import { randomUUID } from 'node:crypto'
import { expect, test, type Page } from '@playwright/test'

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

function timeoutSesionMs(): number {
  const valor = (process.env.TEST_SESSION_TIMEOUT ?? process.env.SESSION_TIMEOUT)?.trim()
  if (!valor) return 0
  if (/^\d+$/.test(valor)) return Number(valor) * 1000
  const simple = valor.match(/^(\d+)\s*(ms|s|m|h)$/i)
  if (simple) {
    const unidad = simple[2].toLowerCase()
    const factor = unidad === 'ms' ? 1 : unidad === 's' ? 1000 : unidad === 'm' ? 60_000 : 3_600_000
    return Number(simple[1]) * factor
  }
  const iso = valor.match(/^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$/i)
  if (iso) {
    return (
      Number(iso[1] ?? 0) * 3_600_000 + Number(iso[2] ?? 0) * 60_000 + Number(iso[3] ?? 0) * 1000
    )
  }
  throw new Error('TEST_SESSION_TIMEOUT debe usar segundos, ms, s, m, h o duración ISO PT.')
}

async function registrar(page: Page, correo: string, contrasena: string): Promise<void> {
  await navegarLista(page, '/clientes/registro')
  await page.getByLabel('Nombre', { exact: true }).fill('Cuenta')
  await page.getByLabel('Primer apellido', { exact: true }).fill('Temporal')
  await page.getByLabel('Correo electrónico', { exact: true }).fill(correo)
  await page.getByLabel('Crear contraseña', { exact: true }).fill(contrasena)
  await page.getByRole('button', { name: 'Crear cuenta', exact: true }).click()
  await expect(page).toHaveURL(/\/clientes\/acceso\?registro=1$/)
  await esperarNuxt(page)
}

test('la sesión CLIENTE vence y el portal vuelve a pedir acceso', async ({ page }) => {
  const esperaMs = timeoutSesionMs()
  test.skip(esperaMs < 1, 'Reinicia solo la API aislada con TEST_SESSION_TIMEOUT=5s.')
  test.setTimeout(esperaMs + 45_000)

  const correo = 'expira-' + randomUUID() + '@example.test'
  const contrasena = 'Expira-' + randomUUID() + '-Ee5!'
  await registrar(page, correo, contrasena)
  await expect(page).toHaveURL(/\/clientes\/acceso\?registro=1$/)
  await navegarLista(page, '/clientes/acceso')
  await page.getByLabel('Correo electrónico', { exact: true }).fill(correo)
  await page.getByLabel('Contraseña', { exact: true }).fill(contrasena)
  await page.getByRole('button', { name: 'Iniciar sesión', exact: true }).click()
  await expect
    .poll(() => new URL(page.url()).pathname, { timeout: 15_000 })
    .toBe('/clientes/portal')
  await esperarNuxt(page)

  const portalInicial = await navegarLista(page, '/clientes/portal')
  expect(portalInicial?.status()).toBe(200)
  await expect(page.getByText(correo, { exact: true })).toBeVisible()
  await page.waitForTimeout(esperaMs + 1_500)

  const respuestasExpiracion: number[] = []
  page.on('response', (respuesta) => {
    if (new URL(respuesta.url()).pathname === '/clientes/portal') {
      respuestasExpiracion.push(respuesta.status())
    }
  })
  await navegarLista(page, '/clientes/portal')
  expect(respuestasExpiracion).toContain(302)
  await expect(page).toHaveURL(/\/clientes\/acceso$/)
  await expect(page.getByRole('heading', { name: 'Inicia sesión' })).toBeVisible()
  await expect(page.getByText(correo, { exact: true })).toHaveCount(0)
})
