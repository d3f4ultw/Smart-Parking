import {
  createError,
  defineEventHandler,
  getRequestHeader,
  getRequestURL,
  sendStream,
  setResponseHeader,
  type H3Event,
} from 'h3'
import { cookieSesionParaUpstream, reenviarCookiesSesion } from '../utils/cliente-sesion-bff'
import { ALLOWLIST, CONSULTAS } from '../utils/allowlist-bff'
import * as rfid1Bff from '../utils/rfid1-bff'

const RUTA_SESION_DIAGNOSTICA = '/api/v1/sesion'
const MAX_BODY_BYTES = 1_048_576
const VENTANA_ACTIVACION_MS = 15 * 60 * 1000
const BLOQUEO_ACTIVACION_MS = 15 * 60 * 1000
const MAXIMO_FALLOS_ACTIVACION = 5
const MAXIMO_ORIGENES_ACTIVACION = 10_000 // Límite temporal por dirección de socket; no almacena sesión ni datos de la cuenta.
const MAXIMO_ID_EMPLEADO = 9223372036854775807n
const intentosActivacion = new Map<
  string,
  { inicioVentana: number; fallos: number; bloqueadoHasta: number | null }
>()

type CorrelacionSesion = {
  metodo: 'GET' | 'POST'
  requestId: string
  inicioMs: number
}

/** Registra cómo respondió la consulta de sesión, cuánto tardó y su identificador
 * sin guardar contraseñas ni el contenido de la respuesta.
 */
function registrarDiagnosticoSesion(
  correlacion: CorrelacionSesion,
  status: number,
  category: string,
  verificationSucceeded?: boolean,
) {
  const registro = {
    layer: 'bff',
    method: correlacion.metodo,
    route: RUTA_SESION_DIAGNOSTICA,
    requestId: correlacion.requestId,
    status,
    durationMs: Math.max(0, Date.now() - correlacion.inicioMs),
    category,
    ...(correlacion.metodo === 'GET'
      ? { verificationSucceeded: verificationSucceeded === true }
      : {}),
  }
  console.info(`session_diagnostic ${JSON.stringify(registro)}`)
}

/** Resume con una etiqueta cómo respondió el servidor Java al iniciar o consultar
 * una sesión; no guarda el texto completo, que podría incluir datos privados.
 */
function clasificarRespuestaSesion(correlacion: CorrelacionSesion, status: number, texto: string) {
  if (correlacion.metodo === 'POST') {
    if (status === 200) return 'autenticacion_aceptada'
    if (status === 401) return 'credenciales_rechazadas'
    if (status === 403) return 'csrf_rechazado'
    if (status === 503) return 'api_no_disponible'
    return 'respuesta_http'
  }

  if (status !== 200) {
    if (status === 401) return 'sesion_no_vigente'
    if (status === 503) return 'api_no_disponible'
    return 'respuesta_http'
  }

  try {
    const cuerpo: unknown = JSON.parse(texto)
    if (!cuerpo || typeof cuerpo !== 'object' || !('autenticada' in cuerpo)) {
      return 'respuesta_sesion_invalida'
    }
    if (typeof cuerpo.autenticada !== 'boolean') return 'respuesta_sesion_invalida'
    return cuerpo.autenticada ? 'sesion_autenticada' : 'sesion_anonima'
  } catch {
    return 'respuesta_sesion_invalida'
  }
}

/** Lee los datos que envía el navegador por partes y rechaza la solicitud si supera
 * 1 048 576 bytes, aproximadamente un millón.
 */
async function leerCuerpoLimitado(event: H3Event): Promise<ArrayBuffer> {
  const partes: Uint8Array[] = []
  let total = 0
  for await (const fragmento of event.node.req) {
    const parte =
      fragmento instanceof Uint8Array ? fragmento : new TextEncoder().encode(String(fragmento))
    total += parte.byteLength
    if (total > MAX_BODY_BYTES) {
      throw createError({
        statusCode: 413,
        statusMessage: 'El cuerpo supera el tamaño permitido.',
        data: { codigo: 'CUERPO_DEMASIADO_GRANDE' },
      })
    }
    partes.push(parte)
  }
  const buffer = new ArrayBuffer(total)
  const cuerpo = new Uint8Array(buffer)
  let posicion = 0
  for (const parte of partes) {
    cuerpo.set(parte, posicion)
    posicion += parte.byteLength
  }
  return buffer
}

