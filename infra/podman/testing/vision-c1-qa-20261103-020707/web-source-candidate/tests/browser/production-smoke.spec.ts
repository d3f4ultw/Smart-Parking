import { expect, test, type Page } from '@playwright/test'
import { baseURL } from './sesion'

async function esperarVueMontada(page: Page): Promise<void> {
  await page.waitForFunction(() => {
    const raiz = document.querySelector('#__nuxt') as
      | (HTMLElement & { __vue_app__?: unknown })
      | null
    return Boolean(raiz?.__vue_app__)
  })
}

test('build de produccion renderiza SSR, hidrata y abre el directorio con sesion', async ({
  page,
}) => {
  const correo = process.env.TEST_OWNER_EMAIL
  const contrasena = process.env.TEST_OWNER_PASSWORD
  if (!correo || !contrasena)
    throw new Error('Faltan credenciales sinteticas en el entorno del runner.')

  let intentoGetConCredenciales = false
  let respuestaLogin = 0
  let lecturasBffEmpleados = 0
  const erroresPagina: string[] = []
  let erroresConsola = 0

  page.on('pageerror', (error) => erroresPagina.push(error.name))
  page.on('console', (mensaje) => {
    if (mensaje.type() === 'error') erroresConsola += 1
  })
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (request.method() === 'GET' && url.pathname === '/api/v1/empleados')
      lecturasBffEmpleados += 1
  })
  page.on('response', (response) => {
    const request = response.request()
    const url = new URL(response.url())
    if (request.method() === 'POST' && url.pathname === '/api/v1/sesion')
      respuestaLogin = response.status()
  })
  await page.route('**/panel?*', async (route) => {
    const url = new URL(route.request().url())
    if (url.searchParams.has('correo') || url.searchParams.has('contrasena')) {
      intentoGetConCredenciales = true
      await route.abort('aborted')
      return
    }
    await route.continue()
  })

  const respuestaPanel = await page.goto(`${baseURL}/panel`)
  const estadoPanel = respuestaPanel?.status() ?? 0
  expect(estadoPanel).toBe(200)
  const htmlPanel = await respuestaPanel!.text()
  const panelSsr =
    htmlPanel.includes('Correo electrónico') &&
    htmlPanel.includes('Contraseña') &&
    htmlPanel.includes('Iniciar sesión')
  expect(panelSsr).toBe(true)
  await expect(page.getByLabel('Correo electrónico')).toBeVisible()
  await page.waitForLoadState('networkidle')
  const contextoSeguro = await page.evaluate(() => window.isSecureContext)
  expect(contextoSeguro).toBe(true)

  const campoContrasena = page.getByRole('textbox', { name: 'Contraseña' })
  await page.getByRole('button', { name: 'Mostrar contraseña', exact: true }).click()
  await expect(campoContrasena).toHaveAttribute('type', 'text')
  await page.getByRole('button', { name: 'Ocultar contraseña', exact: true }).click()
  await expect(campoContrasena).toHaveAttribute('type', 'password')

  await page.getByLabel('Correo electrónico').fill(correo)
  await campoContrasena.fill(contrasena)
  await page.getByRole('button', { name: 'Iniciar sesión' }).click({ noWaitAfter: true })
  await expect.poll(() => new URL(page.url()).pathname, { timeout: 15_000 }).toBe('/admin')
  expect(intentoGetConCredenciales).toBe(false)
  expect(respuestaLogin).toBe(200)

  lecturasBffEmpleados = 0
  console.log('PRODUCTION_SMOKE_SSR_EMPLOYEES_BEGIN')
  const respuestaEmpleados = await page.goto(`${baseURL}/admin/empleados`)
  const estadoEmpleados = respuestaEmpleados?.status() ?? 0
  expect(estadoEmpleados).toBe(200)
  const htmlEmpleados = await respuestaEmpleados!.text()
  const filasHtmlIniciales = (htmlEmpleados.match(/<tr(?:\s|>)/gi) ?? []).length
  expect(filasHtmlIniciales).toBeGreaterThan(0)
  await esperarVueMontada(page)
  await expect(page.getByRole('region', { name: 'Lista de empleados' }).first()).toBeVisible()
  await page.waitForTimeout(500)
  console.log('PRODUCTION_SMOKE_SSR_EMPLOYEES_END')

  expect(lecturasBffEmpleados).toBeLessThanOrEqual(1)
  expect(erroresPagina).toEqual([])
  console.log(
    `Producción SSR: panel=${estadoPanel}, empleados=${estadoEmpleados}, filas HTML=${filasHtmlIniciales}, GET BFF empleados=${lecturasBffEmpleados}, login=${respuestaLogin}, pageerrors=${erroresPagina.length}, console-errors=${erroresConsola}`,
  )
})
