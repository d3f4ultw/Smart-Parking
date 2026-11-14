import { expect, test, type Locator, type Page } from '@playwright/test'
import {
  cancelarCapturaActiva,
  consultarTarjetas,
  enviarLecturaSintetica,
  iniciarSesion,
  webUrl,
} from './soporte'

async function seleccionarCliente(page: Page): Promise<Locator> {
  await page.getByRole('button', { name: 'Asociar tarjeta', exact: true }).click()
  const dialogo = page.getByRole('dialog', { name: 'Asociar tarjeta' })
  await dialogo.getByRole('button', { name: 'CLIENTE', exact: true }).click()
  await dialogo.getByRole('combobox', { name: 'Buscar' }).fill('Stage 2')
  const candidato = dialogo.getByRole('option', { name: /^CLI-\d{4,} · / }).first()
  await expect(candidato).toBeEnabled()
  await candidato.click()
  await dialogo.getByRole('button', { name: 'Siguiente', exact: true }).click()
  await expect(dialogo.getByText('2. Leer tarjeta', { exact: true })).toBeVisible()
  return dialogo
}

async function iniciarCaptura(page: Page, dialogo: Locator): Promise<string> {
  const respuesta = page.waitForResponse(
    (elemento) =>
      new URL(elemento.url()).pathname === '/api/v1/rfid-1/capturas' &&
      elemento.request().method() === 'POST',
  )
  await dialogo.getByRole('button', { name: 'Iniciar lectura', exact: true }).click()
  const inicio = await respuesta
  expect(inicio.status()).toBe(201)
  const cuerpo = (await inicio.json()) as { capturaId: string }
  return cuerpo.capturaId
}

async function asociarCliente(page: Page, dialogo: Locator): Promise<void> {
  const capturaId = await iniciarCaptura(page, dialogo)
  const respuestaPrevia = page.waitForResponse(
    (elemento) =>
      new URL(elemento.url()).pathname === `/api/v1/rfid-1/capturas/${capturaId}/vista-previa`,
  )
  const lectura = await enviarLecturaSintetica(capturaId)
  expect(lectura.estadoHttp).toBe(200)
  expect((await respuestaPrevia).status()).toBe(200)
  await expect(dialogo.getByText('3. Confirmar asociación', { exact: true })).toBeVisible()

  const confirmacion = page.waitForResponse(
    (elemento) =>
      new URL(elemento.url()).pathname === `/api/v1/rfid-1/capturas/${capturaId}/confirmacion` &&
      elemento.request().method() === 'POST',
  )
  await dialogo.getByRole('button', { name: 'Confirmar asociación', exact: true }).click()
  const respuesta = await confirmacion
  expect(respuesta.status()).toBe(200)
  await expect(dialogo).toBeHidden()
}

async function cancelarActivasPrevias(page: Page): Promise<void> {
  const activas = await consultarTarjetas(page.context().request, 'CLIENTE', 'ACTIVA')
  if (activas.total === 0) return
  const csrfRespuesta = await page.context().request.get(webUrl('/api/v1/csrf'))
  expect(csrfRespuesta.status()).toBe(200)
  const csrf = (await csrfRespuesta.json()) as { token: string }
  for (const tarjeta of activas.items) {
    const respuesta = await page
      .context()
      .request.post(webUrl(`/api/v1/tarjetas-rfid/${tarjeta.asociacionId}/cancelacion`), {
        headers: { 'X-CSRF-TOKEN': csrf.token },
      })
    expect(respuesta.status()).toBe(200)
  }
}

test.afterEach(async ({ page }) => {
  await cancelarCapturaActiva(page.context().request)
})

