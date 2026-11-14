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
  const candidato = dialogo.getByRole('option', { name: /CLI-\d{4,}/ }).first()
  await expect(candidato).toBeEnabled()
  await candidato.click()
  await dialogo.getByRole('button', { name: 'Siguiente', exact: true }).click()
  await expect(dialogo.getByText('Lee la tarjeta', { exact: true })).toBeVisible()
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
  await expect(dialogo.getByText('Revisa la tarjeta', { exact: true })).toBeVisible()

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
  const erroresConsola: string[] = []
  const solicitudesFallidas: string[] = []
  page.on('console', (mensaje) => {
    if (mensaje.type() === 'error') erroresConsola.push(mensaje.text())
  })
  page.on('requestfailed', (solicitud) => {
    if (/\/api\/v1\/tarjetas-rfid\/\d+/.test(new URL(solicitud.url()).pathname)) {
      solicitudesFallidas.push(solicitud.url())
    }
  })
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
  const candidatoOcupado = dialogoOcupado.getByRole('option', { name: /CLI-\d{4,}/ }).first()
  await expect(candidatoOcupado).toBeDisabled()
  await page.keyboard.press('Escape')
  await expect(dialogoOcupado).toBeVisible()
  await expect(dialogoOcupado.getByRole('option')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(dialogoOcupado).toBeHidden()

  const filtro = page.getByLabel('Estado', { exact: true })
  await expect(filtro).toHaveValue('TODAS')
  await expect(filtro.locator('option')).toHaveText(['Todos', 'Activas', 'Inactivas'])
  await filtro.selectOption('ACTIVA')
  const botonDetalle = page.getByRole('button', { name: /^Ver detalles de / }).first()
  await botonDetalle.click()
  const detalle = page.getByRole('dialog', { name: 'Detalles de tarjeta' })
  await expect
    .poll(async () => (await detalle.innerText()).toUpperCase().includes(tarjetaOriginal.uid), {
      timeout: 15_000,
    })
    .toBe(true)
  await page.setViewportSize({ width: 390, height: 844 })
  const cajaMovil = await detalle.boundingBox()
  expect(cajaMovil).not.toBeNull()
  if (!cajaMovil) throw new Error('El diálogo no tiene dimensiones en el viewport móvil.')
  expect(cajaMovil.x).toBeGreaterThanOrEqual(0)
  expect(cajaMovil.x + cajaMovil.width).toBeLessThanOrEqual(390)
  await page.setViewportSize({ width: 1280, height: 900 })

  await page.keyboard.press('Escape')
  await expect(detalle).toBeHidden()
  await expect(botonDetalle).toBeFocused()
  await botonDetalle.click()
  await expect(detalle).toBeVisible()
  await expect(detalle.getByText(tarjetaOriginal.uid, { exact: true })).toBeVisible()

  const textoDetalle = (await detalle.innerText()).toUpperCase()
  expect(
    textoDetalle.includes(tarjetaOriginal.uid),
    'los detalles muestran la UID de la tarjeta activa',
  ).toBe(true)
  for (const etiqueta of ['UID', 'Persona asociada', 'Fecha de asociación']) {
    await expect(detalle.getByText(etiqueta, { exact: true })).toBeVisible()
  }
  await expect(detalle.getByText('Activa', { exact: true })).toBeVisible()
  await expect(detalle.getByText('Cliente', { exact: true })).toBeVisible()
  await expect(detalle.getByText(tarjetaOriginal.codigoPersona, { exact: true })).toBeVisible()
  await detalle.getByRole('button', { name: 'Cancelar tarjeta', exact: true }).click()
  await expect(
    detalle.getByRole('heading', { name: '¿Cancelar esta tarjeta?', exact: true }),
  ).toBeVisible()
  await expect(
    detalle.getByText(
      /La cancelación es permanente.*No podrás reactivar ni reasignar esta tarjeta/,
    ),
  ).toBeVisible()
  await detalle.getByRole('button', { name: 'Volver', exact: true }).click()
  await expect(
    detalle.getByRole('heading', { name: '¿Cancelar esta tarjeta?', exact: true }),
  ).toBeHidden()
  const botonCancelarTarjeta = detalle.getByRole('button', {
    name: 'Cancelar tarjeta',
    exact: true,
  })
  await expect(botonCancelarTarjeta).toBeFocused()
  await botonCancelarTarjeta.click()

  const rutaCancelacion = webUrl(
    `/api/v1/tarjetas-rfid/${tarjetaOriginal.asociacionId}/cancelacion`,
  )
  await page.route(rutaCancelacion, async (ruta) => {
    await ruta.fulfill({
      status: 503,
      contentType: 'application/json',
      body: '{"codigo":"SERVICIO_NO_DISPONIBLE","mensaje":"Intenta de nuevo."}',
    })
  })
  const rechazoCancelacion = page.waitForResponse(
    (elemento) =>
      new URL(elemento.url()).pathname ===
        `/api/v1/tarjetas-rfid/${tarjetaOriginal.asociacionId}/cancelacion` &&
      elemento.request().method() === 'POST',
  )
  await detalle.getByRole('button', { name: 'Confirmar cancelación', exact: true }).click()
  expect((await rechazoCancelacion).status()).toBe(503)
  await expect(detalle.getByRole('alert')).toContainText('No sabemos si la solicitud se completó.')
  await expect(detalle.getByText('Activa', { exact: true })).toBeVisible()
  await page.unroute(rutaCancelacion)

  let solicitudesCancelacion = 0
  let liberarRespuesta: (() => void) | undefined
  const compuertaCancelacion = new Promise<void>((resolver) => {
    liberarRespuesta = resolver
  })
  await page.route(rutaCancelacion, async (ruta) => {
    solicitudesCancelacion += 1
    await compuertaCancelacion
    await ruta.continue()
  })
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
  const confirmacion = detalle.getByRole('button', {
    name: 'Confirmar cancelación',
    exact: true,
  })
  await expect(confirmacion).toBeDisabled()
  await confirmacion.dispatchEvent('click')
  expect(solicitudesCancelacion).toBe(1)
  liberarRespuesta?.()
  const [respuesta, solicitud] = await Promise.all([respuestaCancelacion, solicitudCancelacion])
  expect(respuesta.status()).toBe(200)
  const encabezadosCancelacion = await solicitud.allHeaders()
  expect(Boolean(encabezadosCancelacion['x-csrf-token'])).toBe(true)
  await expect(detalle.getByText('Cancelada', { exact: true })).toBeVisible()
  await expect(
    detalle.getByText('Tarjeta cancelada permanentemente.', { exact: true }),
  ).toBeVisible()
  await expect(detalle.getByRole('button', { name: 'Cancelar tarjeta', exact: true })).toHaveCount(
    0,
  )
  await page.unroute(rutaCancelacion)

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
    .getByRole('button', { name: /^Ver detalles de / })
    .first()
    .click()
  const detalleHistorico = page.getByRole('dialog', { name: 'Detalles de tarjeta' })
  await expect(detalleHistorico.getByText('Cancelada', { exact: true })).toBeVisible()
  await expect(detalleHistorico.getByText('Fecha de cancelación', { exact: true })).toHaveCount(0)
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
  await expect(dialogoDisponible.getByText('Revisa la tarjeta', { exact: true })).toBeVisible()

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
  const erroresEsperados503 = erroresConsola.filter((error) => /\b503\b/.test(error))
  expect(erroresEsperados503.length).toBeLessThanOrEqual(1)
  expect(erroresConsola.filter((error) => !/\b503\b/.test(error))).toEqual([])
  expect(solicitudesFallidas).toEqual([])
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
    .getByRole('button', { name: /^Ver detalles de / })
    .first()
    .click()
  const detalle = page.getByRole('dialog', { name: 'Detalles de tarjeta' })
  await expect(detalle.getByRole('button', { name: 'Cancelar tarjeta', exact: true })).toBeVisible()
  await detalle.getByRole('button', { name: 'Cancelar tarjeta', exact: true }).click()
  await expect(detalle.getByText('¿Cancelar esta tarjeta?', { exact: true })).toBeVisible()

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
