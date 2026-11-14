import { randomUUID } from 'node:crypto'
import { expect, test, type BrowserContext, type Page } from '@playwright/test'

const baseURL = process.env.BASE_URL || process.env.TEST_WEB_BASE_URL || 'http://127.0.0.1:3000'

function ruta(path: string): string {
  return new URL(path, baseURL).toString()
}

async function esperarNuxt(page: Page): Promise<void> {
  await page.waitForLoadState('networkidle')
  await page.waitForFunction(() => {
    const raiz = document.querySelector('#__nuxt') as
      | (HTMLElement & { __vue_app__?: unknown })
      | null
    return Boolean(raiz?.__vue_app__)
  })
}

async function navegarLista(page: Page, path: string) {
  const respuesta = await page.goto(ruta(path))
  await esperarNuxt(page)
  return respuesta
}

async function registrar(page: Page, correo: string, contrasena: string): Promise<void> {
  await navegarLista(page, '/clientes/registro')
  await page.getByLabel('Nombre', { exact: true }).fill('Cliente')
  await page.getByLabel('Primer apellido', { exact: true }).fill('Sintético')
  await page.getByLabel('Segundo apellido (opcional)', { exact: true }).fill('Temporal')
  await page.getByLabel('Correo electrónico', { exact: true }).fill(correo)
  await page.getByLabel('Crear contraseña', { exact: true }).fill(contrasena)
  await expect(page.getByLabel('Confirmar contraseña', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Crear cuenta', exact: true }).click()
  await expect(page).toHaveURL(/\/clientes\/acceso\?registro=1$/)
  await esperarNuxt(page)
}

async function iniciarSesion(
  page: Page,
  correo: string,
  contrasena: string,
  destino: string,
): Promise<void> {
  await page.getByLabel('Correo electrónico', { exact: true }).fill(correo)
  await page.getByLabel('Contraseña', { exact: true }).fill(contrasena)
  await page.getByRole('button', { name: 'Iniciar sesión', exact: true }).click()
  await expect.poll(() => new URL(page.url()).pathname, { timeout: 15_000 }).toBe(destino)
  await esperarNuxt(page)
}

async function cookiesDe(context: BrowserContext) {
  const cookies = await context.cookies(baseURL)
  return new Set(cookies.map((cookie) => cookie.name))
}

async function valorCookie(context: BrowserContext, nombre: string): Promise<string> {
  const cookies = await context.cookies(baseURL)
  return cookies.find((cookie) => cookie.name === nombre)?.value ?? ''
}

test('registro y portal cliente conservan separada la sesión DUENO', async ({ browser, page }) => {
  const correoDueno = process.env.TEST_OWNER_EMAIL
  const contrasenaDueno = process.env.TEST_OWNER_PASSWORD
  if (!correoDueno || !contrasenaDueno) {
    throw new Error(
      'Define TEST_OWNER_EMAIL y TEST_OWNER_PASSWORD desde el entorno privado del runner.',
    )
  }

  const erroresCliente: string[] = []
  const avisosHidratacion: string[] = []
  page.on('pageerror', (error) => erroresCliente.push(error.name))
  page.on('console', (mensaje) => {
    if (mensaje.type() === 'error' && /hydration|mismatch/i.test(mensaje.text())) {
      avisosHidratacion.push(mensaje.text().slice(0, 120))
    }
  })

  const home = await navegarLista(page, '/')
  expect(home?.status()).toBe(200)
  await expect(page.getByRole('heading', { name: /Tu cuenta de Smart Parking/ })).toBeVisible()

  await navegarLista(page, '/panel')
  await page.getByLabel('Correo electrónico', { exact: true }).fill(correoDueno)
  await page.getByLabel('Contraseña', { exact: true }).fill(contrasenaDueno)
  await page.getByRole('button', { name: 'Iniciar sesión', exact: true }).click()
  await expect.poll(() => new URL(page.url()).pathname, { timeout: 15_000 }).toBe('/admin')
  await esperarNuxt(page)

  const paginaAnonima = await browser.newPage()
  const respuestasPortalAnonimo: number[] = []
  paginaAnonima.on('response', (respuesta) => {
    if (new URL(respuesta.url()).pathname === '/clientes/portal') {
      respuestasPortalAnonimo.push(respuesta.status())
    }
  })
  await navegarLista(paginaAnonima, '/clientes/portal')
  expect(new URL(paginaAnonima.url()).pathname).toBe('/clientes/acceso')
  expect(respuestasPortalAnonimo).toContain(302)
  await expect(paginaAnonima.getByRole('heading', { name: 'Inicia sesión' })).toBeVisible()
  await paginaAnonima.close()

  const correoCliente = 'cliente-' + randomUUID() + '@example.test'
  const contrasenaOriginal = 'Cliente-' + randomUUID() + '-Aa9!'
  const contrasenaNueva = 'Nueva-' + randomUUID() + '-Bb8!'
  const paginaCliente = await page.context().newPage()
  paginaCliente.on('pageerror', (error) => erroresCliente.push(error.name))
  paginaCliente.on('console', (mensaje) => {
    if (mensaje.type() === 'error' && /hydration|mismatch/i.test(mensaje.text())) {
      avisosHidratacion.push(mensaje.text().slice(0, 120))
    }
  })
  await registrar(paginaCliente, correoCliente, contrasenaOriginal)
  await expect(paginaCliente).toHaveURL(/\/clientes\/acceso\?registro=1$/)
  await expect(paginaCliente.getByRole('status')).toContainText('Tu cuenta se creó')

  let conflictoGenerico = false
  let limiteRegistro = false
  await navegarLista(paginaCliente, '/clientes/registro')
  await paginaCliente.getByLabel('Nombre', { exact: true }).fill('Cliente')
  await paginaCliente.getByLabel('Primer apellido', { exact: true }).fill('Sintético')
  await paginaCliente.getByLabel('Correo electrónico', { exact: true }).fill(correoCliente)
  await paginaCliente.getByLabel('Crear contraseña', { exact: true }).fill(contrasenaOriginal)
  await expect(paginaCliente.getByLabel('Confirmar contraseña', { exact: true })).toHaveCount(0)
  for (let intento = 0; intento < 6; intento += 1) {
    await paginaCliente.getByRole('button', { name: 'Crear cuenta', exact: true }).click()
    const mensaje = await paginaCliente.getByRole('alert').textContent()
    expect(mensaje).toBeTruthy()
    if (mensaje?.includes('Has intentado varias veces')) {
      limiteRegistro = true
      break
    }
    expect(mensaje).toContain('No pudimos crear la cuenta con esos datos')
    conflictoGenerico = true
  }
  expect(conflictoGenerico).toBe(true)
  expect(limiteRegistro).toBe(true)

  await navegarLista(paginaCliente, '/clientes/acceso')
  let solicitudesCheckout = 0
  paginaCliente.on('request', (solicitud) => {
    if (
      solicitud.method() === 'POST' &&
      new URL(solicitud.url()).pathname === '/api/v1/clientes/membresia/checkout'
    ) {
      solicitudesCheckout += 1
    }
  })
  await iniciarSesion(paginaCliente, correoCliente, contrasenaOriginal, '/clientes/portal')
  const respuestaSsrCuenta = await navegarLista(paginaCliente, '/clientes/portal')
  expect(respuestaSsrCuenta?.status()).toBe(200)
  const htmlSsrCuenta = await respuestaSsrCuenta!.text()
  await expect(paginaCliente.getByRole('heading', { name: 'Mi cuenta', exact: true })).toBeVisible()
  await expect(paginaCliente.getByRole('link', { name: 'Mi cuenta' })).toHaveAttribute(
    'aria-current',
    'page',
  )
  await expect(paginaCliente.getByText(correoCliente, { exact: true })).toBeVisible()
  expect(htmlSsrCuenta).toContain(correoCliente)
  await expect(paginaCliente.getByRole('link', { name: 'Inicio' })).toHaveCount(0)
  await expect(paginaCliente.locator('a[href^="/admin"]')).toHaveCount(0)

  const respuestaSsrMembresia = await navegarLista(
    paginaCliente,
    '/clientes/portal?seccion=membresia',
  )
  expect(respuestaSsrMembresia?.status()).toBe(200)
  const htmlSsrMembresia = await respuestaSsrMembresia!.text()
  await expect(paginaCliente.getByRole('heading', { name: 'Membresía', exact: true })).toBeVisible()
  await expect(paginaCliente.getByRole('link', { name: 'Membresía' })).toHaveAttribute(
    'aria-current',
    'page',
  )
  await expect(paginaCliente.getByRole('heading', { name: 'Información personal' })).toHaveCount(0)
  expect(htmlSsrMembresia).toContain(correoCliente)
  expect(htmlSsrMembresia).toContain('$399.00 MXN / mes')

  const respuestaPortal = await page.context().request.get(ruta('/api/v1/clientes/portal'))
  expect(respuestaPortal.status()).toBe(200)
  const datosPortal = await respuestaPortal.json()
  expect(datosPortal.cliente.correo).toBe(correoCliente)
  expect(datosPortal.membresia.estado).toBe('SIN_MEMBRESIA')
  expect(datosPortal.membresia.plan.nombre).toBe('Smart Parking - Membresía Mensual')
  expect(datosPortal.membresia.plan.importeMenorUnidad).toBe(39_900)
  expect(datosPortal.membresia.plan.moneda).toBe('MXN')
  await expect(paginaCliente.getByText('Sin membresía activa', { exact: true })).toBeVisible()
  await expect(paginaCliente.getByText('Smart Parking - Membresía Mensual')).toBeVisible()
  await expect(paginaCliente.getByText('$399.00 MXN / mes', { exact: true })).toBeVisible()

  expect(htmlSsrMembresia).not.toContain(datosPortal.cliente.clienteId)
  expect(htmlSsrMembresia).not.toMatch(/prod_[A-Za-z0-9]+|price_[A-Za-z0-9]+/)
  const botonComprar = paginaCliente.getByRole('button', { name: 'Comprar membresía', exact: true })
  await expect(botonComprar).toBeEnabled()
  expect(solicitudesCheckout).toBe(0)
  await expect(paginaCliente.getByRole('link', { name: /checkout|pagos|comprar/i })).toHaveCount(0)

  const contextoClienteB = await browser.newContext()
  const paginaClienteB = await contextoClienteB.newPage()
  const correoClienteB = 'cliente-' + randomUUID() + '@example.test'
  const contrasenaClienteB = 'Cliente-' + randomUUID() + '-Cc7!'
  await registrar(paginaClienteB, correoClienteB, contrasenaClienteB)
  await expect(paginaClienteB).toHaveURL(/\/clientes\/acceso\?registro=1$/)
  await navegarLista(paginaClienteB, '/clientes/acceso')
  await iniciarSesion(paginaClienteB, correoClienteB, contrasenaClienteB, '/clientes/portal')
  const portalClienteA = await page.context().request.get(ruta('/api/v1/clientes/portal'))
  const portalClienteB = await contextoClienteB.request.get(ruta('/api/v1/clientes/portal'))
  expect((await portalClienteA.json()).cliente.correo).toBe(correoCliente)
  expect((await portalClienteB.json()).cliente.correo).toBe(correoClienteB)

  for (const recursoDueno of [
    '/api/v1/panel',
    '/api/v1/empleados',
    '/api/v1/eventos/administracion',
  ]) {
    const respuestaRecursoDueno = await contextoClienteB.request.get(ruta(recursoDueno))
    expect(respuestaRecursoDueno.status()).toBe(401)
  }

  const idSesionClienteA = await valorCookie(page.context(), 'CLIENTSESSIONID')
  const idSesionClienteB = await valorCookie(contextoClienteB, 'CLIENTSESSIONID')
  expect(
    Boolean(idSesionClienteA && idSesionClienteB && idSesionClienteA !== idSesionClienteB),
  ).toBe(true)
  await contextoClienteB.close()

  const nombresCookies = await cookiesDe(page.context())
  expect(nombresCookies.has('JSESSIONID')).toBe(true)
  expect(nombresCookies.has('CLIENTSESSIONID')).toBe(true)
  const sesionDueno = await page.context().request.get(ruta('/api/v1/sesion'))
  const sesionCliente = await page.context().request.get(ruta('/api/v1/clientes/sesion'))
  expect((await sesionDueno.json()).rol).toBe('DUENO')
  expect((await sesionCliente.json()).rol).toBe('CLIENTE')

  const csrfDueno = await page.context().request.get(ruta('/api/v1/csrf'))
  const tokenCsrfDueno = (await csrfDueno.json()).token as string
  const rechazoCsrfCruzado = await page.context().request.post(ruta('/api/v1/clientes/sesion'), {
    headers: { 'x-csrf-token': tokenCsrfDueno },
    data: {
      correo: 'csrf-invalido-' + randomUUID() + '@example.test',
      contrasena: 'Dato sintetico que no autentica',
    },
  })
  expect(rechazoCsrfCruzado.status()).toBe(403)
  expect((await rechazoCsrfCruzado.json()).codigo).toBe('CSRF_RECHAZADO')

  const checkout = await page.context().request.get(ruta('/api/v1/clientes/checkout'))
  const pagos = await page.context().request.get(ruta('/api/v1/clientes/pagos'))
  const crearCheckout = await page.context().request.post(ruta('/api/v1/clientes/checkout'), {
    data: {},
  })
  expect(checkout.status()).toBe(404)
  expect(pagos.status()).toBe(404)
  expect(crearCheckout.status()).toBe(404)

  await paginaCliente.setViewportSize({ width: 375, height: 812 })
  const anchoDocumento = await paginaCliente.evaluate(() => document.documentElement.scrollWidth)
  expect(anchoDocumento).toBeLessThanOrEqual(375)
  await paginaCliente.setViewportSize({ width: 1280, height: 900 })

  await paginaCliente.getByRole('link', { name: 'Cambiar contraseña' }).click()
  await expect(paginaCliente).toHaveURL(/\/clientes\/portal\?seccion=contrasena$/)
  await expect(paginaCliente.getByRole('link', { name: 'Cambiar contraseña' })).toHaveAttribute(
    'aria-current',
    'page',
  )
  await paginaCliente.getByLabel('Contraseña actual', { exact: true }).fill(contrasenaOriginal)
  await paginaCliente.getByLabel('Contraseña nueva', { exact: true }).fill(contrasenaNueva)
  await paginaCliente
    .getByLabel('Confirmar contraseña nueva', { exact: true })
    .fill(contrasenaNueva)
  await paginaCliente.getByRole('button', { name: 'Actualizar contraseña', exact: true }).click()
  await expect(paginaCliente).toHaveURL(/\/clientes\/acceso\?contrasena=actualizada$/)
  await esperarNuxt(paginaCliente)
  await expect(paginaCliente.getByRole('status')).toContainText('La contraseña se actualizó')
  expect((await cookiesDe(page.context())).has('JSESSIONID')).toBe(true)
  expect((await cookiesDe(page.context())).has('CLIENTSESSIONID')).toBe(false)

  await paginaCliente.getByLabel('Correo electrónico', { exact: true }).fill(correoCliente)
  await paginaCliente.getByLabel('Contraseña', { exact: true }).fill(contrasenaOriginal)
  await paginaCliente.getByRole('button', { name: 'Iniciar sesión', exact: true }).click()
  await expect(paginaCliente.getByRole('alert')).toContainText(
    'El correo o la contraseña no son correctos',
  )
  await iniciarSesion(paginaCliente, correoCliente, contrasenaNueva, '/clientes/portal')
  const menuPerfil = paginaCliente.locator('details.perfil-portal')
  const activadorPerfil = menuPerfil.locator('summary')
  await activadorPerfil.focus()
  await paginaCliente.keyboard.press('Enter')
  await expect(menuPerfil).toHaveAttribute('open', '')
  await paginaCliente.getByRole('button', { name: 'Cerrar sesión', exact: true }).focus()
  await paginaCliente.keyboard.press('Escape')
  await expect(menuPerfil).not.toHaveAttribute('open')
  await expect(activadorPerfil).toBeFocused()
  await activadorPerfil.click()
  await paginaCliente.getByRole('button', { name: 'Cerrar sesión', exact: true }).click()
  await expect(paginaCliente).toHaveURL(/\/clientes\/acceso\?salida=1$/)
  await esperarNuxt(paginaCliente)
  expect((await cookiesDe(page.context())).has('CLIENTSESSIONID')).toBe(false)
  expect((await cookiesDe(page.context())).has('JSESSIONID')).toBe(true)

  await navegarLista(page, '/admin')
  await expect(page.getByText('Panel del propietario')).toBeVisible()
  const finDueno = await page.context().request.get(ruta('/api/v1/sesion'))
  expect((await finDueno.json()).rol).toBe('DUENO')
  await navegarLista(paginaCliente, '/clientes/portal')
  await expect(paginaCliente).toHaveURL(/\/clientes\/acceso$/)
  expect(erroresCliente).toEqual([])
  expect(avisosHidratacion).toEqual([])
})

test('dos solicitudes concurrentes de registro crean una sola cuenta', async ({ browser }) => {
  const contextos = await Promise.all([browser.newContext(), browser.newContext()])
  try {
    const [csrfA, csrfB] = await Promise.all(
      contextos.map((contexto) => contexto.request.get(ruta('/api/v1/clientes/csrf'))),
    )
    expect(csrfA.status()).toBe(200)
    expect(csrfB.status()).toBe(200)
    const [tokenA, tokenB] = await Promise.all([
      csrfA.json().then((respuesta) => respuesta.token as string),
      csrfB.json().then((respuesta) => respuesta.token as string),
    ])
    const correo = 'concurrente-' + randomUUID() + '@example.test'
    const contrasena = 'Concurrente-' + randomUUID() + '-Dd6!'
    const datos = {
      nombres: 'Alta concurrente',
      primerApellido: 'Sintético',
      segundoApellido: null,
      correo,
      contrasena,
      confirmarContrasena: contrasena,
    }
    const respuestas = await Promise.all(
      contextos.map((contexto, indice) =>
        contexto.request.post(ruta('/api/v1/clientes/registro'), {
          headers: { 'x-csrf-token': indice === 0 ? tokenA : tokenB },
          data: datos,
        }),
      ),
    )
    expect(respuestas.filter((respuesta) => respuesta.status() === 201)).toHaveLength(1)
    expect(respuestas.filter((respuesta) => respuesta.status() === 409)).toHaveLength(1)
  } finally {
    await Promise.all(contextos.map((contexto) => contexto.close()))
  }
})
