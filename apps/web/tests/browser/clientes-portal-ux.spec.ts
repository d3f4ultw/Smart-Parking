import { expect, test, type Page } from '@playwright/test'

const baseURL = process.env.BASE_URL || process.env.TEST_WEB_BASE_URL || 'http://127.0.0.1:3000'
const correoPrueba = process.env.SMARTPARKING_TEST_CLIENT_EMAIL
const contrasenaPrueba = process.env.SMARTPARKING_TEST_CLIENT_PASSWORD

function ruta(path: string): string {
  return new URL(path, baseURL).toString()
}

async function esperarHidratacion(page: Page): Promise<void> {
  await page.waitForFunction(() => {
    const raiz = document.querySelector('#__nuxt') as
      | (HTMLElement & { __vue_app__?: unknown })
      | null
    return Boolean(raiz?.__vue_app__)
  })
}

async function iniciarSesion(page: Page): Promise<void> {
  await page.goto(ruta('/clientes/acceso'))
  await esperarHidratacion(page)
  await page.getByLabel('Correo electrónico', { exact: true }).fill(correoPrueba ?? '')
  await page.getByLabel('Contraseña', { exact: true }).fill(contrasenaPrueba ?? '')
  const botonAcceso = page.getByRole('button', { name: 'Iniciar sesión', exact: true })
  await expect(botonAcceso).toBeEnabled()
  await botonAcceso.click()
  await page.waitForURL(
    (url) => url.origin === new URL(baseURL).origin && url.pathname === '/clientes/portal',
  )
  await esperarHidratacion(page)
}

test.afterEach(async ({ page }) => {
  if (new URL(page.url()).pathname !== '/clientes/portal') return
  const menuCuenta = page.locator('details.perfil-portal')
  const botonCerrarSesion = page.getByRole('button', { name: 'Cerrar sesión', exact: true })
  if (!(await botonCerrarSesion.count())) return
  if (!(await menuCuenta.evaluate((element) => (element as HTMLDetailsElement).open))) {
    await menuCuenta.locator('summary').click()
  }
  await botonCerrarSesion.click()
  await page.waitForURL((url) => url.pathname === '/clientes/acceso')
})

