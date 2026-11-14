import { expect, test, type Page } from '@playwright/test'
import { cancelarCapturaActiva, iniciarSesion, webUrl } from './soporte'

async function iniciarSesionCliente(page: Page): Promise<void> {
  const correo = process.env.TEST_CLIENT_EMAIL
  const contrasena = process.env.TEST_CLIENT_PASSWORD
  if (!correo || !contrasena)
    throw new Error('Faltan credenciales sintéticas de CLIENTE en el runner.')

  let intentoGetConCredenciales = false
  await page.route('**/*', async (ruta) => {
    const destino = new URL(ruta.request().url())
    if (destino.searchParams.has('correo') || destino.searchParams.has('contrasena')) {
      intentoGetConCredenciales = true
      await ruta.abort('aborted')
      return
    }
    await ruta.continue()
  })
  await page.goto(webUrl('/clientes/acceso'))
  await page.getByLabel('Correo electrónico').fill(correo)
  await page.getByRole('textbox', { name: 'Contraseña' }).fill(contrasena)
  await page.getByRole('button', { name: 'Iniciar sesión', exact: true }).click()
  await expect.poll(() => new URL(page.url()).pathname).toBe('/clientes/portal')
  expect(
    intentoGetConCredenciales,
    'el formulario de CLIENTE nunca envía credenciales en GET',
  ).toBe(false)
}

function verificarHtmlSinModuloRfid(html: string, contexto: string): void {
  const contenido = html.toLocaleLowerCase()
  expect(
    contenido.includes('directorio e historial'),
    `${contexto}: SSR no incluye el directorio`,
  ).toBe(false)
  expect(
    contenido.includes('asociar tarjeta'),
    `${contexto}: SSR no incluye la acción de asociación`,
  ).toBe(false)
  expect(
    contenido.includes('filtra por persona y estado'),
    `${contexto}: SSR no incluye controles RFID`,
  ).toBe(false)
}

test.afterEach(async ({ page }) => {
  await cancelarCapturaActiva(page.context().request)
})

test('la ruta de administración rechaza sesiones anónimas y CLIENTE', async ({ browser, page }) => {
  const respuestaAnonima = await page.goto(webUrl('/admin/tarjetas-rfid'))
  expect(Boolean(respuestaAnonima)).toBe(true)
  if (!respuestaAnonima) throw new Error('No se recibió la respuesta SSR para la entrada anónima.')
  verificarHtmlSinModuloRfid(await respuestaAnonima.text(), 'sesión anónima')
  await expect.poll(() => new URL(page.url()).pathname).not.toBe('/admin/tarjetas-rfid')
  await expect(page.getByRole('heading', { name: 'Tarjetas RFID', exact: true })).toHaveCount(0)

  const contextoCliente = await browser.newContext()
  const paginaCliente = await contextoCliente.newPage()
  try {
    await iniciarSesionCliente(paginaCliente)
    const respuestaCliente = await paginaCliente.goto(webUrl('/admin/tarjetas-rfid'))
    expect(Boolean(respuestaCliente)).toBe(true)
    if (!respuestaCliente) throw new Error('No se recibió la respuesta SSR para la sesión CLIENTE.')
    verificarHtmlSinModuloRfid(await respuestaCliente.text(), 'sesión CLIENTE')
    await expect.poll(() => new URL(paginaCliente.url()).pathname).not.toBe('/admin/tarjetas-rfid')
    await expect(
      paginaCliente.getByRole('heading', { name: 'Tarjetas RFID', exact: true }),
    ).toHaveCount(0)
  } finally {
    await contextoCliente.close()
  }
})

test('una cancelación de captura sin token CSRF se rechaza y no altera la captura', async ({
  page,
}) => {
  await iniciarSesion(page)
  await page.goto(webUrl('/admin/tarjetas-rfid'))
  await page.getByRole('button', { name: 'Asociar tarjeta', exact: true }).click()
  const dialogo = page.getByRole('dialog', { name: 'Asociar tarjeta' })
  await dialogo.getByRole('button', { name: 'CLIENTE', exact: true }).click()
  await dialogo.getByRole('combobox', { name: 'Buscar' }).fill('Stage 2')
  const candidato = dialogo.getByRole('option', { name: /^CLI-\d{4,} · / }).first()
  await expect(candidato).toBeEnabled()
  await candidato.click()
  await dialogo.getByRole('button', { name: 'Siguiente', exact: true }).click()
  await expect(dialogo.getByText('2. Leer tarjeta', { exact: true })).toBeVisible()

  const respuestaInicio = page.waitForResponse(
    (respuesta) =>
      new URL(respuesta.url()).pathname === '/api/v1/rfid-1/capturas' &&
      respuesta.request().method() === 'POST',
  )
  await dialogo.getByRole('button', { name: 'Iniciar lectura', exact: true }).click()
  const inicio = await respuestaInicio
  expect(inicio.status()).toBe(201)
  const { capturaId } = (await inicio.json()) as { capturaId: string }

  const rechazo = await page
    .context()
    .request.delete(webUrl(`/api/v1/rfid-1/capturas/${capturaId}`))
  expect(rechazo.status()).toBe(403)
  const estado = await page.context().request.get(webUrl(`/api/v1/rfid-1/capturas/${capturaId}`))
  expect(estado.status()).toBe(200)
  const actual = (await estado.json()) as { estado: string }
  expect(actual.estado).not.toBe('CANCELADA')
  await expect(dialogo.getByText('2. Leer tarjeta', { exact: true })).toBeVisible()
})

