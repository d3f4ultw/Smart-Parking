import { expect, test, type Locator, type Page } from '@playwright/test'
import {
  consultarTarjetas,
  crearUidSintetico,
  enviarLecturaSintetica,
  estadoEventosRfid,
  instrumentarEventosRfid,
  iniciarSesion,
  prepararCapturaSintetica,
  webUrl,
} from './soporte'

const MENSAJE_RECHAZO = 'Esta tarjeta ya se utilizó. Presenta otra; el lector sigue listo.'
const LIMITE_RECHAZO_MS = 1_500

interface InicioCaptura {
  capturaId: string
  estado: string
  expiraEn: string
}

async function elegirPersona(page: Page, tipo: 'CLIENTE' | 'EMPLEADO'): Promise<Locator> {
  await page.getByRole('button', { name: 'Asociar tarjeta', exact: true }).click()
  const dialogo = page.getByRole('dialog', { name: 'Asociar tarjeta' })
  if (tipo === 'EMPLEADO') await dialogo.getByRole('button', { name: 'EMPLEADO' }).click()
  const busqueda = tipo === 'CLIENTE' ? 'Stage 3' : 'Stage3'
  await dialogo.getByRole('combobox', { name: 'Buscar' }).fill(busqueda)
  const candidato = tipo === 'CLIENTE'
    ? dialogo.getByRole('option', { name: /^CLI-\d{4,} · / }).first()
    : dialogo.getByRole('option', { name: /Empleado Stage3 Sintetico/ }).first()
  await expect(candidato).toBeVisible()
  await candidato.click()
  await dialogo.getByRole('button', { name: 'Siguiente', exact: true }).click()
  await expect(dialogo.getByText('2. Leer tarjeta', { exact: true })).toBeVisible()
  return dialogo
}

async function iniciarCaptura(page: Page, dialogo: Locator): Promise<InicioCaptura> {
  const respuesta = page.waitForResponse((elemento) =>
    new URL(elemento.url()).pathname === '/api/v1/rfid-1/capturas' &&
    elemento.request().method() === 'POST',
  )
  await dialogo.getByRole('button', { name: 'Iniciar lectura', exact: true }).click()
  const inicio = await respuesta
  expect(inicio.status()).toBe(201)
  return (await inicio.json()) as InicioCaptura
}

test('rechazo RFID1 permite otra tarjeta en la misma captura y se actualiza en vivo', async ({ page }) => {
  test.setTimeout(90_000)
  await instrumentarEventosRfid(page)
  await iniciarSesion(page)
  await page.goto(webUrl('/admin/tarjetas-rfid'))

  const dialogoCliente = await elegirPersona(page, 'CLIENTE')
  const inicioCliente = await iniciarCaptura(page, dialogoCliente)
  const tarjetaAsociada = crearUidSintetico()
  const previaCliente = await enviarLecturaSintetica(inicioCliente.capturaId, tarjetaAsociada)
  expect(previaCliente.estadoHttp).toBe(200)
  expect(previaCliente.resultado?.estado).toBe('VISTA_PREVIA')
  await expect(dialogoCliente.getByText('3. Confirmar asociación', { exact: true })).toBeVisible()
  const confirmar = page.waitForResponse((elemento) =>
    new URL(elemento.url()).pathname === `/api/v1/rfid-1/capturas/${inicioCliente.capturaId}/confirmacion` &&
    elemento.request().method() === 'POST',
  )
  await dialogoCliente.getByRole('button', { name: 'Confirmar asociación' }).click()
  expect((await confirmar).status()).toBe(200)
  await expect(dialogoCliente).toBeHidden()

  const dialogoEmpleado = await elegirPersona(page, 'EMPLEADO')
  const inicioEmpleado = await iniciarCaptura(page, dialogoEmpleado)
  await prepararCapturaSintetica(inicioEmpleado.capturaId)
  await expect(
    dialogoEmpleado.getByText('Presenta la tarjeta al lector para continuar.', { exact: true }),
  ).toBeVisible()
  const eventosAntes = await estadoEventosRfid(page)
  const inicioRechazo = performance.now()
  const rechazo = await enviarLecturaSintetica(
    inicioEmpleado.capturaId,
    tarjetaAsociada,
    false,
  )
  const respuestaApiMs = performance.now() - inicioRechazo
  expect(rechazo.estadoHttp).toBe(409)
  const desdeRespuestaApi = performance.now()
  await expect(dialogoEmpleado.getByText(MENSAJE_RECHAZO, { exact: true })).toBeVisible({
    timeout: LIMITE_RECHAZO_MS,
  })
  const actualizacionWebMs = performance.now() - desdeRespuestaApi
  const eventosDespues = await estadoEventosRfid(page)
  expect(eventosDespues.tipos.length).toBeGreaterThan(eventosAntes.tipos.length)
  console.log(
    `RFID1_TIMING api_response_ms=${Math.round(respuestaApiMs)} ui_after_response_ms=${Math.round(actualizacionWebMs)} sse_delta=${eventosDespues.tipos.length - eventosAntes.tipos.length}`,
  )

  const tarjetaDisponible = await enviarLecturaSintetica(inicioEmpleado.capturaId, undefined, false)
  expect(tarjetaDisponible.estadoHttp).toBe(200)
  expect(tarjetaDisponible.resultado?.estado).toBe('VISTA_PREVIA')
  await expect(dialogoEmpleado.getByText('3. Confirmar asociación', { exact: true })).toBeVisible()
  await expect(dialogoEmpleado.getByRole('button', { name: 'Confirmar asociación' })).toHaveCount(1)

  const cancelacion = page.waitForResponse((elemento) =>
    new URL(elemento.url()).pathname === `/api/v1/rfid-1/capturas/${inicioEmpleado.capturaId}` &&
    elemento.request().method() === 'DELETE',
  )
  await dialogoEmpleado.getByRole('button', { name: 'Cancelar captura' }).click()
  expect((await cancelacion).status()).toBe(204)

  const tarjetasCliente = await consultarTarjetas(page.context().request, 'CLIENTE')
  const tarjetasEmpleado = await consultarTarjetas(page.context().request, 'EMPLEADO')
  expect(tarjetasCliente.items.some((tarjeta) => tarjeta.uid === tarjetaAsociada && tarjeta.estado === 'ACTIVA')).toBe(true)
  expect(tarjetasEmpleado.total).toBe(0)
})