test('el portal cliente organiza sus secciones, perfil y contraseña', async ({ page }) => {
  test.skip(
    !correoPrueba || !contrasenaPrueba,
    'Define SMARTPARKING_TEST_CLIENT_EMAIL y SMARTPARKING_TEST_CLIENT_PASSWORD en el runner privado.',
  )

  const erroresCliente: string[] = []
  const erroresRecursosPortal: number[] = []
  let solicitudesCheckout = 0
  let solicitudesCambioContrasena = 0
  page.on('pageerror', (error) => erroresCliente.push(error.name))
  page.on('response', (respuesta) => {
    const rutaRespuesta = new URL(respuesta.url()).pathname
    if (
      respuesta.status() >= 400 &&
      (rutaRespuesta.endsWith('/pages/clientes/portal.vue') ||
        rutaRespuesta.endsWith('/assets/css/cliente-portal.css'))
    ) {
      erroresRecursosPortal.push(respuesta.status())
    }
  })
  page.on('request', (solicitud) => {
    const rutaSolicitud = new URL(solicitud.url()).pathname
    if (solicitud.method() === 'POST' && rutaSolicitud === '/api/v1/clientes/membresia/checkout') {
      solicitudesCheckout += 1
    }
    if (solicitud.method() === 'PATCH' && rutaSolicitud === '/api/v1/clientes/contrasena') {
      solicitudesCambioContrasena += 1
    }
  })

  await iniciarSesion(page)
  const cuenta = await page.goto(ruta('/clientes/portal'))
  await esperarHidratacion(page)
  expect(cuenta?.status()).toBe(200)
  await expect(page.getByRole('heading', { name: 'Mi cuenta', exact: true })).toBeVisible()
  await expect(page.locator('.correo-perfil-portal')).toHaveText(correoPrueba!)
  await expect(page.getByRole('link', { name: 'Inicio' })).toHaveCount(0)
  await expect(page.locator('a[href^="/admin"]')).toHaveCount(0)

  await page.getByRole('link', { name: 'Membresía', exact: true }).click()
  await expect(page).toHaveURL(/\/clientes\/portal\?seccion=membresia$/)
  await expect(page.getByRole('link', { name: 'Membresía' })).toHaveAttribute(
    'aria-current',
    'page',
  )
  await expect(page.locator('[data-estado-membresia]')).toBeVisible()
  await expect(page.locator('.estado-membresia')).toBeVisible()
  await expect(page.locator('.datos-plan-cliente h3')).toBeVisible()
  await expect(page.locator('.precio-plan-cliente')).toContainText('/')
  const estadoMembresia = await page
    .locator('[data-estado-membresia]')
    .getAttribute('data-estado-membresia')
  expect(estadoMembresia).toBeTruthy()
  const accesosCompra =
    (await page.getByRole('button', { name: 'Comprar membresía', exact: true }).count()) +
    (await page.getByRole('button', { name: 'Continuar con Checkout', exact: true }).count()) +
    (await page
      .getByText('La compra no está disponible con el estado actual de tu membresía.')
      .count())
  expect(accesosCompra).toBeGreaterThan(0)

  await page.goto(ruta('/clientes/portal?seccion=membresia'))
  await esperarHidratacion(page)
  await expect(page.getByRole('heading', { name: 'Membresía', exact: true })).toBeVisible()
  await page.reload()
  await esperarHidratacion(page)
  await expect(page.getByRole('link', { name: 'Membresía' })).toHaveAttribute(
    'aria-current',
    'page',
  )

  await page.getByRole('link', { name: 'Cambiar contraseña', exact: true }).click()
  await expect(page).toHaveURL(/\/clientes\/portal\?seccion=contrasena$/)
  await esperarHidratacion(page)
  await expect(page.getByLabel('Contraseña actual', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Contraseña nueva', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Confirmar contraseña nueva', { exact: true })).toBeVisible()
  await page.getByLabel('Contraseña actual', { exact: true }).fill('clave actual de prueba')
  await page.getByLabel('Contraseña nueva', { exact: true }).fill('corta')
  await page.getByLabel('Confirmar contraseña nueva', { exact: true }).fill('corta')
  await page.getByRole('button', { name: 'Actualizar contraseña', exact: true }).click()
  await expect(
    page.getByText('La contraseña nueva debe tener al menos 10 caracteres.'),
  ).toBeVisible()
  expect(solicitudesCambioContrasena).toBe(0)

  await page.getByLabel('Contraseña nueva', { exact: true }).fill('NuevaClave123')
  await page.getByLabel('Confirmar contraseña nueva', { exact: true }).fill('OtraClave123')
  await page.getByRole('button', { name: 'Actualizar contraseña', exact: true }).click()
  await expect(page.getByText('Las contraseñas nuevas no coinciden.')).toBeVisible()
  expect(solicitudesCambioContrasena).toBe(0)

  for (const viewport of [
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 1280, height: 900 },
  ]) {
    await page.setViewportSize(viewport)
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
  }

  await page.getByRole('link', { name: 'Mi cuenta', exact: true }).click()
  const menuPerfil = page.locator('details.perfil-portal')
  const activadorPerfil = menuPerfil.locator('summary')
  await activadorPerfil.focus()
  await page.keyboard.press('Enter')
  await expect(menuPerfil).toHaveAttribute('open', '')
  await page.getByRole('button', { name: 'Cerrar sesión', exact: true }).focus()
  await page.keyboard.press('Escape')
  await expect(menuPerfil).not.toHaveAttribute('open')
  await expect(activadorPerfil).toBeFocused()
  await activadorPerfil.click()
  await page.getByRole('button', { name: 'Cerrar sesión', exact: true }).click()
  await expect(page).toHaveURL(/\/clientes\/acceso\?salida=1$/)
  expect(solicitudesCheckout).toBe(0)
  expect(erroresRecursosPortal).toEqual([])
  expect(erroresCliente).toEqual([])
})

test('la ruta protegida redirige al acceso sin sesión cliente', async ({ page }) => {
  const respuesta = await page.goto(ruta('/clientes/portal?seccion=membresia'))
  expect(respuesta?.status()).toBe(200)
  await expect(page).toHaveURL(/\/clientes\/acceso$/)
  await expect(page.getByRole('heading', { name: 'Inicia sesión', exact: true })).toBeVisible()
  await expect(page.locator('.barra-lateral-portal')).toHaveCount(0)
})