/** Relaciona cada ruta y método admitidos con su operación; también comprueba
 * que los identificadores de las rutas con datos variables tengan un formato válido.
 */
function operacionPermitida(metodo: string, path: string) {
  const exacta = ALLOWLIST.get(`${metodo} ${path}`)
  if (exacta) return exacta
  if (
    metodo === 'POST' &&
    /^\/api\/v1\/accesos\/movimientos\/[1-9]\d{0,18}\/salida-manual$/.test(path)
  ) {
    return 'salida-manual-crear'
  }
  if (
    metodo === 'GET' &&
    /^\/api\/v1\/accesos\/salidas-manuales\/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(
      path,
    )
  ) {
    return 'salida-manual-consultar'
  }
  if (
    metodo === 'PUT' &&
    /^\/api\/v1\/vision\/cajones\/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\/display-name$/i.test(
      path,
    )
  ) {
    return 'vision-nombre-cajon'
  }
  const coincidenciaEmpleado =
    /^\/api\/v1\/empleados\/([1-9]\d{0,18})(\/estado|\/correo|\/operador\/promocion|\/operador\/desactivacion|\/operador\/vinculacion)?$/.exec(
      path,
    )
  if (coincidenciaEmpleado) {
    const idEmpleado = coincidenciaEmpleado[1]
    if (!idEmpleado || BigInt(idEmpleado) > MAXIMO_ID_EMPLEADO) return undefined
    const sufijo = coincidenciaEmpleado[2] ?? ''
    if (metodo === 'GET' && !sufijo) return 'detalle-empleado'
    if (metodo === 'PATCH' && sufijo === '/estado') return 'estado-empleado'
    if (metodo === 'PATCH' && sufijo === '/correo') return 'correo-empleado'
    if (metodo === 'POST' && sufijo === '/operador/promocion') return 'promocion-empleado'
    if (metodo === 'POST' && sufijo === '/operador/desactivacion') return 'desactivacion-empleado'
    if (metodo === 'POST' && sufijo === '/operador/vinculacion') return 'vinculacion-empleado'
  }
  if (
    metodo === 'POST' &&
    /^\/api\/v1\/operadores\/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\/invitacion\/reemitir$/.test(
      path,
    )
  ) {
    return 'reemitir-operador'
  }
  if (
    metodo === 'GET' &&
    /^\/api\/v1\/operadores\/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(path)
  ) {
    return 'detalle-operador'
  }
  if (
    metodo === 'PATCH' &&
    /^\/api\/v1\/operadores\/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\/estado$/.test(path)
  ) {
    return 'estado-operador'
  }
  if (
    metodo === 'POST' &&
    /^\/api\/v1\/operadores\/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\/recuperacion$/.test(path)
  ) {
    return 'solicitar-recuperacion-operador'
  }
  if (
    metodo === 'GET' &&
    /^\/api\/v1\/clientes\/membresia\/checkout\/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(
      path,
    )
  ) {
    return 'cliente-checkout-status'
  }
  if (metodo === 'GET' && /^\/api\/v1\/clientes\/administracion\/CLI-[0-9]{4,}$/.test(path)) {
    return 'detalle-cliente-administracion'
  }
  return undefined
}

/** Rechaza filtros que la operación no admite; en las consultas RFID1 también
 * comprueba que sus valores sean válidos y que no estén repetidos.
 */
function consultaPermitida(url: URL, operacion: string) {
  if (operacion.startsWith('rfid1-')) return rfid1Bff.consultaRfid1Permitida(url, operacion)
  const permitidos = CONSULTAS.get(operacion) ?? []
  return [...new Set(url.searchParams.keys())].every((nombre) => permitidos.includes(nombre))
}

function origenCliente(event: H3Event) {
  const direccion = event.node.req.socket.remoteAddress?.trim()
  return direccion && direccion.length <= 128 ? direccion : 'origen-desconocido'
}

function limpiarIntentosActivacion(ahora: number) {
  for (const [origen, estado] of intentosActivacion) {
    const vencido = estado.bloqueadoHasta
      ? ahora >= estado.bloqueadoHasta
      : ahora >= estado.inicioVentana + VENTANA_ACTIVACION_MS
    if (vencido) intentosActivacion.delete(origen)
  }
}

function activacionBloqueada(origen: string) {
  const ahora = Date.now()
  limpiarIntentosActivacion(ahora)
  const estado = intentosActivacion.get(origen)
  return Boolean(estado?.bloqueadoHasta && ahora < estado.bloqueadoHasta)
}