test('la expiración autoritativa permite reintentar y cancelar la captura', async ({ page }) => {
  await iniciarSesion(page)
  await page.goto(webUrl('/admin/tarjetas-rfid'))
  await page.getByRole('button', { name: 'Asociar tarjeta', exact: true }).click()
  const dialogo = page.getByRole('dialog', { name: 'Asociar tarjeta' })
  await dialogo.getByRole('button', { name: 'CLIENTE', exact: true }).click()
  await dialogo.getByRole('combobox', { name: 'Buscar' }).fill('Stage 2')
  const candidato = dialogo.getByRole('option', { name: /^CLI-\d{4,} · / }).first()
  await expect(candidato).toBeEnabled()
  await candidato.click()
  await dialogo.getByRole('button', { name: 'Siguiente', exact: true }).click()
  await expect(dialogo.getByText('2. Leer tarjeta', { exact: true })).toBeVisible()

  const inicioRespuesta = page.waitForResponse(
    (respuesta) =>
      new URL(respuesta.url()).pathname === '/api/v1/rfid-1/capturas' &&
      respuesta.request().method() === 'POST',
  )
  await dialogo.getByRole('button', { name: 'Iniciar lectura', exact: true }).click()
  const inicio = await inicioRespuesta
  expect(inicio.status()).toBe(201)
  const { capturaId: capturaExpirada } = (await inicio.json()) as { capturaId: string }
  const rutaExpirada = `**/api/v1/rfid-1/capturas/${capturaExpirada}`
  await page.route(rutaExpirada, async (ruta) => {
    if (ruta.request().method() === 'DELETE') {
      await ruta.fulfill({ status: 410, contentType: 'application/json', body: '{}' })
      return
    }
    if (ruta.request().method() === 'GET') {
      const respuesta = await ruta.fetch()
      const actual = (await respuesta.json()) as Record<string, unknown>
      await ruta.fulfill({ response: respuesta, json: { ...actual, estado: 'EXPIRADA' } })
      return
    }
    await ruta.continue()
  })

  const deleteExpirado = page.waitForResponse(
    (respuesta) =>
      new URL(respuesta.url()).pathname === `/api/v1/rfid-1/capturas/${capturaExpirada}` &&
      respuesta.request().method() === 'DELETE',
  )
  const getExpirado = page.waitForResponse(
    (respuesta) =>
      new URL(respuesta.url()).pathname === `/api/v1/rfid-1/capturas/${capturaExpirada}` &&
      respuesta.request().method() === 'GET',
  )
  await dialogo.getByRole('button', { name: 'Cancelar captura', exact: true }).click()
  expect((await deleteExpirado).status()).toBe(410)
  expect((await getExpirado).status()).toBe(200)
  await expect(dialogo.getByRole('status')).toContainText(
    'La captura venció. Inicia otra lectura para continuar.',
  )
  await expect(dialogo.getByText('2. Leer tarjeta', { exact: true })).toBeVisible()

  const csrfRespuesta = await page.context().request.get(webUrl('/api/v1/csrf'))
  expect(csrfRespuesta.status()).toBe(200)
  const csrf = (await csrfRespuesta.json()) as { token: string }
  const liberarCaptura = await page
    .context()
    .request.delete(webUrl(`/api/v1/rfid-1/capturas/${capturaExpirada}`), {
      headers: { 'X-CSRF-TOKEN': csrf.token },
    })
  expect(liberarCaptura.status()).toBe(204)

  const nuevaCapturaRespuesta = page.waitForResponse(
    (respuesta) =>
      new URL(respuesta.url()).pathname === '/api/v1/rfid-1/capturas' &&
      respuesta.request().method() === 'POST',
  )
  await dialogo.getByRole('button', { name: 'Iniciar otra lectura', exact: true }).click()
  const nuevaCaptura = await nuevaCapturaRespuesta
  expect(nuevaCaptura.status()).toBe(201)
  const { capturaId: capturaReintentada } = (await nuevaCaptura.json()) as { capturaId: string }
  expect(capturaReintentada === capturaExpirada, 'el reintento crea una captura nueva').toBe(false)

  const cancelacion = page.waitForResponse(
    (respuesta) =>
      new URL(respuesta.url()).pathname === `/api/v1/rfid-1/capturas/${capturaReintentada}` &&
      respuesta.request().method() === 'DELETE',
  )
  await dialogo.getByRole('button', { name: 'Cancelar captura', exact: true }).click()
  expect((await cancelacion).status()).toBe(204)
  await expect(dialogo.getByRole('status')).toContainText('La captura se canceló.')
  const estadoFinal = await page
    .context()
    .request.get(webUrl(`/api/v1/rfid-1/capturas/${capturaReintentada}`))
  expect(estadoFinal.status()).toBe(200)
  const capturaFinal = (await estadoFinal.json()) as { estado: string }
  expect(capturaFinal.estado).toBe('CANCELADA')
})