test('el historial conserva cancelaciones permanentes y libera nueva elegibilidad', async ({
  page,
}) => {
  await iniciarSesion(page)
  await page.goto(webUrl('/admin/tarjetas-rfid'))
  await cancelarActivasPrevias(page)
  expect((await consultarTarjetas(page.context().request, 'CLIENTE', 'ACTIVA')).total).toBe(0)

  const primerDialogo = await seleccionarCliente(page)
  await asociarCliente(page, primerDialogo)

  const activas = await consultarTarjetas(page.context().request, 'CLIENTE', 'ACTIVA')
  expect(activas.total).toBe(1)
  const tarjetaOriginal = activas.items[0]
  expect(Boolean(tarjetaOriginal)).toBe(true)
  if (!tarjetaOriginal) throw new Error('No se encontró la tarjeta sintética recién asociada.')
  const detalleHttp = await page
    .context()
    .request.get(webUrl(`/api/v1/tarjetas-rfid/${tarjetaOriginal.asociacionId}`))
  expect(detalleHttp.status()).toBe(200)
  const encabezadosDetalle = detalleHttp.headers()
  expect(encabezadosDetalle['cache-control']?.toLowerCase()).toContain('no-store')
  expect(encabezadosDetalle.vary?.toLowerCase()).toContain('cookie')
  const detalleTarjeta = (await detalleHttp.json()) as { uid?: string }
  expect(
    detalleTarjeta.uid === tarjetaOriginal.uid,
    'la consulta de detalle conserva la tarjeta correcta',
  ).toBe(true)

  const selectorOcupado = page.getByRole('button', { name: 'Asociar tarjeta', exact: true })
  await selectorOcupado.click()
  const dialogoOcupado = page.getByRole('dialog', { name: 'Asociar tarjeta' })
  await dialogoOcupado.getByRole('button', { name: 'CLIENTE', exact: true }).click()
  await dialogoOcupado.getByRole('combobox', { name: 'Buscar' }).fill('Stage 2')
  const candidatoOcupado = dialogoOcupado.getByRole('option', { name: /^CLI-\d{4,} · / }).first()
  await expect(candidatoOcupado).toBeDisabled()
  await page.keyboard.press('Escape')
  await expect(dialogoOcupado).toBeHidden()

  const filtro = page.getByRole('combobox', { name: 'Estado de tarjeta' })
  await expect(filtro).toHaveValue('TODAS')
  await expect(filtro.locator('option')).toHaveText(['TODAS', 'ACTIVA', 'CANCELADA'])
  await filtro.selectOption('ACTIVA')
  await page
    .getByRole('button', { name: /^Detalles/ })
    .first()
    .click()
  const detalle = page.getByRole('dialog', { name: 'Tarjeta RFID' })
  await expect
    .poll(async () => (await detalle.innerText()).toUpperCase().includes(tarjetaOriginal.uid), {
      timeout: 15_000,
    })
    .toBe(true)
  const textoDetalle = (await detalle.innerText()).toUpperCase()
  expect(
    textoDetalle.includes(tarjetaOriginal.uid),
    'los detalles muestran la UID de la tarjeta activa',
  ).toBe(true)
  for (const etiqueta of ['UID', 'Persona', 'Tipo', 'Fecha de asociación', 'Estado']) {
    await expect(detalle.getByText(etiqueta, { exact: true })).toBeVisible()
  }
  await expect(detalle.getByText('ACTIVA', { exact: true })).toBeVisible()
  await detalle.getByRole('button', { name: 'Cancelar tarjeta', exact: true }).click()
  await expect(
    detalle.getByRole('heading', { name: 'Confirmar cancelación permanente', exact: true }),
  ).toBeVisible()

  const respuestaCancelacion = page.waitForResponse(
    (elemento) =>
      new URL(elemento.url()).pathname ===
        `/api/v1/tarjetas-rfid/${tarjetaOriginal.asociacionId}/cancelacion` &&
      elemento.request().method() === 'POST',
  )
  const solicitudCancelacion = page.waitForRequest(
    (elemento) =>
      new URL(elemento.url()).pathname ===
        `/api/v1/tarjetas-rfid/${tarjetaOriginal.asociacionId}/cancelacion` &&
      elemento.method() === 'POST',
  )
  await detalle.getByRole('button', { name: 'Confirmar cancelación', exact: true }).click()
  const [respuesta, peticion] = await Promise.all([respuestaCancelacion, solicitudCancelacion])
  expect(respuesta.status()).toBe(200)
  const encabezadosCancelacion = await peticion.allHeaders()
  expect(Boolean(encabezadosCancelacion['x-csrf-token'])).toBe(true)
  await expect(detalle.getByText('CANCELADA', { exact: true })).toBeVisible()
  await expect(detalle.getByRole('button', { name: 'Cancelar tarjeta', exact: true })).toHaveCount(
    0,
  )

  const canceladas = await consultarTarjetas(page.context().request, 'CLIENTE', 'CANCELADA')
  const tarjetaCancelada = canceladas.items.find(
    (tarjeta) => tarjeta.asociacionId === tarjetaOriginal.asociacionId,
  )
  expect(tarjetaCancelada?.estado).toBe('CANCELADA')
  expect(Boolean(tarjetaCancelada?.canceladaEn)).toBe(true)
  expect(
    tarjetaCancelada?.uid === tarjetaOriginal.uid,
    'la cancelación conserva la UID histórica',
  ).toBe(true)
  expect((await consultarTarjetas(page.context().request, 'CLIENTE', 'ACTIVA')).total).toBe(0)

  await page.keyboard.press('Escape')
  await filtro.selectOption('CANCELADA')
  await page
    .getByRole('button', { name: /^Detalles/ })
    .first()
    .click()
  const detalleHistorico = page.getByRole('dialog', { name: 'Tarjeta RFID' })
  await expect(detalleHistorico.getByText('Fecha de cancelación', { exact: true })).toBeVisible()
  await expect(
    detalleHistorico.getByRole('button', { name: 'Cancelar tarjeta', exact: true }),
  ).toHaveCount(0)
  await page.keyboard.press('Escape')

  const dialogoDisponible = await seleccionarCliente(page)
  const capturaNueva = await iniciarCaptura(page, dialogoDisponible)
  const previaNueva = page.waitForResponse(
    (elemento) =>
      new URL(elemento.url()).pathname === `/api/v1/rfid-1/capturas/${capturaNueva}/vista-previa`,
  )
  const lecturaNueva = await enviarLecturaSintetica(capturaNueva)
  expect(lecturaNueva.estadoHttp).toBe(200)
  expect((await previaNueva).status()).toBe(200)
  await expect(
    dialogoDisponible.getByText('3. Confirmar asociación', { exact: true }),
  ).toBeVisible()

  const confirmacionNueva = page.waitForResponse(
    (elemento) =>
      new URL(elemento.url()).pathname === `/api/v1/rfid-1/capturas/${capturaNueva}/confirmacion`,
  )
  await dialogoDisponible.getByRole('button', { name: 'Confirmar asociación', exact: true }).click()
  expect((await confirmacionNueva).status()).toBe(200)

  const historial = await consultarTarjetas(page.context().request, 'CLIENTE')
  expect(historial.total).toBe(canceladas.total + 1)
  expect(historial.items.filter((tarjeta) => tarjeta.estado === 'CANCELADA').length).toBe(
    canceladas.total,
  )
  expect(historial.items.filter((tarjeta) => tarjeta.estado === 'ACTIVA').length).toBe(1)
  const conservaOriginal = historial.items.some(
    (tarjeta) =>
      tarjeta.asociacionId === tarjetaOriginal.asociacionId && tarjeta.uid === tarjetaOriginal.uid,
  )
  expect(conservaOriginal, 'la tarjeta cancelada permanece intacta en el historial').toBe(true)
  await cancelarActivasPrevias(page)
})

