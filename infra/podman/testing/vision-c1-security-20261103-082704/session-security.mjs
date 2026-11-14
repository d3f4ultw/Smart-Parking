import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { createInterface } from 'node:readline'
import { chromium, request } from '@playwright/test'

const webBase = process.env.QA_WEB_BASE_URL ?? 'http://web:3000'
const apiBase = process.env.QA_API_BASE_URL ?? 'http://api:8080'
const mailpitBase = process.env.QA_MAILPIT_API_BASE_URL ?? 'http://mailpit:8025'
const ownerEmail = process.env.TEST_OWNER_EMAIL
const ownerPassword = process.env.TEST_OWNER_PASSWORD
const webUrl = new URL(webBase)
const apiUrl = new URL(apiBase)
const mailpitUrl = new URL(mailpitBase)

function exigirEntornoAislado() {
  assert.equal(webUrl.protocol, 'http:')
  assert.equal(webUrl.hostname, 'web')
  assert.equal(webUrl.port, '3000')
  assert.equal(apiUrl.protocol, 'http:')
  assert.equal(apiUrl.hostname, 'api')
  assert.equal(apiUrl.port, '8080')
  assert.equal(mailpitUrl.protocol, 'http:')
  assert.equal(mailpitUrl.hostname, 'mailpit')
  assert.equal(mailpitUrl.port, '8025')
  assert.ok(ownerEmail && ownerPassword, 'Faltan credenciales sintéticas DUENO.')
}

function exigir(verdadero, etiqueta) {
  assert.ok(verdadero, etiqueta)
}

function esperar(ms) {
  return new Promise((resolver) => setTimeout(resolver, ms))
}

async function esperarHabilitado(locator, limiteMs = 10_000) {
  const limite = Date.now() + limiteMs
  while (Date.now() < limite) {
    if (await locator.isEnabled()) return
    await esperar(100)
  }
  assert.fail('El control requerido no se habilitó a tiempo.')
}

async function iniciarSesionWeb(page) {
  await page.goto(`${webBase}/panel`)
  await page.getByLabel('Correo electrónico').fill(ownerEmail)
  await page.getByRole('button', { name: 'Mostrar contraseña', exact: true }).click()
  await page.getByRole('textbox', { name: 'Contraseña' }).fill(ownerPassword)
  await page.getByRole('button', { name: 'Ocultar contraseña', exact: true }).click()
  await page.getByRole('button', { name: 'Iniciar sesión' }).click({ noWaitAfter: true })
  await page.waitForURL((url) => url.pathname === '/admin', { timeout: 20_000 })
  await page.getByRole('region', { name: 'Ocupación física' }).waitFor({ state: 'visible' })
}

async function iniciarSesionApi() {
  const contexto = await request.newContext({ baseURL: apiBase, timeout: 15_000 })
  const csrfRespuesta = await contexto.get('/api/v1/csrf')
  assert.equal(csrfRespuesta.status(), 200, 'GET CSRF DUENO')
  const token = String((await csrfRespuesta.json()).token)
  const respuesta = await contexto.post('/api/v1/sesion', {
    data: { correo: ownerEmail, contrasena: ownerPassword },
    headers: { 'X-CSRF-TOKEN': token },
  })
  assert.equal(respuesta.status(), 200, 'POST login DUENO')
  const cuerpo = await respuesta.json()
  assert.equal(cuerpo.rol, 'DUENO', 'El login sintético debe ser DUENO')
  return contexto
}

async function obtenerCsrf(contexto, ruta = '/api/v1/csrf') {
  const respuesta = await contexto.get(ruta)
  assert.equal(respuesta.status(), 200, `GET CSRF ${ruta}`)
  return String((await respuesta.json()).token)
}

function crearCredencialesSinteticas(prefijo) {
  const id = randomUUID()
  return {
    correo: `qa-${prefijo}-${id}@example.test`,
    contrasena: `${randomUUID()}Aa9!`,
    sufijo: id.slice(0, 8),
  }
}

