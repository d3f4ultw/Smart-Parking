import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'

const base = new URL(process.env.TEST_WEB_BASE_URL ?? 'http://web:3000')
const correo = process.env.TEST_OWNER_EMAIL
const contrasena = process.env.TEST_OWNER_PASSWORD
const rutaDirectorio = '/api/v1/empleados'
const rutaAckHeartbeat = '/api/v1/eventos/administracion/heartbeat'
const eventoHeartbeat = 'empleado.heartbeat'
const eventoDirectorio = 'empleado.directorio.actualizado'

if (!correo || !contrasena) {
  throw new Error('Define TEST_OWNER_EMAIL y TEST_OWNER_PASSWORD desde un env protegido.')
}

class ClienteWeb {
  constructor() {
    this.cookies = new Map()
    this.csrfToken = ''
    this.solicitudes = []
  }

  async solicitar(ruta, opciones = {}) {
    const encabezados = new Headers(opciones.headers)
    const url = new URL(ruta, base)
    const metodo = (opciones.method ?? 'GET').toUpperCase()
    this.solicitudes.push({ metodo, ruta: url.pathname })
    if (!encabezados.has('accept')) encabezados.set('accept', 'application/json')
    if (this.cookies.size) {
      encabezados.set(
        'cookie',
        [...this.cookies].map(([nombre, valor]) => `${nombre}=${valor}`).join('; '),
      )
    }

    const respuesta = await fetch(url, { ...opciones, headers: encabezados })
    for (const cookie of respuesta.headers.getSetCookie()) this.guardarCookie(cookie)
    return respuesta
  }

  guardarCookie(cookie) {
    const par = cookie.split(';', 1)[0]
    const separador = par.indexOf('=')
    if (separador < 1) return
    const nombre = par.slice(0, separador).trim()
    const valor = par.slice(separador + 1).trim()
    if (/;\s*max-age=0(?:;|$)/i.test(cookie) || !valor) this.cookies.delete(nombre)
    else this.cookies.set(nombre, valor)
  }

  contarSolicitudes(metodo, ruta) {
    return this.solicitudes.filter(
      (solicitud) => solicitud.metodo === metodo && solicitud.ruta === ruta,
    ).length
  }

  async autenticar() {
    const respuestaCsrf = await this.solicitar('/api/v1/csrf')
    exigirEstado(respuestaCsrf, 200, 'GET /api/v1/csrf')
    const csrf = await respuestaCsrf.json()
    assert.equal(typeof csrf.token, 'string', 'El BFF debe devolver el token CSRF inicial.')

    const respuestaLogin = await this.solicitar('/api/v1/sesion', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-csrf-token': csrf.token },
      body: JSON.stringify({ correo, contrasena }),
    })
    exigirEstado(respuestaLogin, 200, 'POST /api/v1/sesion')
    const sesion = await respuestaLogin.json()
    assert.equal(sesion.autenticada, true, 'El login de prueba debe abrir una sesión de propietario.')
    assert.equal(sesion.rol, 'DUENO', 'El BFF debe autenticar la cuenta de prueba como DUENO.')
    assert.equal(typeof sesion.csrfToken, 'string', 'El login debe renovar el token CSRF.')
    this.csrfToken = sesion.csrfToken

    const id = this.cookies.get('JSESSIONID')
    assert.ok(id, 'El BFF debe reenviar la cookie JSESSIONID.')
    return id
  }
}

function exigirEstado(respuesta, esperado, operacion) {
  if (respuesta.status !== esperado) {
    throw new Error(`${operacion} devolvió HTTP ${respuesta.status}; se esperaba ${esperado}.`)
  }
}

async function leerDirectorio(cliente) {
  const respuesta = await cliente.solicitar(`${rutaDirectorio}?pagina=1`)
  exigirEstado(respuesta, 200, 'GET /api/v1/empleados')
  const pagina = await respuesta.json()
  assert.ok(Array.isArray(pagina.items) && pagina.items.length > 0, 'El directorio debe tener empleados.')
  assert.equal(typeof pagina.cursorEventos, 'string', 'La página debe incluir el cursor SSE.')
  return pagina
}

