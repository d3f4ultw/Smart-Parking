import { expect, test } from '@playwright/test'
import { baseURL, iniciarSesion } from '../sesion'

const url = (ruta: string) => new URL(ruta, baseURL).toString()

const candidatos = [
  {
    tipoEntidad: 'CLIENTE',
    codigoPersona: 'CLI-1001',
    nombreCompleto: 'Cliente sin membresía',
    estadoAdministrativo: 'ACTIVA',
    elegible: false,
    motivoNoElegible: 'CLIENTE_SIN_MEMBRESIA',
  },
  {
    tipoEntidad: 'CLIENTE',
    codigoPersona: 'CLI-1002',
    nombreCompleto: 'Cliente con membresía',
    estadoAdministrativo: 'ACTIVA',
    elegible: true,
    motivoNoElegible: null,
  },
]

test('mantiene visible pero deshabilitado al cliente sin membresía', async ({ page }) => {
  await iniciarSesion(page)

  await page.route('**/api/v1/tarjetas-rfid/modalidad', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ tipoEstacionamiento: 'PUBLICO' }),
    }),
  )
  await page.route('**/api/v1/tarjetas-rfid?*', async (route) => {
    if (new URL(route.request().url()).pathname !== '/api/v1/tarjetas-rfid') {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], pagina: 1, tamano: 10, total: 0, totalPaginas: 0 }),
    })
  })
  await page.route('**/api/v1/rfid-1/estado-conexion', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ estado: 'CONECTADO', actualizadoEn: null }),
    }),
  )
  await page.route('**/api/v1/rfid-1/capturas/activa', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: 'null' }),
  )
  await page.route('**/api/v1/tarjetas-rfid/personas?*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(candidatos),
    }),
  )
  await page.route('**/api/v1/eventos/administracion*', (route) => route.abort('failed'))

  await page.goto(url('/admin/tarjetas-rfid'))
  const abrirAsociacion = page.getByRole('button', { name: 'Asociar tarjeta', exact: true })
  await expect(abrirAsociacion).toBeEnabled()
  await abrirAsociacion.click()

  const dialogo = page.getByRole('dialog', { name: 'Asociar tarjeta' })
  const busqueda = dialogo.getByRole('combobox', { name: 'Buscar' })
  await busqueda.fill('Cliente')

  const sinMembresia = dialogo.getByRole('option', { name: /Cliente sin membresía/ })
  const conMembresia = dialogo.getByRole('option', { name: /Cliente con membresía/ })
  await expect(sinMembresia).toBeVisible()
  await expect(sinMembresia).toBeDisabled()
  await expect(sinMembresia).toContainText('Sin membresía; no se puede asociar una tarjeta.')
  await expect(conMembresia).toBeVisible()
  await expect(conMembresia).toBeEnabled()

  await busqueda.press('Enter')
  await sinMembresia.dispatchEvent('click')
  await expect(dialogo.getByRole('region', { name: 'Persona seleccionada' })).toHaveCount(0)
  await expect(dialogo.getByRole('button', { name: 'Siguiente', exact: true })).toBeDisabled()

  await busqueda.press('ArrowDown')
  await busqueda.press('Enter')
  await expect(dialogo.getByRole('region', { name: 'Persona seleccionada' })).toContainText(
    'Cliente con membresía',
  )
  await expect(dialogo.getByRole('button', { name: 'Siguiente', exact: true })).toBeEnabled()
})
