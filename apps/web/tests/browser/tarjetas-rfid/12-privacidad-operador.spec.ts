import { expect, test, type Page } from '@playwright/test'
import { baseURL } from '../sesion'

const correoOperador = process.env.TEST_OPERATOR_EMAIL
const contrasenaOperador = process.env.TEST_OPERATOR_PASSWORD

const tarjeta = {
  asociacionId: 987,
  uid: null,
  tipoEntidad: 'CLIENTE',
  codigoPersona: 'CLI-00987',
  nombreCompleto: 'Persona Sintética RFID',
  estado: 'ACTIVA',
  asociadaEn: '2026-11-05T09:02:38Z',
  canceladaEn: null,
}

async function iniciarSesionOperador(page: Page) {
  if (!/^[^@]+@[^@]+\.invalid$/i.test(correoOperador ?? '')) {
    throw new Error('La prueba requiere un OPERADOR sintético con dominio .invalid.')
  }

  let intentoGetConCredenciales = false
  await page.route('**/panel?*', async (ruta) => {
    const url = new URL(ruta.request().url())
    if (url.searchParams.has('correo') || url.searchParams.has('contrasena')) {
      intentoGetConCredenciales = true
      await ruta.abort('aborted')
      return
    }
    await ruta.continue()
  })

  await page.goto(new URL('/panel', baseURL).toString())
  await page.waitForLoadState('networkidle')
  await page.getByLabel('Correo electrónico').fill(correoOperador!)
  await page.getByRole('textbox', { name: 'Contraseña' }).fill(contrasenaOperador!)
  await page.getByRole('button', { name: 'Iniciar sesión' }).click({ noWaitAfter: true })
  await expect
    .poll(() => new URL(page.url()).pathname, { timeout: 15_000 })
    .toBe('/operador/monitoreo')
  expect(intentoGetConCredenciales).toBe(false)
}

async function responderJson(page: Page) {
  await page.route(
    (destino) =>
      destino.pathname === '/api/v1/tarjetas-rfid' ||
      destino.pathname.startsWith('/api/v1/tarjetas-rfid/'),
    async (intercepcion) => {
      const destino = new URL(intercepcion.request().url())
      if (intercepcion.request().method() !== 'GET') {
        return intercepcion.abort('blockedbyclient')
      }

      if (destino.pathname === '/api/v1/tarjetas-rfid') {
        return intercepcion.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            items: [tarjeta],
            pagina: 1,
            tamano: 10,
            total: 1,
            totalPaginas: 1,
          }),
        })
      }
      if (destino.pathname === `/api/v1/tarjetas-rfid/${tarjeta.asociacionId}`) {
        return intercepcion.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(tarjeta),
        })
      }
      if (destino.pathname === '/api/v1/tarjetas-rfid/modalidad') {
        return intercepcion.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ tipoEstacionamiento: 'PUBLICO' }),
        })
      }
      return intercepcion.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
    },
  )
}

test('OPERADOR no ve UID en el directorio ni en el detalle de una tarjeta', async ({ page }) => {
  test.skip(
    !correoOperador || !contrasenaOperador,
    'Esta prueba requiere una cuenta OPERADOR sintética del entorno desechable.',
  )
  await iniciarSesionOperador(page)
  await responderJson(page)
  await page.route(
    (destino) => destino.pathname.startsWith('/api/v1/rfid-1/'),
    (intercepcion) => {
      const destino = new URL(intercepcion.request().url())
      if (destino.pathname === '/api/v1/rfid-1/estado-conexion') {
        return intercepcion.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ estado: 'CONECTADO', actualizadoEn: '2026-11-05T09:02:38Z' }),
        })
      }
      if (destino.pathname === '/api/v1/rfid-1/capturas/activa') {
        return intercepcion.fulfill({ status: 200, contentType: 'application/json', body: 'null' })
      }
      return intercepcion.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
    },
  )

  await page.goto(new URL('/operador/tarjetas', baseURL).toString(), {
    waitUntil: 'domcontentloaded',
  })
  const directorio = page.locator('section[aria-labelledby="titulo-directorio-rfid"]')
  await expect(
    directorio.getByRole('searchbox', { name: 'Buscar por nombre o código' }),
  ).toBeVisible()
  await expect(directorio.getByRole('columnheader', { name: 'UID', exact: true })).toHaveCount(0)

  const fila = directorio.locator('tbody tr').filter({ hasText: 'Persona Sintética RFID' })
  await expect(fila).toBeVisible()
  await expect(fila.locator('td')).toHaveCount(4)
  await expect(fila.getByText('null', { exact: true })).toHaveCount(0)
  await fila.getByRole('button', { name: 'Ver detalles de Persona Sintética RFID' }).click()

  const detalle = page.getByRole('dialog', { name: 'Detalles de tarjeta' })
  await expect(detalle).toBeVisible()
  await expect(detalle.getByText('UID', { exact: true })).toHaveCount(0)
  await expect(detalle.getByText('null', { exact: true })).toHaveCount(0)
  await detalle.getByRole('button', { name: 'Cancelar tarjeta' }).click()
  await expect(detalle.getByText(/conservará el historial de esta asociación\./)).toBeVisible()
  await expect(detalle.getByText('UID', { exact: true })).toHaveCount(0)
})