test('una sesión expirada al confirmar cancelación vuelve al acceso de propietario', async ({
  page,
}) => {
  await iniciarSesion(page)
  await page.goto(webUrl('/admin/tarjetas-rfid'))
  await cancelarActivasPrevias(page)

  const dialogoAsociacion = await seleccionarCliente(page)
  await asociarCliente(page, dialogoAsociacion)
  const activas = await consultarTarjetas(page.context().request, 'CLIENTE', 'ACTIVA')
  expect(activas.total).toBe(1)
  const tarjeta = activas.items[0]
  expect(Boolean(tarjeta)).toBe(true)
  if (!tarjeta) throw new Error('No se encontró la tarjeta sintética para la regresión de sesión.')

  await page
    .getByRole('button', { name: /^Detalles/ })
    .first()
    .click()
  const detalle = page.getByRole('dialog', { name: 'Tarjeta RFID' })
  await expect(detalle.getByRole('button', { name: 'Cancelar tarjeta', exact: true })).toBeVisible()
  await detalle.getByRole('button', { name: 'Cancelar tarjeta', exact: true }).click()
  await expect(detalle.getByText('Confirmar cancelación permanente', { exact: true })).toBeVisible()

  const rutaCancelacion = webUrl(`/api/v1/tarjetas-rfid/${tarjeta.asociacionId}/cancelacion`)
  try {
    await page.route(rutaCancelacion, async (ruta) => {
      await ruta.fulfill({
        status: 401,
        contentType: 'application/json',
        body: '{"codigo":"SESION_EXPIRADA"}',
      })
    })
    await page.route('**/api/v1/sesion', async (ruta) => {
      if (ruta.request().method() === 'GET') {
        await ruta.fulfill({
          status: 200,
          contentType: 'application/json',
          body: '{"autenticada":false}',
        })
        return
      }
      await ruta.continue()
    })

    const rechazo = page.waitForResponse(
      (respuesta) =>
        new URL(respuesta.url()).pathname ===
          `/api/v1/tarjetas-rfid/${tarjeta.asociacionId}/cancelacion` &&
        respuesta.request().method() === 'POST',
    )
    await detalle.getByRole('button', { name: 'Confirmar cancelación', exact: true }).click()
    expect((await rechazo).status()).toBe(401)
    await expect.poll(() => new URL(page.url()).pathname).toBe('/panel')
    await expect(page.getByRole('button', { name: 'Iniciar sesión', exact: true })).toBeVisible()
  } finally {
    await page.unroute(rutaCancelacion)
    await page.unroute('**/api/v1/sesion')
    await cancelarActivasPrevias(page)
  }
})
