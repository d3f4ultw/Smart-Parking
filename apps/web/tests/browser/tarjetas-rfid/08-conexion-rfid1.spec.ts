import { expect, test } from '@playwright/test'
import { baseURL, iniciarSesion } from './soporte'

const url = (ruta: string) => new URL(ruta, baseURL).toString()

test('RFID1 refleja el PONG del bridge y distingue conexión de lectura activa', async ({
  page,
}) => {
  await iniciarSesion(page)
  await page.clock.install()

  let liberarPrimeraConsulta!: () => void
  const primeraConsultaPendiente = new Promise<void>((resolve) => {
    liberarPrimeraConsulta = resolve
  })
  const estados = ['DESCONOCIDO', 'CONECTADO', 'DESCONECTADO', 'HTTP_403', 'CONECTADO'] as const
  let consultas = 0

  await page.route('**/api/v1/panel', (ruta) =>
    ruta.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ estacionamiento: { tipo: 'MIXTO' } }),
    }),
  )
  await page.route('**/api/v1/tarjetas-rfid?*', async (ruta) => {
    const destino = new URL(ruta.request().url())
    if (destino.pathname !== '/api/v1/tarjetas-rfid') return ruta.continue()
    await ruta.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], pagina: 1, tamano: 10, total: 0, totalPaginas: 0 }),
    })
  })
  await page.route('**/api/v1/rfid-1/estado-conexion', async (ruta) => {
    const indice = consultas++
    if (indice === 0) await primeraConsultaPendiente
    const estado = estados[Math.min(indice, estados.length - 1)]
    if (estado === 'HTTP_403') {
      await ruta.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ codigo: 'PERMISO_INSUFICIENTE' }),
      })
      return
    }
    await ruta.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        estado,
        actualizadoEn: estado === 'DESCONOCIDO' ? null : `2026-10-29T12:0${indice}:00Z`,
      }),
    })
  })

  const primeraPeticion = page.waitForRequest(
    (solicitud) => new URL(solicitud.url()).pathname === '/api/v1/rfid-1/estado-conexion',
  )
  await page.goto(url('/admin/tarjetas-rfid'))
  const indicador = page.getByRole('status', {
    name: /Estado de conexión del ESP32 RFID 1 según el último PONG conocido/,
  })
  await primeraPeticion
  await expect(indicador).toContainText('Comprobando')
  await expect(indicador).toHaveAttribute('aria-live', 'polite')
  liberarPrimeraConsulta()
  await expect(indicador).toContainText('Esperando señal')
  await expect(indicador).toHaveAttribute(
    'aria-label',
    /último PONG conocido: Esperando señal\. No indica una lectura activa\./,
  )

  const segundaPeticion = page.waitForRequest(
    (solicitud) => new URL(solicitud.url()).pathname === '/api/v1/rfid-1/estado-conexion',
  )
  await page.clock.fastForward(5000)
  await segundaPeticion
  await expect(indicador).toContainText('Conectado')

  const terceraPeticion = page.waitForRequest(
    (solicitud) => new URL(solicitud.url()).pathname === '/api/v1/rfid-1/estado-conexion',
  )
  await page.clock.fastForward(5000)
  await terceraPeticion
  await expect(indicador).toContainText('Sin conexión')

  const cuartaPeticion = page.waitForRequest(
    (solicitud) => new URL(solicitud.url()).pathname === '/api/v1/rfid-1/estado-conexion',
  )
  await page.clock.fastForward(5000)
  await cuartaPeticion
  await expect(indicador).toContainText('No se pudo verificar')
  await expect(indicador).not.toContainText('Sin conexión')

  const quintaPeticion = page.waitForRequest(
    (solicitud) => new URL(solicitud.url()).pathname === '/api/v1/rfid-1/estado-conexion',
  )
  await page.clock.fastForward(5000)
  await quintaPeticion
  await expect(indicador).toContainText('Conectado')
  expect(consultas).toBe(5)
})
