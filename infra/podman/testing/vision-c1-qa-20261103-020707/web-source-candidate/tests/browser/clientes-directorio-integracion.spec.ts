import { expect, test } from '@playwright/test'
import { baseURL, iniciarSesion } from './sesion'

test('directorio real conserva URL, pagina, detalle y un unico SSE por sesion', async ({
  page,
}) => {
  await page.addInitScript(() => {
    const Original = window.EventSource
    const rutas: string[] = []
    Object.defineProperty(window, '__eventSourcesClientes', { value: rutas })
    window.EventSource = class extends Original {
      constructor(url: string | URL, init?: EventSourceInit) {
        super(url, init)
        rutas.push(new URL(String(url), window.location.href).pathname)
      }
    }
  })

  await iniciarSesion(page)
  await page.goto(`${baseURL}/admin/clientes`)
  await expect(page.locator('section[aria-label="Lista de clientes"]')).toBeVisible()
  const totalClientes = page.locator(
    'section[aria-label="Lista de clientes"] .resumen-directorio > div:first-child > span',
  )
  await expect(totalClientes).toHaveText(/^\d+ clientes en total\s*$/)
  const total = Number((await totalClientes.textContent())?.match(/\d+/)?.[0])
  expect(total).toBeGreaterThanOrEqual(12)
  await expect(page.getByRole('row').filter({ hasText: /CLI-[0-9]{4,}/ })).toHaveCount(10)
  await expect(page.getByText('CLI-0001', { exact: true })).toBeVisible()

  await expect
    .poll(() => page.evaluate(() => (window as Window & { __eventSourcesClientes?: string[] }).__eventSourcesClientes))
    .toEqual(['/api/v1/eventos/administracion'])

  const paginacion = page.getByRole('navigation', { name: 'Páginas de clientes' })
  await paginacion.locator('button').last().click()
  await expect(page).toHaveURL(/pagina=2/)
  await expect(page.getByText('CLI-0011', { exact: true })).toBeVisible()
  await expect(page.getByText('CLI-0012', { exact: true })).toBeVisible()

  await page.getByRole('combobox', { name: 'Estado de membresía' }).click()
  await page.getByRole('option', { name: 'Activa', exact: true }).click()
  await expect(page).toHaveURL(/estado=activa/)
  await expect(page).not.toHaveURL(/pagina=2/)
  await expect(page.getByText('CLI-0002', { exact: true })).toBeVisible()
  await expect(page.getByRole('table').getByText('Activa', { exact: true })).toBeVisible()

  await page.locator('#cliente-detalle-CLI-0002').click()
  const dialogo = page.getByRole('dialog')
  await expect(dialogo).toBeVisible()
  await expect(dialogo).toContainText('CLI-0002')
  await expect(dialogo).toContainText('Activa')
  await expect(dialogo).toContainText('Smart Parking - Membresía Mensual')
  await expect(dialogo).not.toContainText('cus_Fase3')
  await expect(dialogo).not.toContainText('sub_Fase3')
})
