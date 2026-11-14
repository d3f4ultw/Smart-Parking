import { randomUUID } from 'node:crypto'
import { expect, test, type Browser, type Page } from '@playwright/test'
import { baseURL, iniciarSesion } from './sesion'

const mailpit = process.env.TEST_MAILPIT_BASE_URL ?? 'http://mailpit:8025'
const apiInterna = process.env.TEST_API_INTERNAL_BASE ?? 'http://api:8080'
const correoDueno = process.env.TEST_OWNER_EMAIL
const contrasenaDueno = process.env.TEST_OWNER_PASSWORD
const contrasenaAdminDueno = process.env.TEST_OWNER_PASSWORD_ADMIN
const correoOperador = process.env.TEST_OPERATOR_EMAIL
const contrasenaInicial = process.env.TEST_OPERATOR_PASSWORD_INITIAL
const contrasenaFinal = process.env.TEST_OPERATOR_PASSWORD_FINAL
const tokenActivacion = /http:\/\/localhost:3000\/activar-operador#([A-Za-z0-9_-]{43})/
const tokenRecuperacion = /http:\/\/localhost:3000\/restablecer-contrasena#([A-Za-z0-9_-]{43})/

test('entrega enlaces HTTP locales por Mailpit, activa y recupera una cuenta', async ({ browser, page }) => {
  if (!correoDueno || !contrasenaDueno || !contrasenaAdminDueno
      || !correoOperador || !contrasenaInicial || !contrasenaFinal) {
    throw new Error('Faltan credenciales sintéticas en el runner.')
  }

  let tokenInvitacion = ''
  let tokenRecuperacionActual = ''
  const erroresCliente: string[] = []
  page.on('pageerror', (error) => erroresCliente.push(error.message))
  try {
    await prepararDueno(page, correoDueno, contrasenaDueno, contrasenaAdminDueno)
    await iniciarSesion(page)
    await page.goto(`${baseURL}/admin/operadores`)
    await expect(page.getByRole('region', { name: 'Lista de operadores' })).toBeVisible()
    await page.waitForFunction(() => {
      const raiz = document.querySelector('#__nuxt') as (HTMLElement & { __vue_app__?: unknown }) | null
      return Boolean(raiz?.__vue_app__)
    })

    const tokenCsrfInicial = await obtenerCsrf(page)
    const rechazoSinCsrf = await page.context().request.post(`${baseURL}/api/v1/operadores`, {
      data: {
        nombres: 'Debe rechazarse',
        primerApellido: 'Sin CSRF',
        segundoApellido: null,
        correo: 'rechazo-csrf@example.test',
      },
      headers: { 'Idempotency-Key': randomUUID() },
    })
    expect(rechazoSinCsrf.status()).toBe(403)

    const datosRegistro = {
      nombres: 'Operador HTTP Local',
      primerApellido: 'Prueba',
      segundoApellido: null,
      correo: correoOperador,
    }
    const claveRegistro = randomUUID()
    const reciboRegistro = await page.context().request.post(`${baseURL}/api/v1/operadores`, {
      data: datosRegistro,
      headers: { 'X-CSRF-TOKEN': tokenCsrfInicial, 'Idempotency-Key': claveRegistro },
    })
    expect(reciboRegistro.status()).toBe(201)
    const respuestaRegistro = (await reciboRegistro.json()) as { id: string; estado: string }
    const operadorId = respuestaRegistro.id
    expect(Boolean(operadorId)).toBe(true)
    expect(respuestaRegistro.estado).toBe('PENDIENTE')

    const repeticionRegistro = await page.context().request.post(`${baseURL}/api/v1/operadores`, {
      data: datosRegistro,
      headers: { 'X-CSRF-TOKEN': tokenCsrfInicial, 'Idempotency-Key': claveRegistro },
    })
    expect(repeticionRegistro.status()).toBe(201)
    expect((await repeticionRegistro.json()).id).toBe(operadorId)

    const detallePendiente = await page.context().request.get(`${baseURL}/api/v1/operadores/${operadorId}`)
    expect(detallePendiente.status()).toBe(200)
    const datosPendiente = (await detallePendiente.json()) as { invitacionVenceEn: string }
    const venceInvitacion = Date.parse(datosPendiente.invitacionVenceEn)
    expect(venceInvitacion > Date.now() + 115 * 60_000 && venceInvitacion < Date.now() + 125 * 60_000).toBe(true)

    const mensajeInvitacion = await esperarCorreo(correoOperador, tokenActivacion)
    expect(mensajeInvitacion.coincidencias).toBe(1)
    expect(mensajeInvitacion.enlace.startsWith('http://localhost:3000/activar-operador#')).toBe(true)
    tokenInvitacion = mensajeInvitacion.token

    const respuestaActivacion = await page.goto(mensajeInvitacion.enlace)
    expect(respuestaActivacion?.status()).toBe(200)
    const htmlActivacion = await respuestaActivacion!.text()
    expect(htmlActivacion.includes(tokenInvitacion)).toBe(false)
    await esperarHidratacionNuxt(page)
    await expect(page.getByRole('heading', { name: 'Activar cuenta' })).toBeVisible()
    await expect(page.locator('#activacion-contrasena')).toBeVisible()
    await expect(page.locator('#activacion-confirmar-contrasena')).toBeVisible()
    await expect.poll(() => new URL(page.url()).hash).toBe('')
    expect((await page.content()).includes(tokenInvitacion)).toBe(false)
    const datosHidratados = await page.locator('#__NUXT_DATA__').textContent()
    expect(datosHidratados?.includes(tokenInvitacion)).toBe(false)

    await page.locator('#activacion-contrasena').fill(contrasenaInicial)
    await page.locator('#activacion-confirmar-contrasena').fill(contrasenaInicial)
    await page.getByRole('button', { name: 'Activar cuenta', exact: true }).click()
    await expect(page.getByRole('status').getByText('Tu cuenta está lista.')).toBeVisible()

    const validarTokenActivacion = await page.context().request.post(
      `${baseURL}/api/v1/operadores/activacion/validar`,
      { data: { token: tokenInvitacion }, headers: { 'X-CSRF-TOKEN': tokenCsrfInicial } },
    )
    expect(validarTokenActivacion.status()).toBe(410)
    const detalleActivo = await page.context().request.get(`${baseURL}/api/v1/operadores/${operadorId}`)
    expect(detalleActivo.status()).toBe(200)
    expect((await detalleActivo.json()).estado).toBe('ACTIVA')

    await verificarLoginOperadorRechazado(browser, correoOperador, contrasenaInicial)

    const detalleRecuperacion = await page.context().request.get(`${baseURL}/api/v1/operadores/${operadorId}`)
    expect(detalleRecuperacion.status()).toBe(200)
    const etagRecuperacion = detalleRecuperacion.headers().etag
    expect(Boolean(etagRecuperacion)).toBe(true)
    const reciboRecuperacion = await page.context().request.post(
      `${baseURL}/api/v1/operadores/${operadorId}/recuperacion`,
      {
        headers: {
          'X-CSRF-TOKEN': tokenCsrfInicial,
          'If-Match': etagRecuperacion!,
          'Idempotency-Key': randomUUID(),
        },
      },
    )
    expect(reciboRecuperacion.status()).toBe(200)
    const datosRecuperacion = (await reciboRecuperacion.json()) as { estadoEnvio: string; venceEn: string }
    expect(datosRecuperacion.estadoEnvio).toBe('ENVIADO')
    const venceRecuperacion = Date.parse(datosRecuperacion.venceEn)
    expect(venceRecuperacion > Date.now() + 29 * 60_000 && venceRecuperacion < Date.now() + 31 * 60_000).toBe(true)

    const mensajeRecuperacion = await esperarCorreo(correoOperador, tokenRecuperacion)
    expect(mensajeRecuperacion.coincidencias).toBe(1)
    expect(mensajeRecuperacion.enlace.startsWith('http://localhost:3000/restablecer-contrasena#')).toBe(true)
    tokenRecuperacionActual = mensajeRecuperacion.token

    const respuestaValidarRecuperacionPromise = page.waitForResponse((respuesta) => {
      const url = new URL(respuesta.url())
      return url.pathname === '/api/v1/operadores/recuperacion/validar'
        && respuesta.request().method() === 'POST'
    })
    const respuestaRecuperacionDocumento = await page.goto(mensajeRecuperacion.enlace)
    expect(respuestaRecuperacionDocumento?.status()).toBe(200)
    const htmlRecuperacion = await respuestaRecuperacionDocumento!.text()
    expect(htmlRecuperacion.includes(tokenRecuperacionActual)).toBe(false)
    await esperarHidratacionNuxt(page)
    const respuestaValidarRecuperacion = await respuestaValidarRecuperacionPromise
    expect(respuestaValidarRecuperacion.status()).toBe(200)
    expect(respuestaRecuperacionDocumento!.headers()['cache-control']).toContain('no-store')
    expect(respuestaRecuperacionDocumento!.headers()['referrer-policy']).toBe('no-referrer')
    const paginaRecuperacion = await page.evaluate(() => ({
      titulo: document.title,
      ruta: `${location.origin}${location.pathname}`,
      encabezados: Array.from(document.querySelectorAll('h1, h2'))
        .map((elemento) => elemento.textContent?.trim() ?? '')
        .filter(Boolean),
      alertas: Array.from(document.querySelectorAll('[role="alert"]'))
        .map((elemento) => elemento.textContent?.trim() ?? '')
        .filter(Boolean),
      etiquetas: Array.from(document.querySelectorAll('label'))
        .map((elemento) => elemento.textContent?.trim() ?? '')
        .filter(Boolean),
      formularioVisible: Boolean(document.querySelector('#recuperacion-contrasena')),
    }))
    expect(
      paginaRecuperacion.encabezados,
      `Página de recuperación inesperada: ${JSON.stringify({ ...paginaRecuperacion, erroresCliente })}`,
    ).toContain('Cambiar contraseña')
    await expect.poll(() => new URL(page.url()).hash).toBe('')
    expect((await page.content()).includes(tokenRecuperacionActual)).toBe(false)
    const hidratacionRecuperacion = await page.locator('#__NUXT_DATA__').textContent()
    expect(hidratacionRecuperacion?.includes(tokenRecuperacionActual)).toBe(false)

    await page.locator('#recuperacion-contrasena').fill(contrasenaFinal)
    await page.locator('#recuperacion-confirmar-contrasena').fill(contrasenaFinal)
    const respuestaCompletarRecuperacion = page.waitForResponse((respuesta) => {
      const url = new URL(respuesta.url())
      return url.pathname === '/api/v1/operadores/recuperacion/completar'
        && respuesta.request().method() === 'POST'
    })
    await page.getByRole('button', { name: 'Cambiar contraseña', exact: true }).click()
    expect((await respuestaCompletarRecuperacion).status()).toBe(204)
    await expect(page.getByRole('status').getByText('Tu contraseña cambió.')).toBeVisible()

    const validarTokenRecuperacion = await page.context().request.post(
      `${baseURL}/api/v1/operadores/recuperacion/validar`,
      { data: { token: tokenRecuperacionActual }, headers: { 'X-CSRF-TOKEN': tokenCsrfInicial } },
    )
    expect(validarTokenRecuperacion.status()).toBe(410)
    await verificarLoginOperadorRechazado(browser, correoOperador, contrasenaFinal)
  } catch (fallo) {
    let mensaje = fallo instanceof Error ? fallo.message : String(fallo)
    for (const token of [tokenInvitacion, tokenRecuperacionActual]) {
      if (token) mensaje = mensaje.replaceAll(token, '[token redactado]')
    }
    throw new Error(mensaje)
  }
})