async function abrirStream(cliente, cursor, lastEventId = null) {
  const aborto = new AbortController()
  const limite = setTimeout(() => aborto.abort(), 15_000)
  const query = cursor === null ? '' : `?despues=${encodeURIComponent(cursor)}`
  const encabezados = { accept: 'text/event-stream' }
  if (lastEventId) encabezados['last-event-id'] = lastEventId
  let respuesta
  try {
    respuesta = await cliente.solicitar(
      `/api/v1/eventos/administracion${query}`,
      { headers: encabezados, signal: aborto.signal },
    )
  } catch {
    aborto.abort()
    throw new Error('El BFF no abrió el stream SSE dentro del límite de espera.')
  } finally {
    clearTimeout(limite)
  }

  exigirEstado(respuesta, 200, 'GET /api/v1/eventos/administracion')
  assert.match(
    respuesta.headers.get('content-type') ?? '',
    /text\/event-stream/i,
    'El BFF debe conservar Content-Type text/event-stream.',
  )
  assert.ok(respuesta.body, 'El BFF debe mantener abierto el cuerpo SSE.')
  return {
    aborto,
    cliente,
    lector: respuesta.body.getReader(),
    decodificador: new TextDecoder(),
    buffer: '',
    suscripcionId: '',
    secuencia: 0,
    confirmaciones: 0,
  }
}

function analizarEventoSse(trama) {
  let nombre = 'message'
  let id = ''
  let tieneId = false
  const datos = []
  for (const linea of trama.split('\n')) {
    if (!linea || linea.startsWith(':')) continue
    const separador = linea.indexOf(':')
    const campo = separador < 0 ? linea : linea.slice(0, separador)
    const valor = separador < 0 ? '' : linea.slice(separador + 1).replace(/^ /, '')
    if (campo === 'event') nombre = valor
    else if (campo === 'id') {
      id = valor
      tieneId = true
    } else if (campo === 'data') datos.push(valor)
  }
  return { nombre, id, tieneId, datos: datos.join('\n') }
}

async function confirmarHeartbeat(stream, evento) {
  assert.equal(evento.nombre, eventoHeartbeat, 'El BFF debe reenviar el evento de heartbeat.')
  assert.equal(evento.tieneId, false, 'El heartbeat no debe incluir SSE id ni mover Last-Event-ID.')
  const datos = JSON.parse(evento.datos)
  assert.equal(typeof datos.suscripcionId, 'string')
  assert.ok(datos.suscripcionId.length > 0)
  assert.equal(Number.isInteger(datos.secuencia), true)
  assert.ok(datos.secuencia > stream.secuencia, 'La secuencia del heartbeat debe ser nueva.')
  if (stream.suscripcionId) assert.equal(datos.suscripcionId, stream.suscripcionId)

  const directoriosAntes = stream.cliente.contarSolicitudes('GET', rutaDirectorio)
  const respuesta = await stream.cliente.solicitar(rutaAckHeartbeat, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-csrf-token': stream.cliente.csrfToken,
    },
    body: JSON.stringify({ suscripcionId: datos.suscripcionId, secuencia: datos.secuencia }),
  })
  exigirEstado(respuesta, 204, 'POST /api/v1/eventos/administracion/heartbeat')
  assert.equal(await respuesta.text(), '', 'El ACK debe responder 204 sin cuerpo.')
  assert.equal(
    stream.cliente.contarSolicitudes('GET', rutaDirectorio),
    directoriosAntes,
    'El heartbeat y su ACK no deben emitir un GET del directorio.',
  )

  stream.suscripcionId = datos.suscripcionId
  stream.secuencia = datos.secuencia
  stream.confirmaciones += 1
  return datos
}

async function leerEvento(stream, limiteMs = 15_000, nombreEsperado = eventoDirectorio) {
  const vence = Date.now() + limiteMs
  while (Date.now() < vence) {
    stream.buffer = stream.buffer.replace(/\r\n/g, '\n')
    const separador = stream.buffer.indexOf('\n\n')
    if (separador >= 0) {
      const trama = stream.buffer.slice(0, separador)
      stream.buffer = stream.buffer.slice(separador + 2)
      const evento = analizarEventoSse(trama)
      if (evento.nombre === eventoHeartbeat) {
        await confirmarHeartbeat(stream, evento)
        if (nombreEsperado === eventoHeartbeat) return evento
        continue
      }
      if (evento.nombre === nombreEsperado) return evento
      continue
    }

    const restante = vence - Date.now()
    let temporizador
    try {
      const resultado = await Promise.race([
        stream.lector.read(),
        new Promise((_, rechazar) => {
          temporizador = setTimeout(() => rechazar(new Error('SSE_TIMEOUT')), restante)
        }),
      ])
      clearTimeout(temporizador)
      if (resultado.done) throw new Error('El stream SSE se cerró antes de publicar la invalidación.')
      stream.buffer += stream.decodificador.decode(resultado.value, { stream: true })
    } catch (fallo) {
      clearTimeout(temporizador)
      if (fallo instanceof Error && fallo.message === 'SSE_TIMEOUT') {
        throw new Error('No llegó el evento SSE dentro del límite de espera.')
      }
      throw fallo
    }
  }
  throw new Error('No llegó el evento SSE dentro del límite de espera.')
}

