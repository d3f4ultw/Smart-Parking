import { expect, test, type Page } from '@playwright/test'
import { baseURL, iniciarSesion } from './sesion'

const OPERADOR_PENDIENTE = '10000000-0000-4000-8000-000000000002'
const OPERADOR_ACTIVO = '10000000-0000-4000-8000-000000000001'
const OPERADOR_INACTIVO = '10000000-0000-4000-8000-000000000003'

test('solo ofrece reenviar la invitación a cuentas Por activar', async ({ page }) => {
  await iniciarSesion(page)
  await page.goto(`${baseURL}/admin/operadores`)
  await esperarHidratacionNuxt(page)
  await expect(page.getByRole('region', { name: 'Lista de operadores' }).first()).toBeVisible()

  await forzarPuedeReemitir(page, OPERADOR_PENDIENTE)
  const respuestaPendiente = esperarRespuestaDetalle(page, OPERADOR_PENDIENTE)
  await page.getByRole('button', {
    name: 'Administrar Operador Pendiente Fixture Pendiente',
    exact: true,
  }).click()
  expect((await respuestaPendiente).status()).toBe(200)
  const dialogoPendiente = page.getByRole('dialog')
  await expect(dialogoPendiente).toContainText('Por activar')
  await expect(
    dialogoPendiente.getByRole('button', { name: 'Reenviar invitación', exact: true }),
  ).toBeVisible()
  await dialogoPendiente.getByRole('button', { name: 'Reenviar invitación', exact: true }).click()
  await expect(dialogoPendiente.getByRole('heading', { name: 'Reenviar invitación' })).toBeVisible()
  await expect(dialogoPendiente).toContainText('El enlace anterior dejará de funcionar')
  await dialogoPendiente.getByRole('button', { name: 'Cancelar', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(dialogoPendiente).toBeHidden()

  await forzarPuedeReemitir(page, OPERADOR_ACTIVO)
  const respuestaActiva = esperarRespuestaDetalle(page, OPERADOR_ACTIVO)
  await page.getByRole('button', {
    name: 'Administrar Operadora Activa Fixture Activa',
    exact: true,
  }).click()
  expect((await respuestaActiva).status()).toBe(200)
  const dialogoActivo = page.getByRole('dialog')
  await expect(dialogoActivo).toContainText('Activa')
  await expect(
    dialogoActivo.getByRole('button', { name: 'Reenviar invitación', exact: true }),
  ).toHaveCount(0)
  await expect(
    dialogoActivo.getByRole('button', { name: 'Recuperar contraseña', exact: true }),
  ).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialogoActivo).toBeHidden()

  await forzarPuedeReemitir(page, OPERADOR_INACTIVO)
  const respuestaInactiva = esperarRespuestaDetalle(page, OPERADOR_INACTIVO)
  await page.getByRole('button', {
    name: 'Administrar Operador Inactivo Fixture Inactivo',
    exact: true,
  }).click()
  expect((await respuestaInactiva).status()).toBe(200)
  await expect(
    page.getByRole('dialog').getByRole('button', { name: 'Reenviar invitación', exact: true }),
  ).toHaveCount(0)
})

async function forzarPuedeReemitir(page: Page, operadorId: string) {
  await page.route(`**/api/v1/operadores/${operadorId}`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    const respuesta = await route.fetch()
    if (!respuesta.ok()) return route.fulfill({ response: respuesta })
    const detalle = await respuesta.json() as Record<string, unknown>
    await route.fulfill({ response: respuesta, json: { ...detalle, puedeReemitirInvitacion: true } })
  })
}

function esperarRespuestaDetalle(page: Page, operadorId: string) {
  return page.waitForResponse((respuesta) => {
    const url = new URL(respuesta.url())
    return url.pathname === `/api/v1/operadores/${operadorId}`
      && respuesta.request().method() === 'GET'
  })
}

async function esperarHidratacionNuxt(page: Page) {
  await page.waitForFunction(() => {
    const raiz = document.querySelector('#__nuxt') as (HTMLElement & { __vue_app__?: unknown }) | null
    return Boolean(raiz?.__vue_app__)
  })
}