async function verificarLoginOperadorRechazado(
  browser: Browser,
  correo: string,
  contrasena: string,
) {
  const contexto = await browser.newContext()
  try {
    const pagina = await contexto.newPage()
    await pagina.goto(`${baseURL}/panel`)
    const respuestaCsrf = await contexto.request.get(`${baseURL}/api/v1/csrf`)
    const csrf = String((await respuestaCsrf.json()).token)
    const acceso = await contexto.request.post(`${baseURL}/api/v1/sesion`, {
      data: { correo, contrasena },
      headers: { 'X-CSRF-TOKEN': csrf },
    })
    expect(acceso.status()).toBe(401)
  } finally {
    await contexto.close()
  }
}

async function prepararDueno(page: Page, correo: string, contrasena: string, contrasenaAdministrativa: string) {
  const estado = await page.context().request.get(`${apiInterna}/api/v1/configuracion/estado`)
  expect(estado.status()).toBe(200)
  expect((await estado.json()).estado).toBe('SIN_CONFIGURAR')

  const respuestaCsrf = await page.context().request.get(`${apiInterna}/api/v1/csrf`)
  expect(respuestaCsrf.status()).toBe(200)
  const csrf = String((await respuestaCsrf.json()).token)
  const configuracion = await page.context().request.post(`${apiInterna}/api/v1/configuracion/inicial`, {
    data: {
      propietario: {
        nombres: 'Dueño sintético',
        primerApellido: 'HTTP Local',
        segundoApellido: 'Prueba',
        correo,
        contrasenaAcceso: contrasena,
        contrasenaAdministrativa,
      },
      estacionamiento: {
        nombre: 'Estacionamiento HTTP Local',
        tipo: 'PUBLICO',
        horario: {
          modo: 'INTERVALO_DIARIO',
          zonaHoraria: 'America/Mexico_City',
          horaApertura: '22:00',
          horaCierre: '06:00',
        },
      },
    },
    headers: { 'X-CSRF-TOKEN': csrf, 'Idempotency-Key': randomUUID() },
  })
  expect(configuracion.status()).toBe(201)
}