/** Cuenta los fallos de activación por dirección de conexión y bloquea esa dirección
 * durante 15 minutos al llegar a cinco intentos fallidos en una ventana de 15 minutos.
 */
function registrarFalloActivacion(origen: string) {
  const ahora = Date.now()
  limpiarIntentosActivacion(ahora)
  const anterior = intentosActivacion.get(origen)
  let inicioVentana = ahora
  let fallos = 1
  if (anterior && ahora < anterior.inicioVentana + VENTANA_ACTIVACION_MS) {
    inicioVentana = anterior.inicioVentana
    fallos = anterior.fallos + 1
  }
  intentosActivacion.delete(origen)
  while (intentosActivacion.size >= MAXIMO_ORIGENES_ACTIVACION) {
    const masAntiguo = intentosActivacion.keys().next().value
    if (masAntiguo === undefined) break
    intentosActivacion.delete(masAntiguo)
  }
  intentosActivacion.set(origen, {
    inicioVentana,
    fallos,
    bloqueadoHasta: fallos >= MAXIMO_FALLOS_ACTIVACION ? ahora + BLOQUEO_ACTIVACION_MS : null,
  })
}

function registrarExitoActivacion(origen: string) {
  intentosActivacion.delete(origen)
}

/** Pasa al navegador los avisos de cambio recibidos del servidor Java; si el navegador
 * cierra la conexión, cancela también la lectura para no dejarla abierta sin destinatario.
 */
async function transmitirEventos(
  event: H3Event,
  upstream: ReadableStream<Uint8Array>,
  aborto: AbortController,
) {
  const lector = upstream.getReader()
  const flujo = new ReadableStream<Uint8Array>({
    async pull(controlador) {
      try {
        const parte = await lector.read()
        if (parte.done) controlador.close()
        else controlador.enqueue(parte.value)
      } catch (fallo) {
        controlador.error(fallo)
      }
    },
    async cancel(motivo) {
      aborto.abort()
      await lector.cancel(motivo).catch(() => {})
    },
  })
  const abortar = () => {
    if (event.node.res.writableEnded) return
    aborto.abort()
    void lector.cancel().catch(() => {})
  }
  event.node.res.once('close', abortar)
  try {
    await sendStream(event, flujo)
  } catch (fallo) {
    aborto.abort()
    void lector.cancel(fallo).catch(() => {})
    if (!event.node.res.destroyed && !event.node.res.writableEnded) event.node.res.destroy()
    throw fallo
  } finally {
    event.node.res.off('close', abortar)
    lector.releaseLock()
  }
}

/** Comprueba la ruta, los filtros y los datos, prepara la sesión correspondiente
 * y reenvía solo las acciones previstas al servidor Java.
 */
