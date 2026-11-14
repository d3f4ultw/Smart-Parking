import { expect, test, type Page } from '@playwright/test'
import {
  cancelarCapturaActiva,
  estadoEventosRfid,
  instrumentarEventosRfid,
  enviarLecturaSintetica,
  iniciarSesion,
  webUrl,
} from './soporte'

async function prepararCliente(page: Page): Promise<string> {
  await page.getByRole('button', { name: 'Asociar tarjeta', exact: true }).click()
  const dialogo = page.getByRole('dialog', { name: 'Asociar tarjeta' })
  await dialogo.getByRole('button', { name: 'CLIENTE', exact: true }).click()
  await dialogo.getByRole('combobox', { name: 'Buscar' }).fill('Stage 2')
  const candidato = dialogo.getByRole('option', { name: /CLI-\d{4,}/ }).first()
  await expect(candidato).toBeEnabled()
  await candidato.click()
  await dialogo.getByRole('button', { name: 'Siguiente', exact: true }).click()
  await expect(dialogo.getByText('Lee la tarjeta', { exact: true })).toBeVisible()

  const inicio = page.waitForResponse(
    (respuesta) =>
      new URL(respuesta.url()).pathname === '/api/v1/rfid-1/capturas' &&
      respuesta.request().method() === 'POST',
  )
  await dialogo.getByRole('button', { name: 'Iniciar lectura', exact: true }).click()
  const respuestaInicio = await inicio
  expect(respuestaInicio.status()).toBe(201)
  return ((await respuestaInicio.json()) as { capturaId: string }).capturaId
}

test.afterEach(async ({ page }) => {
  await cancelarCapturaActiva(page.context().request)
})

test('sin eventos SSE, reconcilia estado a ritmo controlado y recupera la vista previa', async ({
  page,
}) => {
  await instrumentarEventosRfid(page)
  await page.route('**/api/v1/eventos/administracion**', async (ruta) => {
    await ruta.abort('failed')
  })
  await iniciarSesion(page)
  await page.goto(webUrl('/admin/tarjetas-rfid'))

  const lecturasEstado: number[] = []
  page.on('request', (solicitud) => {
    if (solicitud.method() !== 'GET') return
    const ruta = new URL(solicitud.url()).pathname
    if (
      ruta === '/api/v1/rfid-1/capturas/activa' ||
      /^\/api\/v1\/rfid-1\/capturas\/[0-9a-f-]+$/i.test(ruta)
    ) {
      lecturasEstado.push(Date.now())
    }
  })

  const capturaId = await prepararCliente(page)
  const dialogo = page.getByRole('dialog', { name: 'Asociar tarjeta' })
  await expect(dialogo.getByText('Estado de la lectura', { exact: true })).toBeVisible()
  await expect(dialogo.getByText(/cada 8 segundos/i)).toHaveCount(0)
  const previa = page.waitForResponse(
    (respuesta) =>
      new URL(respuesta.url()).pathname === `/api/v1/rfid-1/capturas/${capturaId}/vista-previa` &&
      respuesta.status() === 200,
    { timeout: 20_000 },
  )
  const lectura = await enviarLecturaSintetica(capturaId)
  expect(lectura.estadoHttp).toBe(200)
  expect((await previa).status()).toBe(200)
  await expect(dialogo.getByText('Revisa la tarjeta', { exact: true })).toBeVisible()

  await expect.poll(() => lecturasEstado.length, { timeout: 20_000 }).toBeGreaterThan(1)
  const intervalos = lecturasEstado
    .slice(1)
    .map((momento, indice) => momento - lecturasEstado[indice])
  expect(
    intervalos.some((intervalo) => intervalo >= 7_000 && intervalo <= 15_000),
    'la reconciliación observada respeta el intervalo aproximado de 8 segundos',
  ).toBe(true)
  expect(lecturasEstado.length).toBeLessThanOrEqual(4)
  const eventos = await estadoEventosRfid(page)
  expect(eventos.maximoActivos).toBe(1)
  expect(eventos.tipos.length).toBe(0)
})