async function obtenerCsrf(page: Page) {
  const respuesta = await page.context().request.get(`${baseURL}/api/v1/csrf`)
  expect(respuesta.status()).toBe(200)
  return String((await respuesta.json()).token)
}

async function esperarHidratacionNuxt(page: Page) {
  await page.waitForFunction(() => {
    const raiz = document.querySelector('#__nuxt') as (HTMLElement & { __vue_app__?: unknown }) | null
    return Boolean(raiz?.__vue_app__)
  })
}

async function esperarCorreo(destinatario: string, formato: RegExp) {
  let resultado = { enlace: '', token: '', coincidencias: 0 }
  await expect.poll(async () => {
    const respuesta = await fetch(`${mailpit}/api/v1/messages?limit=100`)
    if (!respuesta.ok) return false
    const lista = (await respuesta.json()) as {
      messages?: Array<{ ID: string; To?: Array<{ Address: string }> }>
    }
    const recibidos = lista.messages ?? []
    const coincidencias = recibidos.filter((mensaje) =>
      mensaje.To?.some((direccion) => direccion.Address === destinatario),
    )
    let enlacesCoincidentes = 0
    let enlaceEncontrado = ''
    for (const mensaje of coincidencias) {
      const detalle = await fetch(`${mailpit}/api/v1/message/${encodeURIComponent(mensaje.ID)}`)
      if (!detalle.ok) continue
      const cuerpo = (await detalle.json()) as { Text?: string }
      const enlace = String(cuerpo.Text ?? '').match(formato)?.[0] ?? ''
      if (enlace) {
        enlacesCoincidentes += 1
        if (!enlaceEncontrado) enlaceEncontrado = enlace
      }
    }
    if (enlaceEncontrado) {
      resultado = {
        enlace: enlaceEncontrado,
        token: new URL(enlaceEncontrado).hash.slice(1),
        coincidencias: enlacesCoincidentes,
      }
      return true
    }
    return false
  }, { timeout: 15_000 }).toBe(true)
  return resultado
}
