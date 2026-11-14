import { expect, test, type Page } from '@playwright/test'

const FRAGMENTO_PRUEBA = 'fixture-de-activacion-sintetico'
const CLAVE_CSRF_PRUEBA = 'csrf-fixture-sintetica'

async function abrirFormulario(page: Page, estadoValidacion = 200) {
  await page.route('**/api/v1/csrf', (ruta) => ruta.fulfill({ json: { token: CLAVE_CSRF_PRUEBA } }))
  await page.route('**/api/v1/operadores/activacion/validar', (ruta) =>
    ruta.fulfill({
      status: estadoValidacion,
      json: estadoValidacion === 200 ? { valida: true } : { error: 'fixture' },
    }),
  )
  await page.goto(`/activar-operador#${FRAGMENTO_PRUEBA}`)
}

test('valida el mínimo, muestra la palomita y conserva la visibilidad accesible', async ({
  page,
}) => {
  let solicitudesCompletadas = 0
  await page.route('**/api/v1/operadores/activacion/completar', (ruta) => {
    solicitudesCompletadas += 1
    return ruta.fulfill({ status: 200 })
  })
  await abrirFormulario(page)

  const contrasena = page.getByLabel('Contraseña', { exact: true })
  const activar = page.getByRole('button', { name: 'Activar cuenta', exact: true })
  await expect(page.getByRole('heading', { name: 'Activar cuenta' })).toBeVisible()
  await expect(page.getByLabel('Confirmar contraseña')).toHaveCount(0)
  await expect(page.getByText(/Elige una contraseña larga|mayúsculas y minúsculas/)).toHaveCount(0)
  await expect(page).not.toHaveURL(/#./)
  await expect(contrasena).toHaveAttribute('autocomplete', 'new-password')
  await expect(contrasena).toHaveAttribute('name', 'password')
  expect(await page.content()).not.toContain(FRAGMENTO_PRUEBA)
  expect(await page.locator('#__NUXT_DATA__').textContent()).not.toContain(FRAGMENTO_PRUEBA)

  await activar.click()
  await expect(page.getByRole('alert')).toHaveText('Ingresa una contraseña.')
  await expect(contrasena).toHaveAttribute('aria-invalid', 'true')

  await contrasena.fill('123456789')
  await expect(page.getByTestId('indicador-contrasena-valida')).toHaveCount(0)
  await activar.click()
  await expect(page.getByRole('alert')).toHaveText(
    'La contraseña debe tener al menos 10 caracteres.',
  )
  expect(solicitudesCompletadas).toBe(0)

  await contrasena.fill('1234567890')
  await expect(page.getByTestId('indicador-contrasena-valida')).toBeVisible()
  await expect(contrasena).not.toHaveAttribute('maxlength')
  await page.getByRole('button', { name: 'Mostrar contraseña' }).click()
  await expect(contrasena).toHaveAttribute('type', 'text')
  await expect(page.getByRole('button', { name: 'Ocultar contraseña' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await page.getByRole('button', { name: 'Ocultar contraseña' }).click()
  await expect(contrasena).toHaveAttribute('type', 'password')
  expect(solicitudesCompletadas).toBe(0)
})

test('muestra la carga, evita dobles envíos y mantiene el contrato vigente del API', async ({
  page,
}) => {
  let solicitudesCompletadas = 0
  let cuerpoEnviado: Record<string, unknown> | undefined
  await page.route('**/api/v1/operadores/activacion/completar', async (ruta) => {
    solicitudesCompletadas += 1
    cuerpoEnviado = ruta.request().postDataJSON() as Record<string, unknown>
    await new Promise((resolver) => setTimeout(resolver, 500))
    await ruta.fulfill({ status: 200 })
  })
  await abrirFormulario(page)
  await page.getByLabel('Contraseña', { exact: true }).fill('clave-fixture-segura')

  await page.getByRole('button', { name: 'Activar cuenta', exact: true }).click()
  const botonCargando = page.getByRole('button', { name: 'Activando…', exact: true })
  await expect(botonCargando).toBeDisabled()
  await page.locator('form').evaluate((form) => (form as HTMLFormElement).requestSubmit())
  await expect(page.getByRole('status').getByText('Tu cuenta está lista.')).toBeVisible()

  expect(solicitudesCompletadas).toBe(1)
  expect(cuerpoEnviado?.contrasena).toBe('clave-fixture-segura')
  expect(cuerpoEnviado?.confirmarContrasena).toBe(cuerpoEnviado?.contrasena)
})

test('muestra un error de contraseña del servidor junto al campo sin borrar su valor', async ({
  page,
}) => {
  await page.route('**/api/v1/operadores/activacion/completar', (ruta) =>
    ruta.fulfill({ status: 400, json: { error: 'fixture' } }),
  )
  await abrirFormulario(page)
  const contrasena = page.getByLabel('Contraseña', { exact: true })
  await contrasena.fill('clave-fixture-segura')
  await page.getByRole('button', { name: 'Activar cuenta', exact: true }).click()

  await expect(page.getByRole('alert')).toHaveText('Revisa la contraseña e inténtalo de nuevo.')
  await expect(contrasena).toHaveValue('clave-fixture-segura')
  await expect(contrasena).toHaveAttribute('aria-invalid', 'true')
  const idError = await page.locator('[data-slot="error"]').getAttribute('id')
  expect(await contrasena.getAttribute('aria-describedby')).toContain(idError)
})

test('distingue un enlace vencido o usado de una página recargada sin enlace', async ({ page }) => {
  await abrirFormulario(page, 410)
  await expect(page.getByRole('alert')).toContainText('Este enlace venció o ya se usó.')

  const paginaConEnlace = await page.context().newPage()
  let validaciones = 0
  await paginaConEnlace.route('**/api/v1/csrf', (ruta) =>
    ruta.fulfill({ json: { token: CLAVE_CSRF_PRUEBA } }),
  )
  await paginaConEnlace.route('**/api/v1/operadores/activacion/validar', (ruta) => {
    validaciones += 1
    return ruta.fulfill({ json: { valida: true } })
  })
  await paginaConEnlace.goto(`/activar-operador#${FRAGMENTO_PRUEBA}`)
  await expect(paginaConEnlace.getByLabel('Contraseña', { exact: true })).toBeVisible()
  await expect(paginaConEnlace).not.toHaveURL(/#./)
  await paginaConEnlace.reload()
  await expect(paginaConEnlace.getByRole('status')).toContainText(
    'Vuelve a abrir la invitación desde el correo.',
  )
  expect(validaciones).toBe(1)
  await paginaConEnlace.close()
})

test('mantiene teclado, alineación y ancho móvil sin errores de consola o red', async ({
  page,
}) => {
  const erroresConsola: string[] = []
  const erroresPagina: string[] = []
  const solicitudesFallidas: string[] = []
  page.on('console', (mensaje) => {
    if (mensaje.type() === 'error') erroresConsola.push(mensaje.text())
  })
  page.on('pageerror', (error) => erroresPagina.push(error.message))
  page.on('requestfailed', (solicitud) => solicitudesFallidas.push(solicitud.url()))
  await page.route('**/api/v1/operadores/activacion/completar', (ruta) =>
    ruta.fulfill({ status: 200 }),
  )
  await abrirFormulario(page)
  await expect(page.getByLabel('Contraseña', { exact: true })).toBeVisible()

  const campo = page.getByLabel('Contraseña', { exact: true })
  const boton = page.getByRole('button', { name: 'Activar cuenta', exact: true })
  for (const tamano of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(tamano)
    const medidas = await page.evaluate(() => {
      const tarjeta = document.querySelector('.tarjeta-activacion')!.getBoundingClientRect()
      const campo = document.querySelector('#activacion-contrasena')!.getBoundingClientRect()
      const boton = document.querySelector('button[type="submit"]')!.getBoundingClientRect()
      return {
        anchoDocumento: document.documentElement.scrollWidth,
        anchoVentana: window.innerWidth,
        centroTarjeta: tarjeta.left + tarjeta.width / 2,
        centroVentana: window.innerWidth / 2,
        anchoCampo: campo.width,
        anchoBoton: boton.width,
      }
    })
    expect(medidas.anchoDocumento).toBeLessThanOrEqual(medidas.anchoVentana)
    expect(Math.abs(medidas.centroTarjeta - medidas.centroVentana)).toBeLessThan(2)
    expect(Math.abs(medidas.anchoCampo - medidas.anchoBoton)).toBeLessThan(2)
  }

  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.keyboard.press('Tab')
  await expect(campo).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Mostrar contraseña' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(boton).toBeFocused()
  await campo.fill('clave-fixture-segura')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('status').getByText('Tu cuenta está lista.')).toBeVisible()

  expect(erroresConsola).toEqual([])
  expect(erroresPagina).toEqual([])
  expect(solicitudesFallidas).toEqual([])
})