async function crearClienteSintetico() {
  const rutaCredenciales = process.env.QA_CLIENT_CREDENTIALS_FILE
  const credenciales = rutaCredenciales
    ? JSON.parse(await readFile(rutaCredenciales, 'utf8'))
    : crearCredencialesSinteticas('cliente')
  assert.ok(credenciales.correo && credenciales.contrasena,
    'El fixture privado del CLIENTE debe incluir credenciales sintéticas.')
  const contexto = await request.newContext({ baseURL: apiBase, timeout: 20_000 })
  try {
    const csrf = await obtenerCsrf(contexto, '/api/v1/clientes/csrf')
    const registro = await contexto.post('/api/v1/clientes/registro', {
      data: {
        nombres: 'QA Seguridad',
        primerApellido: 'Sintetico',
        segundoApellido: null,
        correo: credenciales.correo,
        contrasena: credenciales.contrasena,
      },
      headers: { 'X-CSRF-TOKEN': csrf },
    })
    assert.equal(registro.status(), 201, 'Registro del CLIENTE sintético en API descartable')
    return credenciales
  } finally {
    await contexto.dispose()
  }
}

async function obtenerTokenInvitacion(correo) {
  for (let intento = 0; intento < 20; intento++) {
    const lista = await fetch(`${mailpitBase}/api/v1/messages?start=0&limit=50`)
    assert.equal(lista.status, 200, 'Mailpit API debe estar disponible en la red interna')
    const indice = await lista.json()
    const mensajes = indice.messages ?? indice.Messages ?? []
    const mensaje = mensajes.find((elemento) =>
      JSON.stringify(elemento.To ?? elemento.to ?? []).toLowerCase().includes(correo.toLowerCase()),
    )
    const id = mensaje?.ID ?? mensaje?.Id ?? mensaje?.id
    if (id) {
      const detalle = await fetch(`${mailpitBase}/api/v1/message/${encodeURIComponent(id)}`)
      assert.equal(detalle.status, 200, 'Mailpit debe devolver el mensaje sintético')
      const cuerpo = await detalle.json()
      const contenido = `${cuerpo.Text ?? cuerpo.text ?? ''}\n${cuerpo.HTML ?? cuerpo.html ?? ''}`
        .replaceAll('&amp;', '&')
      const enlaces = contenido.match(/https?:\/\/[^\s"'<>]+/g) ?? []
      for (const enlace of enlaces) {
        try {
          const url = new URL(enlace.replace(/[),.;]+$/, ''))
          const token = decodeURIComponent(url.hash.slice(1))
          if (token.length >= 16) return token
        } catch {
          // Ignora contenido que parezca URL pero no sea un enlace válido.
        }
      }
      throw new Error('El mensaje sintético no incluyó el fragmento de activación esperado.')
    }
    await esperar(250)
  }
  throw new Error('No llegó a Mailpit la invitación sintética del OPERADOR.')
}

async function crearOperadorSintetico() {
  const rutaCredenciales = process.env.QA_OPERATOR_CREDENTIALS_FILE
  if (rutaCredenciales) {
    const credenciales = JSON.parse(await readFile(rutaCredenciales, 'utf8'))
    assert.ok(credenciales.correo && credenciales.contrasena,
      'El fixture privado del OPERADOR debe incluir credenciales sintéticas.')
    return credenciales
  }

  const credenciales = crearCredencialesSinteticas('operador')
  const propietario = await iniciarSesionApi()
  let activacion
  try {
    const csrf = await obtenerCsrf(propietario)
    const empleado = await propietario.post('/api/v1/empleados', {
      data: {
        nombres: 'QA Seguridad',
        primerApellido: 'Sintetico',
        segundoApellido: null,
      },
      headers: { 'X-CSRF-TOKEN': csrf, 'Idempotency-Key': randomUUID() },
    })
    assert.equal(empleado.status(), 201, 'Alta del empleado sintético vinculado')
    const id = String((await empleado.json()).id)
    const detalle = await propietario.get(`/api/v1/empleados/${encodeURIComponent(id)}`)
    assert.equal(detalle.status(), 200)
    const revisionEmpleado = detalle.headers()['etag']
    assert.ok(revisionEmpleado, 'El detalle del empleado debe incluir ETag')
    const promocion = await propietario.post(`/api/v1/empleados/${encodeURIComponent(id)}/operador/promocion`, {
      data: { correo: credenciales.correo },
      headers: {
        'X-CSRF-TOKEN': csrf,
        'If-Match': revisionEmpleado,
        'Idempotency-Key': randomUUID(),
      },
    })
    if (promocion.status() !== 200) {
      const cuerpoError = await promocion.json().catch(() => ({}))
      const valorCodigo = cuerpoError && typeof cuerpoError.codigo === 'string'
        ? cuerpoError.codigo
        : ''
      const codigo = /^[A-Z0-9_]{1,64}$/.test(valorCodigo) ? valorCodigo : 'SIN_CODIGO'
      console.error(`EVIDENCIA promocion_operador status=${promocion.status()} codigo=${codigo}`)
    }
    assert.equal(promocion.status(), 200, 'Promoción del empleado a OPERADOR con invitación Mailpit')
    activacion = await request.newContext({ baseURL: apiBase, timeout: 20_000 })
    const csrfActivacion = await obtenerCsrf(activacion)
    const token = await obtenerTokenInvitacion(credenciales.correo)
    const validacion = await activacion.post('/api/v1/operadores/activacion/validar', {
      data: { token },
      headers: { 'X-CSRF-TOKEN': csrfActivacion },
    })
    assert.equal(validacion.status(), 200, 'Validación de invitación interna')
    assert.equal((await validacion.json()).valida, true)
    const completada = await activacion.post('/api/v1/operadores/activacion/completar', {
      data: {
        token,
        contrasena: credenciales.contrasena,
        confirmarContrasena: credenciales.contrasena,
      },
      headers: { 'X-CSRF-TOKEN': csrfActivacion },
    })
    assert.equal(completada.status(), 204, 'Activación sintética del OPERADOR')
  } finally {
    await activacion?.dispose()
    await propietario.dispose()
  }
  return credenciales
}

async function comprobarRolEnApiYBff(rol, credenciales) {
  const csrfRuta = rol === 'CLIENTE' ? '/api/v1/clientes/csrf' : '/api/v1/csrf'
  const sesionRuta = rol === 'CLIENTE' ? '/api/v1/clientes/sesion' : '/api/v1/sesion'
  for (const baseURL of [apiBase, webBase]) {
    const contexto = await request.newContext({ baseURL, timeout: 20_000 })
    try {
      const csrf = await obtenerCsrf(contexto, csrfRuta)
      const login = await contexto.post(sesionRuta, {
        data: { correo: credenciales.correo, contrasena: credenciales.contrasena },
        headers: { 'X-CSRF-TOKEN': csrf },
      })
      assert.equal(login.status(), 200, `Login sintético ${rol}`)
      const cuerpo = await login.json()
      assert.equal(cuerpo.rol, rol, `La sesión autenticada debe conservar rol ${rol}`)
      const sesionAntes = await contexto.get(sesionRuta)
      assert.equal(sesionAntes.status(), 200, `La sesión ${rol} debe seguir autenticada antes de consultar Vision`)
      assert.equal((await sesionAntes.json()).autenticada, true)
      const vision = await contexto.get('/api/v1/vision/cajones')
      assert.ok([401, 403].includes(vision.status()),
        `${rol} debe recibir 401 o 403 desde ${baseURL === apiBase ? 'Java' : 'BFF'}`)
      console.log(`EVIDENCIA autorizacion ${rol} capa=${baseURL === apiBase ? 'Java' : 'BFF'} vision=${vision.status()}`)
      const csrfCierre = await obtenerCsrf(contexto, csrfRuta)
      const cierre = await contexto.delete(sesionRuta, { headers: { 'X-CSRF-TOKEN': csrfCierre } })
      const estadoLogout = rol === 'CLIENTE' ? 204 : 200
      assert.equal(cierre.status(), estadoLogout, `Logout sintético ${rol}`)
    } finally {
      await contexto.dispose()
    }
  }
  console.log(`PASS autorizacion ${rol} denegado en Java y BFF`)
}

function observarPeticiones(page) {
  const conteos = { visionGet: 0, heartbeatAck: 0, sseGet: 0 }
  const fallosAck = []
  const estadosAck = []
  const estadosSse = []
  const fallosSse = []
  page.on('request', (solicitud) => {
    let ruta
    try {
      ruta = new URL(solicitud.url()).pathname
    } catch {
      return
    }
    if (ruta === '/api/v1/vision/cajones' && solicitud.method() === 'GET') conteos.visionGet++
    if (ruta === '/api/v1/eventos/administracion/heartbeat' && solicitud.method() === 'POST') {
      conteos.heartbeatAck++
    }
    if (ruta === '/api/v1/eventos/administracion' && solicitud.method() === 'GET') conteos.sseGet++
  })
  page.on('response', (respuesta) => {
    const ruta = new URL(respuesta.url()).pathname
    if (ruta === '/api/v1/eventos/administracion/heartbeat') {
      estadosAck.push(respuesta.status())
      if (respuesta.status() !== 204) fallosAck.push(respuesta.status())
    }
    if (ruta === '/api/v1/eventos/administracion') {
      estadosSse.push({
        estado: respuesta.status(),
        tipoContenido: respuesta.headers()['content-type'] ?? '',
      })
    }
  })
  page.on('requestfailed', (solicitud) => {
    let ruta
    try {
      ruta = new URL(solicitud.url()).pathname
    } catch {
      return
    }
    if (ruta === '/api/v1/eventos/administracion/heartbeat') fallosAck.push('red')
    if (ruta === '/api/v1/eventos/administracion') fallosSse.push('red')
  })
  return { conteos, fallosAck, estadosAck, estadosSse, fallosSse }
}

async function probarPasivoEInactivo() {
  const pasivoMs = Number(process.env.QA_PASSIVE_MS ?? 130_000)
  const esperaInactividadMs = Number(process.env.QA_IDLE_MS ?? 70_000)
  assert.ok(Number.isSafeInteger(pasivoMs) && pasivoMs >= 120_000)
  assert.ok(Number.isSafeInteger(esperaInactividadMs) && esperaInactividadMs >= 65_000)

  const navegador = await chromium.launch({ headless: true })
  const pagina = await navegador.newPage()
  const { conteos, fallosAck, estadosAck, estadosSse, fallosSse } = observarPeticiones(pagina)
  let inicioPasivo = 0
  let inactivo

  try {
    await iniciarSesionWeb(pagina)
    inicioPasivo = Date.now()
    assert.equal(await pagina.evaluate(() => document.visibilityState), 'visible')
    inactivo = await iniciarSesionApi()
    const inicioInactivo = Date.now()
    const verificacionInactiva = (async () => {
      await esperar(esperaInactividadMs)
      const transcurridoMs = Date.now() - inicioInactivo
      const protegida = await inactivo.get('/api/v1/vision/cajones')
      assert.equal(protegida.status(), 401, 'Una sesión sin solicitudes debe expirar en Tomcat')
      const sesion = await inactivo.get('/api/v1/sesion')
      assert.equal(sesion.status(), 200, 'GET /sesion es público tras expirar')
      const cuerpo = await sesion.json()
      assert.equal(cuerpo.autenticada, false, 'Tomcat no debe conservar la autenticación inactiva')
      return { transcurridoMs, estadoProtegido: protegida.status() }
    })()

    await pagina.waitForTimeout(pasivoMs)
    const autenticacion = await pagina.evaluate(async () => {
      const respuesta = await fetch('/api/v1/sesion', { credentials: 'same-origin' })
      return { estado: respuesta.status, cuerpo: await respuesta.json() }
    })
    assert.equal(autenticacion.estado, 200, 'La revalidación de la sesión pasiva debe responder 200')
    assert.equal(autenticacion.cuerpo.autenticada, true, 'El tablero visible debe seguir autenticado')
    assert.equal(autenticacion.cuerpo.rol, 'DUENO')
    assert.equal(await pagina.evaluate(() => document.visibilityState), 'visible')
    await pagina.waitForURL((url) => url.pathname === '/admin', { timeout: 2_000 })
    await pagina.getByRole('region', { name: 'Ocupación física' }).waitFor({ state: 'visible' })

    const inactiva = await verificacionInactiva
    const duracionPasivaMs = Date.now() - inicioPasivo
    exigir(duracionPasivaMs >= 120_000, 'El periodo pasivo medido debe superar 120 s')
    exigir(conteos.sseGet === 1, 'Debe existir una sola conexión SSE administrativa')
    exigir(estadosSse.length === 1 && estadosSse[0].estado === 200,
      'La conexión SSE debe aceptar HTTP 200')
    exigir(estadosSse[0].tipoContenido.includes('text/event-stream'),
      'La respuesta SSE debe tener Content-Type text/event-stream')
    exigir(fallosSse.length === 0, 'La conexión SSE no debe fallar durante la observación')
    exigir(conteos.heartbeatAck >= 5, 'No se observaron ACK autenticados suficientes durante el periodo')
    exigir(estadosAck.length === conteos.heartbeatAck && estadosAck.every((estado) => estado === 204),
      'Todos los ACK de la sesión activa deben responder 204')
    exigir(conteos.visionGet >= 2, 'No se observaron reconciliaciones Vision durante el periodo')
    exigir(fallosAck.length === 0, 'Un ACK de la sesión activa fue rechazado')

    console.log(
      `PASS sesiones pasiva_ms=${duracionPasivaMs} inactiva_ms=${inactiva.transcurridoMs}`
      + ` vision_get=${conteos.visionGet} sse_get=${conteos.sseGet}`
      + ` sse_status=${estadosSse[0].estado} sse_fallos=${fallosSse.length}`
      + ` heartbeat_ack=${conteos.heartbeatAck} heartbeat_204=${estadosAck.filter((estado) => estado === 204).length}`
      + ` heartbeat_fallos=${fallosAck.length}`
      + ` inactiva_status=${inactiva.estadoProtegido}`,
    )
  } finally {
    await inactivo?.dispose()
    await pagina.close()
    await navegador.close()
  }
}

function crearCompuerta() {
  let abrir
  let listo
  let terminado
  const promesaApertura = new Promise((resolver) => { abrir = resolver })
  const promesaLista = new Promise((resolver) => { listo = resolver })
  const promesaTerminada = new Promise((resolver) => { terminado = resolver })
  return {
    promesaApertura,
    promesaLista,
    promesaTerminada,
    abrir,
    listo,
    terminado,
  }
}

async function probarLogoutConRespuestasTardias() {
  const navegador = await chromium.launch({ headless: true })
  const contexto = await navegador.newContext()
  const pagina = await contexto.newPage()
  let apiDueno
  const conteos = { visionGet: 0, visionGetTrasLogout: 0 }
  const ack = crearCompuerta()
  const vision = crearCompuerta()
  let interceptarAck = true
  let interceptarVision = true
  let estadoAck = 0
  let estadoVision = 0
  let estadoCsrfInvalido = 0
  let estadoAckRevocado = 0
  let ackEntregado = false
  let visionEntregada = false
  let horaLogout = 0

  try {
    await pagina.addInitScript(() => {
      const nativo = window.EventSource
      const fuentes = []
      const capturado = new Proxy(nativo, {
        construct(objetivo, argumentos, nuevoObjetivo) {
          const fuente = Reflect.construct(objetivo, argumentos, nuevoObjetivo)
          fuentes.push(fuente)
          return fuente
        },
      })
      Object.defineProperty(window, '__qaFuentesSse', { value: fuentes })
      Object.defineProperty(window, 'EventSource', { configurable: true, writable: true, value: capturado })
    })
    pagina.on('request', (solicitud) => {
      if (new URL(solicitud.url()).pathname === '/api/v1/vision/cajones' && solicitud.method() === 'GET') {
        conteos.visionGet++
        if (horaLogout && Date.now() >= horaLogout) conteos.visionGetTrasLogout++
      }
    })
    await pagina.route('**/api/v1/eventos/administracion/heartbeat', async (ruta) => {
      if (!interceptarAck) return ruta.continue()
      interceptarAck = false
      try {
        const respuesta = await ruta.fetch()
        estadoAck = respuesta.status()
        ack.listo()
        await ack.promesaApertura
        try {
          await ruta.fulfill({ response: respuesta })
          ackEntregado = true
        } catch { /* El resultado permanece fallido si Logout aborta el consumidor. */ }
      } catch {
        ack.listo()
      } finally {
        ack.terminado()
      }
    })
    await iniciarSesionWeb(pagina)
    await Promise.race([
      ack.promesaLista,
      esperar(15_000).then(() => { throw new Error('No llegó un ACK SSE al harness.') }),
    ])
    assert.equal(estadoAck, 204, 'El ACK capturado debe haber sido aceptado antes del logout')

    await pagina.route('**/api/v1/vision/cajones', async (ruta) => {
      if (!interceptarVision) return ruta.continue()
      interceptarVision = false
      try {
        const respuesta = await ruta.fetch()
        estadoVision = respuesta.status()
        vision.listo()
        await vision.promesaApertura
        try {
          await ruta.fulfill({ response: respuesta })
          visionEntregada = true
        } catch { /* El resultado permanece fallido si Logout aborta el consumidor. */ }
      } catch {
        vision.listo()
      } finally {
        vision.terminado()
      }
    })
    const botonActualizar = pagina.getByRole('region', { name: 'Ocupación física' })
      .getByRole('button', { name: 'Actualizar' })
    await esperarHabilitado(botonActualizar)
    await botonActualizar.click()
    await Promise.race([
      vision.promesaLista,
      esperar(15_000).then(() => { throw new Error('No llegó la GET Vision que debía quedar pendiente.') }),
    ])
    assert.ok([200, 401, 403].includes(estadoVision), 'La GET capturada debe tener respuesta HTTP')

    await pagina.getByRole('button', { name: 'Cerrar sesión' }).click()
    await pagina.waitForURL((url) => url.pathname === '/panel', { timeout: 15_000 })
    horaLogout = Date.now()
    ack.abrir()
    vision.abrir()
    await Promise.all([ack.promesaTerminada, vision.promesaTerminada])

    const despachoTardio = await pagina.evaluate(() => {
      const fuentes = window.__qaFuentesSse ?? []
      const fuente = fuentes.at(-1)
      if (!fuente) return { existe: false, cerrada: false }
      fuente.dispatchEvent(new MessageEvent('vision.ocupacion.actualizada', { data: '{}' }))
      return { existe: true, cerrada: fuente.readyState === window.EventSource.CLOSED }
    })
    assert.equal(despachoTardio.existe, true, 'Se debe capturar la conexión SSE administrativa')
    assert.equal(despachoTardio.cerrada, true, 'El callback tardío debe pertenecer a un EventSource cerrado')
    await pagina.waitForTimeout(1_000)
    const getPorEventoTardio = conteos.visionGetTrasLogout
    assert.equal(getPorEventoTardio, 0, 'El evento tardío no debe disparar otra GET Vision')
    assert.equal(ackEntregado, true, 'El ACK guardado debe entregarse al navegador después del logout')
    assert.equal(visionEntregada, true, 'La GET guardada debe entregarse al navegador después del logout')
    const accesoPosterior = await pagina.evaluate(async () => {
      const respuesta = await fetch('/api/v1/vision/cajones', { credentials: 'same-origin' })
      return respuesta.status
    })
    assert.equal(accesoPosterior, 401, 'Una solicitud posterior al logout debe recibir 401')
    assert.equal(await pagina.getByRole('region', { name: 'Ocupación física' }).count(), 0)

    apiDueno = await iniciarSesionApi()
    const csrfRespuesta = await apiDueno.get('/api/v1/csrf')
    assert.equal(csrfRespuesta.status(), 200)
    const csrf = String((await csrfRespuesta.json()).token)
    const estadoAnterior = await apiDueno.storageState()
    const csrfInvalido = await apiDueno.post('/api/v1/eventos/administracion/heartbeat', {
      data: { suscripcionId: randomUUID(), secuencia: 1 },
      headers: { 'X-CSRF-TOKEN': 'token-sintetico-invalido' },
    })
    estadoCsrfInvalido = csrfInvalido.status()
    assert.equal(estadoCsrfInvalido, 403, 'Un ACK con CSRF incorrecto debe recibir 403')
    const cierreApi = await apiDueno.delete('/api/v1/sesion', {
      headers: { 'X-CSRF-TOKEN': csrf },
    })
    assert.equal(cierreApi.status(), 200)
    const sesionAntigua = await request.newContext({ baseURL: apiBase, storageState: estadoAnterior })
    let ackAntiguo
    try {
      ackAntiguo = await sesionAntigua.post('/api/v1/eventos/administracion/heartbeat', {
        data: { suscripcionId: randomUUID(), secuencia: 1 },
        headers: { 'X-CSRF-TOKEN': csrf },
      })
      estadoAckRevocado = ackAntiguo.status()
      assert.ok([401, 403].includes(estadoAckRevocado), 'El ACK con cookie revocada debe denegarse')
    } finally {
      await sesionAntigua.dispose()
      await apiDueno.dispose()
      apiDueno = undefined
    }

    console.log(
      `PASS logout ack_tardio=${estadoAck} get_tardia=${estadoVision}`
      + ` ack_entregado=${ackEntregado} get_entregada=${visionEntregada}`
      + ` get_posterior=${accesoPosterior} get_por_evento_tardio=${getPorEventoTardio}`
      + ` csrf_invalido=${estadoCsrfInvalido} ack_cookie_revocada=${estadoAckRevocado}`,
    )
  } finally {
    ack.abrir()
    vision.abrir()
    await apiDueno?.dispose()
    await contexto.close()
    await navegador.close()
  }
}

async function esperarSenal(nombre) {
  const lector = createInterface({ input: process.stdin })
  try {
    for await (const linea of lector) {
      if (linea.trim() === nombre) return
    }
  } finally {
    lector.close()
  }
  throw new Error(`No se recibió la señal ${nombre}.`)
}

async function probarRevocacionRemota() {
  const navegador = await chromium.launch({ headless: true })
  const pagina = await navegador.newPage()
  let horaRevocacion = 0
  const solicitudesVisionPosteriores = []
  const iniciosVision = new WeakMap()
  try {
    pagina.on('request', (solicitud) => {
      const ruta = new URL(solicitud.url()).pathname
      if (ruta === '/api/v1/vision/cajones' && solicitud.method() === 'GET') {
        iniciosVision.set(solicitud, Date.now())
      }
    })
    pagina.on('response', (respuesta) => {
      if (new URL(respuesta.url()).pathname !== '/api/v1/vision/cajones') return
      const inicio = iniciosVision.get(respuesta.request())
      if (horaRevocacion && inicio && inicio >= horaRevocacion) solicitudesVisionPosteriores.push(respuesta.status())
    })
    await iniciarSesionWeb(pagina)
    console.log('LISTO_REVOCACION: actualice revision_acceso del unico DUENO sintetico activo y luego envie "revocar" por stdin.')
    await esperarSenal('revocar')
    horaRevocacion = Date.now()
    await pagina.waitForURL((url) => url.pathname === '/panel', { timeout: 50_000 })
    await pagina.getByLabel('Correo electrónico').waitFor({ state: 'visible' })
    const acceso = await pagina.evaluate(async () => {
      const respuesta = await fetch('/api/v1/vision/cajones', { credentials: 'same-origin' })
      return respuesta.status
    })
    assert.equal(acceso, 401, 'La revocación remota debe denegar Vision sin click')
    assert.ok(solicitudesVisionPosteriores.every((estado) => estado === 401 || estado === 403))
    assert.equal(await pagina.getByRole('region', { name: 'Ocupación física' }).count(), 0)
    console.log(
      `PASS revocacion_remota limpieza=si acceso=${acceso}`
      + ` get_posteriores=${solicitudesVisionPosteriores.length}`
      + ` estados=${solicitudesVisionPosteriores.join(',') || 'ninguna'}`,
    )
  } finally {
    await pagina.close()
    await navegador.close()
  }
}

async function probarReinicioJava() {
  const navegador = await chromium.launch({ headless: true })
  const pagina = await navegador.newPage()
  try {
    await iniciarSesionWeb(pagina)
    console.log('LISTO_REINICIO: reinicie solo la API aislada, espere su health y luego envie "reiniciar" por stdin.')
    await esperarSenal('reiniciar')
    await pagina.waitForURL((url) => url.pathname === '/panel', { timeout: 50_000 })
    const accesoViejo = await pagina.evaluate(async () => {
      const respuesta = await fetch('/api/v1/vision/cajones', { credentials: 'same-origin' })
      return respuesta.status
    })
    assert.equal(accesoViejo, 401, 'Java debe rechazar la sesión que existía antes del reinicio')
    await iniciarSesionWeb(pagina)
    const recuperada = await pagina.evaluate(async () => {
      const respuesta = await fetch('/api/v1/sesion', { credentials: 'same-origin' })
      return { estado: respuesta.status, cuerpo: await respuesta.json() }
    })
    assert.equal(recuperada.estado, 200)
    assert.equal(recuperada.cuerpo.autenticada, true)
    assert.equal(recuperada.cuerpo.rol, 'DUENO')
    console.log(`PASS reinicio_java sesion_anterior=${accesoViejo} recuperacion=200 rol=DUENO`)
  } finally {
    await pagina.close()
    await navegador.close()
  }
}

async function probarAutorizacionPorRol() {
  const anonimo = await request.newContext({ baseURL: apiBase, timeout: 15_000 })
  try {
    const sinSesion = await anonimo.get('/api/v1/vision/cajones')
    assert.equal(sinSesion.status(), 401, 'Anónimo debe recibir 401 desde Java')
    const bearer = await anonimo.get('/api/v1/vision/cajones', {
      headers: { Authorization: 'Bearer token-sintetico-invalido' },
    })
    assert.equal(bearer.status(), 401, 'Bearer de dispositivo no debe autenticar Vision')
    console.log(`PASS autorizacion anonimo=${sinSesion.status()} bearer_invalido=${bearer.status()}`)
  } finally {
    await anonimo.dispose()
  }
  const cliente = await crearClienteSintetico()
  await comprobarRolEnApiYBff('CLIENTE', cliente)
  const operador = await crearOperadorSintetico()
  await comprobarRolEnApiYBff('OPERADOR', operador)
}

exigirEntornoAislado()
const modo = process.argv[2]
try {
  if (modo === 'pasivo') await probarPasivoEInactivo()
  else if (modo === 'logout') await probarLogoutConRespuestasTardias()
  else if (modo === 'revocacion') await probarRevocacionRemota()
  else if (modo === 'reinicio') await probarReinicioJava()
  else if (modo === 'autorizacion') await probarAutorizacionPorRol()
  else throw new Error('Use el modo pasivo, logout, revocacion, reinicio o autorizacion.')
} catch (error) {
  const detalle = String(error?.message ?? '')
    .replaceAll(ownerEmail ?? '', '[REDACTADO]')
    .replaceAll(ownerPassword ?? '', '[REDACTADO]')
    .replace(/[A-Za-z0-9_-]{32,}/g, '[REDACTADO]')
    .split('\n')
    .slice(0, 3)
    .join(' ')
    .slice(0, 320)
  console.error(`FAIL ${modo ?? 'sin_modo'}: ${error?.name ?? 'Error'} ${detalle}`)
  process.exitCode = 1
}