async function cerrarStream(stream) {
  stream.aborto.abort()
  await stream.lector.cancel().catch(() => {})
}

async function esperarCierreStream(stream, limiteMs = 30_000) {
  const vence = Date.now() + limiteMs
  while (Date.now() < vence) {
    let temporizador
    try {
      const resultado = await Promise.race([
        stream.lector.read(),
        new Promise((_, rechazar) => {
          temporizador = setTimeout(() => rechazar(new Error('SSE_TIMEOUT')), vence - Date.now())
        }),
      ])
      clearTimeout(temporizador)
      if (resultado.done) return 'eof'
    } catch (fallo) {
      clearTimeout(temporizador)
      if (fallo instanceof Error && fallo.message === 'SSE_TIMEOUT') {
        throw new Error('El BFF mantuvo abierto el stream más de 30 s tras logout.')
      }
      return 'reader-error'
    }
  }
  throw new Error('El BFF mantuvo abierto el stream más de 30 s tras logout.')
}

const sesionA = new ClienteWeb()
const sesionB = new ClienteWeb()
let streamA
let streamB

try {
  const [idSesionA, idSesionB] = await Promise.all([sesionA.autenticar(), sesionB.autenticar()])
  assert.notEqual(idSesionA, idSesionB, 'Las dos sesiones BFF deben usar JSESSIONID distintas.')

  const [paginaA, paginaB] = await Promise.all([leerDirectorio(sesionA), leerDirectorio(sesionB)])
  assert.equal(paginaA.cursorEventos, paginaB.cursorEventos, 'Ambas sesiones deben observar el mismo cursor.')
  const aperturaA = abrirStream(sesionA, paginaA.cursorEventos)
  const aperturaB = abrirStream(sesionB, paginaB.cursorEventos)

  const [flujoA, flujoB] = await Promise.all([aperturaA, aperturaB])
  streamA = flujoA
  streamB = flujoB
  const [heartbeatA, heartbeatB] = await Promise.all([
    leerEvento(streamA, 15_000, eventoHeartbeat),
    leerEvento(streamB, 15_000, eventoHeartbeat),
  ])
  assert.notEqual(streamA.suscripcionId, streamB.suscripcionId, 'Cada pestaña debe mantener su suscripción propia.')
  assert.equal(heartbeatA.tieneId, false)
  assert.equal(heartbeatB.tieneId, false)

  const [paginaTrasAckA, paginaTrasAckB] = await Promise.all([
    leerDirectorio(sesionA),
    leerDirectorio(sesionB),
  ])
  assert.equal(paginaTrasAckA.cursorEventos, paginaA.cursorEventos, 'El ACK no debe avanzar el cursor SSE.')
  assert.equal(paginaTrasAckB.cursorEventos, paginaB.cursorEventos, 'El ACK no debe avanzar el cursor SSE.')

  const inicioIdle = Date.now()
  async function confirmarDuranteIdle(stream) {
    while (Date.now() - inicioIdle < 26_000) {
      await leerEvento(stream, 15_000, eventoHeartbeat)
    }
  }
  await Promise.all([confirmarDuranteIdle(streamA), confirmarDuranteIdle(streamB)])
  assert.ok(Date.now() - inicioIdle >= 25_000, 'Las dos conexiones deben superar 25 s inactivas.')
  assert.ok(streamA.confirmaciones >= 3 && streamB.confirmaciones >= 3,
    'Cada stream debe confirmar heartbeats durante el periodo inactivo.')

  const empleado = paginaA.items[0]
  const estadoNuevo = empleado.estado === 'ACTIVO' ? 'INACTIVO' : 'ACTIVO'
  const cambio = await sesionA.solicitar(`/api/v1/empleados/${empleado.id}/estado`, {
    method: 'PATCH',
    headers: {
      'content-type': 'application/json',
      'x-csrf-token': sesionA.csrfToken,
      'if-match': `"${empleado.revision}"`,
      'idempotency-key': randomUUID(),
    },
    body: JSON.stringify({ estado: estadoNuevo }),
  })
  exigirEstado(cambio, 200, 'PATCH /api/v1/empleados/{id}/estado')

  const [eventoA, eventoB] = await Promise.all([leerEvento(streamA), leerEvento(streamB)])
  assert.equal(eventoA.nombre, eventoDirectorio)
  assert.equal(eventoB.nombre, eventoDirectorio)
  assert.ok(eventoA.id && eventoB.id, 'Cada invalidación de negocio debe incluir cursor.')
  assert.equal(eventoA.id, eventoB.id, 'Las dos sesiones deben recibir la misma invalidación.')
  assert.deepEqual(JSON.parse(eventoA.datos), {})
  assert.deepEqual(JSON.parse(eventoB.datos), {})

  const paginaActualizadaB = await leerDirectorio(sesionB)
  const empleadoB = paginaActualizadaB.items.find((elemento) => elemento.id === empleado.id)
  assert.equal(empleadoB?.estado, estadoNuevo, 'La sesión B debe leer el estado confirmado por A.')

  const cursorAnteriorReplay = paginaActualizadaB.cursorEventos
  const estadoInicial = empleado.estado
  await cerrarStream(streamA)
  await cerrarStream(streamB)
  streamA = undefined
  streamB = undefined

  const paginaActualizadaA = await leerDirectorio(sesionA)
  const empleadoA = paginaActualizadaA.items.find((elemento) => elemento.id === empleado.id)
  assert.ok(empleadoA, 'La sesión A debe conservar el empleado tras la primera mutación.')
  const restauracion = await sesionA.solicitar(`/api/v1/empleados/${empleado.id}/estado`, {
    method: 'PATCH',
    headers: {
      'content-type': 'application/json',
      'x-csrf-token': sesionA.csrfToken,
      'if-match': `"${empleadoA.revision}"`,
      'idempotency-key': randomUUID(),
    },
    body: JSON.stringify({ estado: estadoInicial }),
  })
  exigirEstado(restauracion, 200, 'PATCH de restauración para replay')
  const paginaReplay = await leerDirectorio(sesionA)
  assert.notEqual(paginaReplay.cursorEventos, cursorAnteriorReplay,
    'La segunda mutación debe crear un cursor de negocio nuevo.')

  const streamReplay = await abrirStream(sesionA, null, cursorAnteriorReplay)
  streamA = streamReplay
  const eventoReplay = await leerEvento(streamReplay, 10_000, eventoDirectorio)
  assert.equal(eventoReplay.id, paginaReplay.cursorEventos,
    'Last-Event-ID por BFF debe reproducir la invalidación posterior al cursor.')
  await cerrarStream(streamReplay)
  streamA = undefined

  const sesionLogout = new ClienteWeb()
  await sesionLogout.autenticar()
  const paginaLogout = await leerDirectorio(sesionLogout)
  const streamLogout = await abrirStream(sesionLogout, paginaLogout.cursorEventos)
  streamA = streamLogout
  await leerEvento(streamLogout, 15_000, eventoHeartbeat)
  const inicioLogout = Date.now()
  const respuestaLogout = await sesionLogout.solicitar('/api/v1/sesion', {
    method: 'DELETE',
    headers: { 'x-csrf-token': sesionLogout.csrfToken },
  })
  exigirEstado(respuestaLogout, 200, 'DELETE /api/v1/sesion')
  const estadoLogout = await respuestaLogout.json()
  assert.equal(estadoLogout.autenticada, false, 'El logout debe invalidar la sesión sintética.')
  assert.equal(typeof estadoLogout.csrfToken, 'string', 'El logout debe renovar el token CSRF.')
  const tipoCierreLogout = await esperarCierreStream(streamLogout)
  assert.ok(Date.now() - inicioLogout <= 30_000, 'Logout debe cerrar el stream BFF en 30 s o menos.')
  await cerrarStream(streamLogout)
  streamA = undefined

  process.stdout.write(
    `PASS: ACK BFF sin GET; heartbeat idle >25 s; replay Last-Event-ID; logout cierra stream (${tipoCierreLogout}); ` +
      'cursor intacto durante heartbeat; dos sesiones sincronizadas.\n',
  )
} finally {
  if (streamA) await cerrarStream(streamA)
  if (streamB) await cerrarStream(streamB)
}
