import { randomUUID } from 'node:crypto'
import { expect, test, type Page } from '@playwright/test'
import { baseURL, iniciarSesion } from './sesion'
import { comprobarRecuperacionLogin } from './recuperacion-login'

const ASUNTO_INVITACION = 'Activa tu cuenta de Smart Parking'
const MAILPIT = process.env.TEST_MAILPIT_BASE_URL ?? 'http://mailpit:8025'

test('registra desde ruta protegida y activa sin exponer el token', async ({ browser, page }) => {
  const sufijo = randomUUID()
  const correo = `operador.${sufijo}@example.test`
  const nombre = `Prueba ${sufijo.slice(0, 8)}`
  const contrasena = `Operador-${sufijo}-2026!`
  await page.setViewportSize({ width: 390, height: 844 })

  const loginBff = page.waitForResponse((respuesta) => {
    const url = new URL(respuesta.url())
    return url.pathname === '/api/v1/sesion' && respuesta.request().method() === 'POST'
  })
  await iniciarSesion(page)
  const respuestaLogin = await loginBff
  expect(respuestaLogin.status()).toBe(200)
  const cookies = await respuestaLogin.allHeaders()
  expect((cookies['set-cookie'] ?? '').includes('JSESSIONID=')).toBe(true)

  const respuestaDirecta = await page.goto(`${baseURL}/admin/operadores`)
  expect(respuestaDirecta?.status()).toBe(200)
  await page.waitForFunction(() => {
    const raiz = document.querySelector('#__nuxt') as (HTMLElement & { __vue_app__?: unknown }) | null
    return Boolean(raiz?.__vue_app__)
  })
  const cabecerasSsr = await respuestaDirecta!.allHeaders()
  expect(cabecerasSsr['cache-control'] ?? '').toContain('no-store')
  expect(cabecerasSsr['vary'] ?? '').toContain('Cookie')
  await expect(page.getByRole('region', { name: 'Lista de operadores' })).toBeVisible()

  const api = page.context().request
  const respuestaCsrf = await api.get(`${baseURL}/api/v1/csrf`)
  expect(respuestaCsrf.status()).toBe(200)
  const tokenCsrf = (await respuestaCsrf.json()).token as string
  expect(typeof tokenCsrf === 'string' && tokenCsrf.length > 0).toBe(true)

  const datos = {
    nombres: 'Intento sin CSRF',
    primerApellido: 'Sintético',
    segundoApellido: null,
    correo: `sin-csrf.${sufijo}@example.test`,
  }
  const sinCsrf = await api.post(`${baseURL}/api/v1/empleados`, {
    data: datos,
    headers: { 'idempotency-key': randomUUID() },
  })
  expect(sinCsrf.status()).toBe(403)

  const datosEmpleado = {
    nombres: nombre,
    primerApellido: 'Aceptación',
    segundoApellido: 'Web',
    correo,
  }
  const claveRegistroEmpleado = randomUUID()
  const respuestaEmpleado = await api.post(`${baseURL}/api/v1/empleados`, {
    data: datosEmpleado,
    headers: {
      'x-csrf-token': tokenCsrf,
      'idempotency-key': claveRegistroEmpleado,
    },
  })
  expect(respuestaEmpleado.status()).toBe(201)
  const reciboEmpleado = (await respuestaEmpleado.json()) as { id: number; codigo: string }
  expect(typeof reciboEmpleado.codigo).toBe('string')
  const idEmpleado = String(reciboEmpleado.id)

  const abrirRegistro = page.getByRole('button', { name: 'Añadir operador', exact: true }).first()
  await abrirRegistro.press('Enter')
  const dialogoRegistro = page.getByRole('dialog')
  await expect(dialogoRegistro).toBeVisible()
  await dialogoRegistro.getByLabel('Buscar empleado').fill(reciboEmpleado.codigo)
  const resultadoEmpleado = dialogoRegistro.getByRole('button', {
    name: new RegExp(reciboEmpleado.codigo),
  })
  await expect(resultadoEmpleado).toBeVisible()
  await resultadoEmpleado.click()
  const correoInvitacion = dialogoRegistro.getByLabel('Correo para la cuenta y la invitación')
  await expect(correoInvitacion).toHaveValue(correo)
  await correoInvitacion.fill(correo)

  const rutaPromocion = `/api/v1/empleados/${idEmpleado}/operador/promocion`
  const solicitudPromocion = page.waitForRequest((solicitud) => {
    const url = new URL(solicitud.url())
    return url.pathname === rutaPromocion && solicitud.method() === 'POST'
  })
  const respuestaPromocion = page.waitForResponse((respuesta) => {
    const url = new URL(respuesta.url())
    return url.pathname === rutaPromocion && respuesta.request().method() === 'POST'
  })
  await dialogoRegistro
    .getByRole('button', { name: 'Crear cuenta y enviar invitación', exact: true })
    .click()
  const [peticionPromocion, reciboPromocion] = await Promise.all([
    solicitudPromocion,
    respuestaPromocion,
  ])
  expect(reciboPromocion.status()).toBe(200)
  const encabezadosPromocion = peticionPromocion.headers()
  expect(typeof encabezadosPromocion['x-csrf-token'] === 'string'
    && encabezadosPromocion['x-csrf-token'].length > 0).toBe(true)
  expect(typeof encabezadosPromocion['idempotency-key'] === 'string'
    && encabezadosPromocion['idempotency-key'].length > 0).toBe(true)
  expect(encabezadosPromocion['if-match']).toMatch(/^"\d+"$/)
  expect(peticionPromocion.postDataJSON()).toEqual({ correo })
  const resultadoPromocion = (await reciboPromocion.json()) as {
    empleadoId: string
    operadorId: string | null
    estadoOperador: string | null
  }
  expect(resultadoPromocion.empleadoId).toBe(idEmpleado)
  expect(resultadoPromocion.estadoOperador).toBe('PENDIENTE')
  const idOperador = String(resultadoPromocion.operadorId)
  expect(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(idOperador)).toBe(true)
  const filaOperador = page.getByRole('row', { name: new RegExp(nombre) })
  try {
    await expect(filaOperador).toBeVisible({ timeout: 1_000 })
  } catch {
    await page.getByRole('button', { name: 'Actualizar lista', exact: true }).click()
    await expect(filaOperador).toBeVisible()
  }

  const estiloTabla = await page.locator('.tabla-operadores-contenedor').evaluate(
    (elemento) => getComputedStyle(elemento).overflowX,
  )
  expect(estiloTabla).toBe('auto')

  const textoCorreo = await leerCorreo(correo)
  const enlace = textoCorreo.match(/https?:\/\/[^\s#]+\/activar-operador#[A-Za-z0-9_-]{43}/)?.[0]
  expect(Boolean(enlace)).toBe(true)
  const token = enlace!.slice(enlace!.indexOf('#') + 1)
  const respuestaDocumento = await navegarSinExponerToken(page, enlace!)
  const htmlServidor = await respuestaDocumento.text()
  expect(htmlServidor.includes(token)).toBe(false)
  const cabecerasActivacion = await respuestaDocumento.allHeaders()
  expect(cabecerasActivacion['cache-control'] ?? '').toContain('no-store')
  expect(cabecerasActivacion['referrer-policy']).toBe('no-referrer')
  await expect(page.getByRole('heading', { name: 'Activar cuenta' })).toBeVisible()
  await expect(page.getByLabel('Contraseña', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => new URL(location.href).hash.length === 0)).toBe(true)
  expect((await page.content()).includes(token)).toBe(false)
  const hidratacion = await page.locator('#__NUXT_DATA__').textContent()
  expect(typeof hidratacion === 'string' && !hidratacion.includes(token)).toBe(true)

  await page.getByLabel('Contraseña', { exact: true }).fill(contrasena)
  await page.getByLabel('Confirmar contraseña').fill(contrasena)
  await page.getByRole('button', { name: 'Activar cuenta', exact: true }).click()
  await expect(page.getByRole('status').getByText('Tu cuenta está lista.')).toBeVisible()
  expect(new URL(page.url()).pathname).toBe('/activar-operador')
  expect(await page.evaluate(() => new URL(location.href).hash.length === 0)).toBe(true)

  const respuestaCsrfReemision = await api.get(`${baseURL}/api/v1/csrf`)
  expect(respuestaCsrfReemision.status()).toBe(200)
  const csrfReemision = (await respuestaCsrfReemision.json()).token as string
  const detalleOperador = await api.get(`${baseURL}/api/v1/operadores/${idOperador}`)
  expect(detalleOperador.status()).toBe(200)
  const revisionAcceso = detalleOperador.headers().etag
  expect(revisionAcceso).toMatch(/^"\d+"$/)
  const rutaUuid = `${baseURL}/api/v1/operadores/${idOperador}/invitacion/reemitir`
  const respuestaUuid = await api.post(rutaUuid, {
    headers: {
      'x-csrf-token': csrfReemision,
      'if-match': revisionAcceso,
      'idempotency-key': randomUUID(),
    },
  })
  expect(respuestaUuid.status()).toBe(409)
  const respuestaNumerica = await api.post(`${baseURL}/api/v1/operadores/42/invitacion/reemitir`, {
    headers: { 'x-csrf-token': csrfReemision, 'idempotency-key': randomUUID() },
  })
  expect(respuestaNumerica.status()).toBe(404)
  const respuestaMalformada = await api.post(`${baseURL}/api/v1/operadores/no-es-uuid/invitacion/reemitir`, {
    headers: { 'x-csrf-token': csrfReemision, 'idempotency-key': randomUUID() },
  })
  expect(respuestaMalformada.status()).toBe(404)

  const contextoOperador = await browser.newContext()
  try {
    const paginaOperador = await contextoOperador.newPage()
    await comprobarRecuperacionLogin(paginaOperador, correo, contrasena, '/operador')
    await expect(paginaOperador.getByRole('heading', { name: 'Bienvenido' })).toBeVisible()

    const apiOperador = paginaOperador.context().request
    const empleadosProtegidos = await apiOperador.get(`${baseURL}/api/v1/empleados`)
    expect(empleadosProtegidos.status()).toBe(403)
    const operadoresProtegidos = await apiOperador.get(`${baseURL}/api/v1/operadores`)
    expect(operadoresProtegidos.status()).toBe(403)

    const respuestaCierre = paginaOperador.waitForResponse((respuesta) => {
      const url = new URL(respuesta.url())
      return url.pathname === '/api/v1/sesion' && respuesta.request().method() === 'DELETE'
    })
    await paginaOperador.getByRole('button', { name: 'Cerrar sesión', exact: true }).click()
    expect((await respuestaCierre).status()).toBe(200)
    await expect.poll(() => new URL(paginaOperador.url()).pathname).toBe('/panel')
    const sesionCerrada = await apiOperador.get(`${baseURL}/api/v1/sesion`)
    expect(sesionCerrada.status()).toBe(200)
    expect((await sesionCerrada.json()).autenticada).toBe(false)
  } finally {
    await contextoOperador.close()
  }
})

async function leerCorreo(destinatario: string): Promise<string> {
  const listado = await fetch(`${MAILPIT}/api/v1/messages?limit=100`).then((respuesta) => respuesta.json())
  const coincidencias = (listado.messages ?? []).filter((mensaje: {
    Subject: string
    To?: Array<{ Address: string }>
  }) => mensaje.Subject === ASUNTO_INVITACION
    && mensaje.To?.some((direccion) => direccion.Address === destinatario))
  expect(coincidencias.length).toBe(1)
  const id = coincidencias[0].ID as string
  const detalle = await fetch(`${MAILPIT}/api/v1/message/${encodeURIComponent(id)}`).then((respuesta) => respuesta.json())
  return String(detalle.Text ?? '')
}

async function navegarSinExponerToken(page: Page, enlace: string) {
  try {
    const respuesta = await page.goto(enlace)
    if (!respuesta) throw new Error('missing response')
    return respuesta
  } catch {
    throw new Error('No se pudo abrir el enlace sintético de activación; valor omitido.')
  }
}
