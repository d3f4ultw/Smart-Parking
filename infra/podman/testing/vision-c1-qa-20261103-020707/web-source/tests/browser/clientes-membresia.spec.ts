import { expect, test, type Locator, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'

test.use({
  actionTimeout: 20_000,
  navigationTimeout: 45_000,
  screenshot: 'off',
  trace: 'off',
  video: 'off',
  viewport: { width: 1280, height: 900 },
})

const baseUrl = process.env.SMARTPARKING_WEB_URL ?? 'http://localhost:3100'
const origenWeb = new URL(baseUrl).origin

function esperarRespuestaApi(pagina: Page, metodo: string, ruta: string) {
  return pagina.waitForResponse(
    (respuesta) =>
      respuesta.request().method() === metodo && new URL(respuesta.url()).pathname === ruta,
  )
}

async function esperarComponenteCliente(pagina: Page, elemento: Locator) {
  await expect
    .poll(
      async () => {
        const aplicacionMontada = await pagina
          .evaluate(() => {
            const raiz = document.querySelector('#__nuxt') as
              | (HTMLElement & { __vue_app__?: unknown })
              | null
            return Boolean(raiz?.__vue_app__)
          })
          .catch(() => false)
        const componenteMontado = await elemento
          .evaluate((nodo) =>
            Boolean(
              (nodo as HTMLElement & { __vueParentComponent?: unknown }).__vueParentComponent,
            ),
          )
          .catch(() => false)
        return aplicacionMontada && componenteMontado
      },
      { timeout: 5_000 },
    )
    .toBe(true)
}

async function llenarCampoStripe(
  pagina: Page,
  etiqueta: RegExp,
  autocomplete: string,
  valor: string,
) {
  const encontrarCampo = async () => {
    for (const marco of pagina.frames()) {
      const porAutocomplete = marco.locator(`input[autocomplete="${autocomplete}"]`).first()
      if (await porAutocomplete.count()) return porAutocomplete
      const porEtiqueta = marco.getByLabel(etiqueta).first()
      if (await porEtiqueta.count()) return porEtiqueta
    }
    return null
  }

  const limite = Date.now() + 30_000
  let campo = await encontrarCampo()
  while (!campo && Date.now() < limite) {
    await pagina.waitForTimeout(250)
    campo = await encontrarCampo()
  }
  if (!campo) throw new Error('No estuvo disponible un campo requerido del Checkout Sandbox.')
  await campo.fill(valor)
}

async function llenarCampoOpcionalStripe(
  pagina: Page,
  autocomplete: string,
  valor: string,
  etiqueta?: RegExp,
) {
  for (const marco of pagina.frames()) {
    const campo = marco.locator(`input[autocomplete="${autocomplete}"]`).first()
    if (await campo.count()) {
      await campo.fill(valor)
      return true
    }
    if (etiqueta) {
      const porEtiqueta = marco.getByLabel(etiqueta).first()
      if (await porEtiqueta.count()) {
        await porEtiqueta.fill(valor)
        return true
      }
    }
  }
  return false
}

async function leerEstadoMembresia(pagina: Page): Promise<string> {
  return pagina.evaluate(async () => {
    const respuesta = await fetch('/api/v1/clientes/portal', { cache: 'no-store' })
    if (!respuesta.ok) return ''
    const cuerpo = await respuesta.json()
    return typeof cuerpo?.membresia?.estado === 'string' ? cuerpo.membresia.estado : ''
  })
}

test('registro con una contraseña y Checkout Sandbox aplican la membresía por webhook', async ({
  page,
}) => {
  test.setTimeout(240_000)
  const correo = `cliente-${randomUUID()}@example.test`
  const contrasena = `Sandbox-${randomUUID()}-26!`
  const formulario = page.locator('form.formulario-cliente')

  await page.goto(`${baseUrl}/clientes/registro`)
  await expect(formulario).toBeVisible()
  await expect(page.locator('input[autocomplete="new-password"]')).toHaveCount(1)
  await expect(page.getByLabel(/confirmar contraseña/i)).toHaveCount(0)
  await esperarComponenteCliente(page, formulario)

  await page.getByLabel('Nombre').fill('Cliente Sandbox')
  await page.getByLabel('Primer apellido').fill('Prueba')
  await page.getByLabel('Correo electrónico').fill(correo)
  await page.getByLabel('Crear contraseña').fill(contrasena)

  const csrfRegistro = esperarRespuestaApi(page, 'GET', '/api/v1/clientes/csrf')
  const respuestaRegistro = esperarRespuestaApi(page, 'POST', '/api/v1/clientes/registro')
  await page.getByRole('button', { name: 'Crear cuenta' }).click()
  expect((await csrfRegistro).status()).toBe(200)
  expect((await respuestaRegistro).status()).toBe(201)
  await page.waitForURL(
    (url) =>
      url.origin === origenWeb &&
      url.pathname === '/clientes/acceso' &&
      url.searchParams.get('registro') === '1',
  )
  expect(
    (await page.context().cookies(baseUrl)).some((cookie) => cookie.name === 'CLIENTSESSIONID'),
  ).toBe(false)

  await expect(formulario).toBeVisible()
  await esperarComponenteCliente(page, formulario)
  await page.getByLabel('Correo electrónico').fill(correo)
  await expect(page.locator('input[autocomplete="current-password"]')).toHaveCount(1)
  await page.locator('input[autocomplete="current-password"]').fill(contrasena)
  const respuestaInicioSesion = esperarRespuestaApi(page, 'POST', '/api/v1/clientes/sesion')
  await page.getByRole('button', { name: 'Iniciar sesión' }).click()
  expect((await respuestaInicioSesion).status()).toBe(200)
  await page.waitForURL((url) => url.origin === origenWeb && url.pathname === '/clientes/portal')
  await expect(page.getByText('Sin membresía activa')).toBeVisible()
  await expect(page.getByText(/399[.,]00\s*MXN\s*\/\s*mes/)).toBeVisible()

  const botonComprar = page.getByRole('button', { name: 'Comprar membresía' })
  await expect(botonComprar).toBeEnabled()
  await esperarComponenteCliente(page, botonComprar)
  const cookies = await page.context().cookies(baseUrl)
  const cookieCliente = cookies.find((cookie) => cookie.name === 'CLIENTSESSIONID')
  expect(cookieCliente?.httpOnly).toBe(true)
  expect(cookieCliente?.sameSite).toBe('Strict')
  expect(cookies.some((cookie) => cookie.name === 'JSESSIONID')).toBe(false)

  await page.reload()
  await expect(page.getByText('Sin membresía activa')).toBeVisible()
  await expect(botonComprar).toBeEnabled()
  await esperarComponenteCliente(page, botonComprar)

  const respuestaCheckout = esperarRespuestaApi(page, 'POST', '/api/v1/clientes/membresia/checkout')
  await botonComprar.click()
  expect((await respuestaCheckout).status()).toBe(201)
  await page.waitForURL((url) => url.hostname === 'checkout.stripe.com', {
    timeout: 15_000,
    waitUntil: 'commit',
  })

  await llenarCampoStripe(page, /card number|número de tarjeta/i, 'cc-number', '4242424242424242')
  await llenarCampoStripe(page, /expiration|expiry|vencimiento/i, 'cc-exp', '1234')
  await llenarCampoStripe(page, /security code|cvc|código de seguridad/i, 'cc-csc', '123')
  await llenarCampoOpcionalStripe(page, 'email', correo)
  const nombreTarjetaLlenado =
    (await llenarCampoOpcionalStripe(page, 'cc-name', 'SmartParking Test', /name|nombre/i)) ||
    (await llenarCampoOpcionalStripe(page, 'name', 'SmartParking Test', /name|nombre/i))
  expect(nombreTarjetaLlenado).toBe(true)
  await llenarCampoOpcionalStripe(page, 'postal-code', '44100')

  await page.getByRole('button', { name: /subscribe|pay|pagar|suscribir/i }).click()
  await page.waitForURL(
    (url) => url.origin === origenWeb && url.pathname === '/clientes/checkout/retorno',
    { timeout: 30_000, waitUntil: 'commit' },
  )
  await expect(page.getByRole('heading', { name: 'Regresaste de Checkout' })).toBeVisible()
  await expect(
    page.getByText(/El regreso desde Checkout no confirma el pago ni activa la membresía/),
  ).toBeVisible()
  await expect(page.getByRole('status')).toHaveText(/La consulta terminó/)

  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await expect
    .poll(() => leerEstadoMembresia(page), {
      timeout: 45_000,
      intervals: [1_000, 2_000, 4_000],
    })
    .toBe('ACTIVA')
})