export default defineEventHandler(async (event) => {
  const url = getRequestURL(event)
  const metodo = event.method.toUpperCase()
  const correlacionSesion: CorrelacionSesion | undefined =
    url.pathname === RUTA_SESION_DIAGNOSTICA && (metodo === 'GET' || metodo === 'POST')
      ? { metodo, requestId: globalThis.crypto.randomUUID(), inicioMs: Date.now() }
      : undefined
  if (correlacionSesion) setResponseHeader(event, 'x-request-id', correlacionSesion.requestId)

  const operacion =
    operacionPermitida(metodo, url.pathname) ??
    rfid1Bff.operacionRfid1Permitida(metodo, url.pathname)
  if (!operacion || !consultaPermitida(url, operacion)) {
    throw createError({ statusCode: 404, statusMessage: 'La ruta no está disponible.' })
  }

  const esOperacionCliente = operacion.startsWith('cliente-')
  const esRfid1 = operacion.startsWith('rfid1-')
  const esConsultaAdministrativaClientes =
    operacion === 'administracion-clientes' || operacion === 'detalle-cliente-administracion'
  if (esOperacionCliente || esConsultaAdministrativaClientes || esRfid1) {
    setResponseHeader(event, 'cache-control', 'no-store, private')
    setResponseHeader(event, 'vary', 'Cookie')
    setResponseHeader(event, 'referrer-policy', 'no-referrer')
  }
  const esActivacion = operacion === 'validar-operador' || operacion === 'activar-operador'
  const esRecuperacionPublica =
    operacion === 'validar-recuperacion' || operacion === 'completar-recuperacion'
  const origen = esActivacion ? origenCliente(event) : ''
  if (esActivacion) {
    setResponseHeader(event, 'cache-control', 'no-store, private')
    setResponseHeader(event, 'vary', 'Cookie')
    setResponseHeader(event, 'referrer-policy', 'no-referrer')
    if (activacionBloqueada(origen)) {
      event.node.res.statusCode = 429
      return { codigo: 'ACTIVACION_LIMITADA', error: 'Se alcanzó el límite temporal de intentos.' }
    }
  }
  if (esRecuperacionPublica) {
    setResponseHeader(event, 'cache-control', 'no-store, private')
    setResponseHeader(event, 'referrer-policy', 'no-referrer')
  }

  const largoDeclarado = Number(getRequestHeader(event, 'content-length') ?? 0)
  if (Number.isFinite(largoDeclarado) && largoDeclarado > MAX_BODY_BYTES) {
    throw createError({
      statusCode: 413,
      statusMessage: 'El cuerpo supera el tamaño permitido.',
      data: { codigo: 'CUERPO_DEMASIADO_GRANDE' },
    })
  }
  const config = useRuntimeConfig(event)
  if (!config.apiInternalBase) {
    if (correlacionSesion) {
      registrarDiagnosticoSesion(correlacionSesion, 503, 'configuracion_api_ausente', false)
    }
    throw createError({
      statusCode: 503,
      statusMessage: 'La conexión no está disponible.',
      data: { codigo: 'API_NO_DISPONIBLE' },
    })
  }

  const headers = new Headers()
  for (const nombre of ['content-type', 'accept', 'x-csrf-token']) {
    const valor = getRequestHeader(event, nombre)
    if (valor) headers.set(nombre, valor)
  }
  if (correlacionSesion) headers.set('x-request-id', correlacionSesion.requestId)
  const cookieSesion = cookieSesionParaUpstream(
    getRequestHeader(event, 'cookie'),
    esOperacionCliente ? 'cliente' : 'administrativa',
  )
  if (cookieSesion) headers.set('cookie', cookieSesion)
  if (operacion === 'panel') {
    const etag = getRequestHeader(event, 'if-none-match')
    if (etag) headers.set('if-none-match', etag)
  }
  if (
    operacion === 'crear-empleado' ||
    operacion === 'crear-operador' ||
    operacion === 'reemitir-operador' ||
    operacion === 'estado-operador' ||
    operacion === 'solicitar-recuperacion-operador' ||
    operacion === 'cliente-checkout' ||
    operacion === 'correo-empleado' ||
    operacion === 'promocion-empleado' ||
    operacion === 'desactivacion-empleado' ||
    operacion === 'vinculacion-empleado' ||
    operacion === 'rfid1-crear' ||
    operacion === 'rfid1-confirmar' ||
    operacion === 'salida-manual-crear'
  ) {
    const clave = getRequestHeader(event, 'idempotency-key')
    if (clave) headers.set('idempotency-key', clave)
  }
  if (
    operacion === 'estado-operador' ||
    operacion === 'reemitir-operador' ||
    operacion === 'solicitar-recuperacion-operador'
  ) {
    const revision = getRequestHeader(event, 'if-match')
    if (revision) headers.set('if-match', revision)
  }
  if (
    operacion === 'estado-empleado' ||
    operacion === 'correo-empleado' ||
    operacion === 'promocion-empleado' ||
    operacion === 'desactivacion-empleado' ||
    operacion === 'vinculacion-empleado'
  ) {
    const revision = getRequestHeader(event, 'if-match')
    if (revision) headers.set('if-match', revision)
  }
  if (operacion === 'eventos') {
    const ultimoEvento = getRequestHeader(event, 'last-event-id')
    if (ultimoEvento) headers.set('last-event-id', ultimoEvento)
  }

  const tieneCuerpo = largoDeclarado > 0 || Boolean(getRequestHeader(event, 'transfer-encoding'))
  let body: ArrayBuffer | undefined
  if (['POST', 'PATCH', 'DELETE'].includes(metodo) || tieneCuerpo) {
    body = await leerCuerpoLimitado(event)
    if (metodo === 'GET' && body.byteLength > 0) {
      throw createError({ statusCode: 400, statusMessage: 'La solicitud no admite cuerpo.' })
    }
  }
  if (esRfid1) {
    rfid1Bff.validarCuerpoRfid1(operacion, body, getRequestHeader(event, 'content-type'))
  }

  const upstream = new URL(url.pathname, `${String(config.apiInternalBase).replace(/\/$/, '')}/`)
  upstream.search = url.search
  const abortController = new AbortController()
  const abortarCliente = () => {
    if (!event.node.res.writableEnded) abortController.abort()
  }
  event.node.res.once('close', abortarCliente)
  event.node.req.once('aborted', abortarCliente)

  let etapaUpstream: 'solicitud' | 'lectura' = 'solicitud'
  try {
    const respuesta = await fetch(upstream, {
      method: metodo,
      headers,
      body,
      signal: abortController.signal,
      redirect: 'manual',
    })
    reenviarCookiesSesion(
      event,
      respuesta.headers.getSetCookie(),
      esOperacionCliente ? 'cliente' : 'administrativa',
    )
    setResponseHeader(event, 'cache-control', 'no-store, private')
    setResponseHeader(event, 'vary', 'Cookie')
    if (esActivacion || esRecuperacionPublica) {
      setResponseHeader(event, 'referrer-policy', 'no-referrer')
    }
    for (const nombre of [
      'content-type',
      'etag',
      'retry-after',
      'referrer-policy',
      'x-accel-buffering',
    ]) {
      const valor = respuesta.headers.get(nombre)
      if (valor) setResponseHeader(event, nombre, valor)
    }
    if (operacion === 'vision-cajones') {
      for (const nombre of ['x-eventos-cursor', 'x-vision-vigencia-restante-ms']) {
        const valor = respuesta.headers.get(nombre)
        if (valor !== null) setResponseHeader(event, nombre, valor)
      }
    }
    const esFlujoEventos =
      operacion === 'eventos' &&
      respuesta.headers.get('content-type')?.includes('text/event-stream')
    if (esFlujoEventos) {
      setResponseHeader(event, 'cache-control', 'no-store, private')
      setResponseHeader(event, 'x-accel-buffering', 'no')
    }
    event.node.res.statusCode = respuesta.status
    if (esActivacion) {
      if (respuesta.status === 400 || respuesta.status === 410) registrarFalloActivacion(origen)
      else if (respuesta.ok) registrarExitoActivacion(origen)
    }
    if (respuesta.status === 204 || respuesta.status === 304 || !respuesta.body) {
      if (correlacionSesion) {
        registrarDiagnosticoSesion(
          correlacionSesion,
          respuesta.status,
          clasificarRespuestaSesion(correlacionSesion, respuesta.status, ''),
          false,
        )
      }
      return null
    }
    if (esFlujoEventos) {
      await transmitirEventos(event, respuesta.body, abortController)
      return null
    }
    etapaUpstream = 'lectura'
    const texto = await respuesta.text()
    if (correlacionSesion) {
      const category = clasificarRespuestaSesion(correlacionSesion, respuesta.status, texto)
      const verificationSucceeded =
        correlacionSesion.metodo === 'GET' && category === 'sesion_autenticada'
      registrarDiagnosticoSesion(
        correlacionSesion,
        respuesta.status,
        category,
        verificationSucceeded,
      )
    }
    return texto
  } catch (fallo) {
    if (abortController.signal.aborted) {
      if (correlacionSesion) {
        registrarDiagnosticoSesion(correlacionSesion, 0, 'solicitud_cancelada', false)
      }
      return null
    }
    if (typeof fallo === 'object' && fallo !== null && 'statusCode' in fallo) {
      if (correlacionSesion) {
        const estado = typeof fallo.statusCode === 'number' ? fallo.statusCode : 503
        registrarDiagnosticoSesion(correlacionSesion, estado, 'error_bff', false)
      }
      throw fallo
    }
    setResponseHeader(event, 'cache-control', 'no-store, private')
    if (esActivacion || esRecuperacionPublica) {
      setResponseHeader(event, 'referrer-policy', 'no-referrer')
    }
    event.node.res.statusCode = 503
    if (correlacionSesion) {
      registrarDiagnosticoSesion(
        correlacionSesion,
        503,
        etapaUpstream === 'lectura' ? 'lectura_upstream_fallida' : 'transporte_upstream_fallido',
        false,
      )
    }
    return { codigo: 'API_NO_DISPONIBLE', error: 'No fue posible conectar con Smart Parking.' }
  } finally {
    event.node.res.off('close', abortarCliente)
    event.node.req.off('aborted', abortarCliente)
  }
})
