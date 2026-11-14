import { randomUUID } from 'node:crypto'
import { expect, test, type Page } from '@playwright/test'
import { baseURL, iniciarSesion } from './sesion'

const MAILPIT = process.env.TEST_MAILPIT_BASE_URL ?? 'http://mailpit:8025'
const DEBOUNCE_BUSQUEDA_MS = 300
const TOKEN_ACTIVACION = /https?:\/\/[^\s#]+\/activar-operador#([A-Za-z0-9_-]{43})/
const TOKEN_RECUPERACION = /https?:\/\/[^\s#]+\/restablecer-contrasena#([A-Za-z0-9_-]{43})/

test('administra operadores y recibe el cambio por SSE en otra sesión', async ({ browser, page }) => {
  const sufijo = randomUUID()
  const nombre = `Aceptación ${sufijo.slice(0, 8)}`
  const correo = `administracion.${sufijo}@example.test`
  await iniciarSesion(page)
  const id = await registrarOperador(page, nombre, correo)
  const contextoSecundario = await browser.newContext()
  try {
    const paginaSecundaria = await contextoSecundario.newPage()
    await iniciarSesion(paginaSecundaria)
    await paginaSecundaria.goto(`${baseURL}/admin/operadores`)
    await esperarHidratacionNuxt(paginaSecundaria)
    const filaSecundaria = paginaSecundaria.getByRole('row', { name: new RegExp(correo) })
    await expect(filaSecundaria).toContainText('Pendiente')

    await page.goto(`${baseURL}/admin/operadores`)
    await esperarHidratacionNuxt(page)
    await expect(page.getByRole('region', { name: 'Lista de operadores' })).toBeVisible()
    await expect(page.getByLabel('Buscar por nombre, apellido o correo')).toBeVisible()
    const respuestaBusqueda = esperarRespuestaDirectorio(page, correo, 'TODOS')
    await page.getByLabel('Buscar por nombre, apellido o correo').fill(correo)
    await page.waitForTimeout(DEBOUNCE_BUSQUEDA_MS + 50)
    await verificarRespuestaDirectorio(await respuestaBusqueda)
    const respuestaPendiente = esperarRespuestaDirectorio(page, correo, 'PENDIENTE')
    await seleccionarEstadoPendiente(page)
    await verificarRespuestaDirectorio(await respuestaPendiente)
    await verificarResultadoUnico(page, correo)
    const fila = page.getByRole('row', { name: new RegExp(correo) })
    await expect(fila).toContainText(nombre)

    const detalleRespuesta = page.waitForResponse((respuesta) => {
      const url = new URL(respuesta.url())
      return url.pathname === `/api/v1/operadores/${id}` && respuesta.request().method() === 'GET'
    })
    await abrirAdministracion(page, nombre)
    const reciboDetalle = await detalleRespuesta
    expect(reciboDetalle.status()).toBe(200)
    expect(reciboDetalle.headers().etag).toMatch(/^"[0-9]+"$/)
    const cuerpoDetalle = await reciboDetalle.text()
    expect(cuerpoDetalle).not.toMatch(/tokenHash|hashContrasena|recuperacion.*token/i)
    const dialogo = page.getByRole('dialog')
    await expect(dialogo.getByRole('heading', { name: 'Administrar operador' })).toBeVisible()
    await expect(dialogo).toContainText('Estado de invitación')
    await expect(dialogo).toContainText('Invitación vence')

    await dialogo.getByRole('button', { name: 'Desactivar cuenta' }).click()
    await expect(dialogo.getByRole('heading', { name: 'Desactivar operador' })).toBeVisible()
    const respuestaBaja = page.waitForResponse((respuesta) => {
      const url = new URL(respuesta.url())
      return url.pathname === `/api/v1/operadores/${id}/estado` && respuesta.request().method() === 'PATCH'
    })
    await dialogo.getByRole('button', { name: 'Confirmar', exact: true }).click()
    expect((await respuestaBaja).status()).toBe(200)
    await expect(dialogo).toContainText('Inactiva')
    await expect(filaSecundaria).toContainText('Inactiva', { timeout: 20_000 })
  } finally {
    await contextoSecundario.close()
  }
})

test('restablece contraseña desde el fragmento sin exponer ni consumir el token al validar', async ({ page }) => {
  const sufijo = randomUUID()
  const correo = `recuperacion.${sufijo}@example.test`
  const nombre = `Recuperación ${sufijo.slice(0, 8)}`
  await iniciarSesion(page)
  const tokenCsrf = await obtenerCsrf(page)
  const id = await registrarOperador(page, nombre, correo, tokenCsrf)
  const tokenActivacion = await esperarTokenCorreo(correo, TOKEN_ACTIVACION)
  const validarActivacion = await page.context().request.post(`${baseURL}/api/v1/operadores/activacion/validar`, {
    data: { token: tokenActivacion },
    headers: { 'X-CSRF-TOKEN': tokenCsrf },
  })
  expect(validarActivacion.status()).toBe(200)
  const completarActivacion = await page.context().request.post(`${baseURL}/api/v1/operadores/activacion/completar`, {
    data: {
      token: tokenActivacion,
      contrasena: `Operador-${sufijo}-2026!`,
      confirmarContrasena: `Operador-${sufijo}-2026!`,
    },
    headers: { 'X-CSRF-TOKEN': tokenCsrf },
  })
  expect(completarActivacion.status()).toBe(204)

  await page.goto(`${baseURL}/admin/operadores`)
  await esperarHidratacionNuxt(page)
  const respuestaBusqueda = esperarRespuestaDirectorio(page, correo, 'TODOS')
  await page.getByLabel('Buscar por nombre, apellido o correo').fill(correo)
  await page.waitForTimeout(DEBOUNCE_BUSQUEDA_MS + 50)
  await verificarRespuestaDirectorio(await respuestaBusqueda)
  await verificarResultadoUnico(page, correo)
  const fila = page.getByRole('row', { name: new RegExp(correo) })
  await expect(fila).toContainText('Activa')
  await abrirAdministracion(page, nombre)
  const dialogo = page.getByRole('dialog')
  await expect(dialogo.getByRole('heading', { name: 'Administrar operador' })).toBeVisible()
  await dialogo.getByRole('button', { name: 'Recuperar contraseña', exact: true }).click()
  await expect(dialogo.getByRole('heading', { name: 'Iniciar recuperación de contraseña' })).toBeVisible()
  const esSolicitudRecuperacion = (urlTexto: string, metodo: string) => {
    const url = new URL(urlTexto)
    return url.pathname === `/api/v1/operadores/${id}/recuperacion` && metodo === 'POST'
  }
  const solicitudRecuperacion = page.waitForRequest((solicitud) =>
    esSolicitudRecuperacion(solicitud.url(), solicitud.method()),
  )
  const respuestaSolicitud = page.waitForResponse((respuesta) =>
    esSolicitudRecuperacion(respuesta.url(), respuesta.request().method()),
  )
  await dialogo.getByRole('button', { name: 'Confirmar', exact: true }).click()
  await solicitudRecuperacion
  const reciboSolicitud = await respuestaSolicitud
  expect(reciboSolicitud.status()).toBe(200)
  const cuerpoTexto = await reciboSolicitud.text()
  const cuerpoSolicitud = JSON.parse(cuerpoTexto) as { estadoEnvio: string; venceEn: string }
  expect(['ENVIADO', 'FALLIDO', 'DESCONOCIDO', 'DESHABILITADO']).toContain(cuerpoSolicitud.estadoEnvio)
  expect(Date.parse(cuerpoSolicitud.venceEn)).toBeGreaterThan(Date.now() + 29 * 60_000)
  expect(Date.parse(cuerpoSolicitud.venceEn)).toBeLessThan(Date.now() + 31 * 60_000)
  expect(cuerpoTexto).not.toMatch(/token/i)

  const token = await esperarTokenCorreo(correo, TOKEN_RECUPERACION)
  const respuestaDocumento = await page.goto(`${baseURL}/restablecer-contrasena#${token}`)
  expect(respuestaDocumento?.status()).toBe(200)
  expect(await respuestaDocumento!.text()).not.toContain(token)
  expect(respuestaDocumento!.headers()['cache-control']).toContain('no-store')
  expect(respuestaDocumento!.headers()['referrer-policy']).toBe('no-referrer')
  await expect(page.getByRole('heading', { name: 'Restablecer contraseña' })).toBeVisible()
  await expect(page.getByLabel('Contraseña nueva', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Confirmar contraseña nueva', { exact: true })).toBeVisible()
  await expect.poll(() => new URL(page.url()).hash).toBe('')
  const validarSinConsumo = await page.context().request.post(
    `${baseURL}/api/v1/operadores/recuperacion/validar`,
    { data: { token }, headers: { 'X-CSRF-TOKEN': tokenCsrf } },
  )
  expect(validarSinConsumo.status()).toBe(200)
  expect((await page.content()).includes(token)).toBe(false)
  const hidratacion = await page.locator('#__NUXT_DATA__').textContent()
  expect(hidratacion?.includes(token)).toBe(false)

  const contrasenaNueva = `Renovada-${sufijo}-2026!`
  await page.getByLabel('Contraseña nueva', { exact: true }).fill(contrasenaNueva)
  await page.getByLabel('Confirmar contraseña nueva', { exact: true }).fill(contrasenaNueva)
  await page.getByRole('button', { name: 'Actualizar contraseña', exact: true }).click()
  await expect(page.getByRole('status').getByText('La contraseña se actualizó correctamente.')).toBeVisible()
  expect(new URL(page.url()).pathname).toBe('/restablecer-contrasena')
})

async function registrarOperador(page: Page, nombres: string, correo: string,
  csrf?: string): Promise<string> {
  const token = csrf ?? await obtenerCsrf(page)
  const respuesta = await page.context().request.post(`${baseURL}/api/v1/operadores`, {
    data: { nombres, primerApellido: 'Aceptación', segundoApellido: 'FaseDos', correo },
    headers: { 'X-CSRF-TOKEN': token, 'Idempotency-Key': randomUUID() },
  })
  expect(respuesta.status()).toBe(201)
  return String((await respuesta.json()).id)
}

async function seleccionarEstadoPendiente(page: Page) {
  const selector = page.getByLabel('Estado de cuenta')
  await selector.selectOption('PENDIENTE')
  await expect(selector).toHaveValue('PENDIENTE')
}

async function esperarHidratacionNuxt(page: Page) {
  await page.waitForFunction(() => {
    const raiz = document.querySelector('#__nuxt') as (HTMLElement & { __vue_app__?: unknown }) | null
    return Boolean(raiz?.__vue_app__)
  })
}

function esperarRespuestaDirectorio(page: Page, busqueda: string, estado: string) {
  return page.waitForResponse((respuesta) => {
    const url = new URL(respuesta.url())
    return url.pathname === '/api/v1/operadores'
      && respuesta.request().method() === 'GET'
      && url.searchParams.get('busqueda') === busqueda
      && url.searchParams.get('estado') === estado
  })
}

async function verificarRespuestaDirectorio(respuesta: Awaited<ReturnType<typeof esperarRespuestaDirectorio>>) {
  expect(respuesta.status()).toBe(200)
  const pagina = await respuesta.json() as { totalRegistros?: number; items?: unknown[] }
  expect(pagina.totalRegistros).toBe(1)
  expect(pagina.items).toHaveLength(1)
}

async function verificarResultadoUnico(page: Page, correo: string) {
  const region = page.getByRole('region', { name: 'Lista de operadores' })
  await expect(region.locator('.resumen-operadores span')).toHaveText('1 registro')
  await expect(region.getByText('Mostrando 1 de 1', { exact: true })).toBeVisible()
  const filas = region.locator('.tabla-operadores tbody tr')
  await expect(filas).toHaveCount(1)
  await expect(filas.filter({ hasText: correo })).toHaveCount(1)
}

async function abrirAdministracion(page: Page, nombre: string) {
  await page.getByRole('button', {
    name: `Administrar ${nombre} Aceptación FaseDos`,
    exact: true,
  }).click()
}

async function obtenerCsrf(page: Page): Promise<string> {
  const respuesta = await page.context().request.get(`${baseURL}/api/v1/csrf`)
  expect(respuesta.status()).toBe(200)
  return String((await respuesta.json()).token)
}

async function esperarTokenCorreo(destinatario: string, formato: RegExp): Promise<string> {
  let token = ''
  await expect.poll(async () => {
    token = await leerTokenCorreo(destinatario, formato)
    return token
  }, { timeout: 15_000 }).not.toBe('')
  return token
}

async function leerTokenCorreo(destinatario: string, formato: RegExp): Promise<string> {
  const listado = await fetch(`${MAILPIT}/api/v1/messages?limit=100`).then((respuesta) => respuesta.json())
  for (const mensaje of listado.messages ?? []) {
    if (!mensaje.To?.some((direccion: { Address: string }) => direccion.Address === destinatario)) continue
    const detalle = await fetch(`${MAILPIT}/api/v1/message/${encodeURIComponent(mensaje.ID)}`)
      .then((respuesta) => respuesta.json())
    const coincidencia = String(detalle.Text ?? '').match(formato)
    if (coincidencia) return coincidencia[1]
  }
  return ''
}
