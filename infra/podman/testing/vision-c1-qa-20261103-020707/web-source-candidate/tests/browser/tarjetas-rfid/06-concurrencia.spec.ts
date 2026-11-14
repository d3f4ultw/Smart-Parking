import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import {
  cancelarCapturaActiva,
  consultarTarjetas,
  enviarLecturaSintetica,
  iniciarSesion,
  webUrl,
} from './soporte'

type TipoPersona = 'CLIENTE' | 'EMPLEADO'

interface FlujoCaptura {
  capturaId: string
  dialogo: Locator
}

interface Barrera {
  espera: Promise<void>
  iniciada: Promise<void>
  finalizada: Promise<void>
  fueIniciada: boolean
  comenzar(): void
  terminar(): void
  liberar(): void
}

function crearBarrera(): Barrera {
  let resolverEspera!: () => void
  let resolverInicio!: () => void
  let resolverFin!: () => void
  let fueIniciada = false
  return {
    espera: new Promise<void>((resolver) => {
      resolverEspera = resolver
    }),
    iniciada: new Promise<void>((resolver) => {
      resolverInicio = resolver
    }),
    finalizada: new Promise<void>((resolver) => {
      resolverFin = resolver
    }),
    get fueIniciada() {
      return fueIniciada
    },
    comenzar() {
      fueIniciada = true
      resolverInicio()
    },
    terminar() {
      resolverFin()
    },
    liberar() {
      resolverEspera()
    },
  }
}

async function cancelarActivas(request: APIRequestContext, tipo: TipoPersona): Promise<void> {
  const activas = await consultarTarjetas(request, tipo, 'ACTIVA')
  if (activas.total === 0) return
  const csrfRespuesta = await request.get(webUrl('/api/v1/csrf'))
  expect(csrfRespuesta.status()).toBe(200)
  const csrf = (await csrfRespuesta.json()) as { token: string }
  for (const tarjeta of activas.items) {
    const respuesta = await request.post(
      webUrl(`/api/v1/tarjetas-rfid/${tarjeta.asociacionId}/cancelacion`),
      { headers: { 'X-CSRF-TOKEN': csrf.token } },
    )
    expect(respuesta.status()).toBe(200)
  }
}

async function crearVistaPrevia(page: Page, tipo: TipoPersona): Promise<FlujoCaptura> {
  await page.getByRole('button', { name: 'Asociar tarjeta', exact: true }).click()
  const dialogo = page.getByRole('dialog', { name: 'Asociar tarjeta' })
  if (tipo === 'EMPLEADO') await dialogo.getByRole('button', { name: tipo, exact: true }).click()
  const busqueda = dialogo.getByRole('combobox', { name: 'Buscar' })
  await busqueda.fill('Stage 2')
  const nombreCandidato = tipo === 'CLIENTE' ? /^CLI-\d{4,} · / : /Empleado Stage 2 Sintetico/
  const candidato = dialogo.getByRole('option', { name: nombreCandidato }).first()
  await expect(candidato).toBeEnabled()
  await candidato.click()
  await dialogo.getByRole('button', { name: 'Siguiente', exact: true }).click()
  await expect(dialogo.getByText('2. Leer tarjeta', { exact: true })).toBeVisible()

  const respuestaInicio = page.waitForResponse(
    (respuesta) =>
      new URL(respuesta.url()).pathname === '/api/v1/rfid-1/capturas' &&
      respuesta.request().method() === 'POST',
  )
  await dialogo.getByRole('button', { name: 'Iniciar lectura', exact: true }).click()
  const inicio = await respuestaInicio
  expect(inicio.status()).toBe(201)
  const { capturaId } = (await inicio.json()) as { capturaId: string }

  const respuestaPrevia = page.waitForResponse(
    (respuesta) =>
      new URL(respuesta.url()).pathname === `/api/v1/rfid-1/capturas/${capturaId}/vista-previa` &&
      respuesta.status() === 200,
    { timeout: 20_000 },
  )
  const lectura = await enviarLecturaSintetica(capturaId)
  expect(lectura.estadoHttp).toBe(200)
  expect((await respuestaPrevia).status()).toBe(200)
  await expect(dialogo.getByText('3. Confirmar asociación', { exact: true })).toBeVisible()
  return { capturaId, dialogo }
}

async function asociar(page: Page, tipo: TipoPersona) {
  const flujo = await crearVistaPrevia(page, tipo)
  const confirmacion = page.waitForResponse(
    (respuesta) =>
      new URL(respuesta.url()).pathname ===
        `/api/v1/rfid-1/capturas/${flujo.capturaId}/confirmacion` &&
      respuesta.request().method() === 'POST',
  )
  await flujo.dialogo.getByRole('button', { name: 'Confirmar asociación', exact: true }).click()
  expect((await confirmacion).status()).toBe(200)
  await expect(flujo.dialogo).toBeHidden()
  const activas = await consultarTarjetas(page.context().request, tipo, 'ACTIVA')
  expect(activas.total).toBe(1)
  const tarjeta = activas.items[0]
  if (!tarjeta) throw new Error('No apareció la tarjeta sintética recién asociada.')
  return tarjeta
}

test.afterEach(async ({ page }) => {
  const request = page.context().request
  await cancelarCapturaActiva(request)
  await cancelarActivas(request, 'CLIENTE').catch(() => undefined)
  await cancelarActivas(request, 'EMPLEADO').catch(() => undefined)
})

test('el detalle ignora una respuesta UID tardía al cerrar y cambiar de asociación', async ({
  page,
}) => {
  await iniciarSesion(page)
  await page.goto(webUrl('/admin/tarjetas-rfid'))
  await cancelarCapturaActiva(page.context().request)
  await cancelarActivas(page.context().request, 'CLIENTE')
  await cancelarActivas(page.context().request, 'EMPLEADO')
  const tarjetaCliente = await asociar(page, 'CLIENTE')
  const tarjetaEmpleado = await asociar(page, 'EMPLEADO')

  const barreras = new Map<number, Barrera>([
    [tarjetaCliente.asociacionId, crearBarrera()],
    [tarjetaEmpleado.asociacionId, crearBarrera()],
  ])
  await page.route('**/api/v1/tarjetas-rfid/*', async (ruta) => {
    const coincidencia = new URL(ruta.request().url()).pathname.match(
      /^\/api\/v1\/tarjetas-rfid\/([1-9]\d*)$/,
    )
    if (ruta.request().method() === 'GET' && coincidencia) {
      const barrera = barreras.get(Number(coincidencia[1]))
      if (barrera) {
        barrera.comenzar()
        try {
          await barrera.espera
          const asociacionId = Number(coincidencia[1])
          const tarjeta =
            asociacionId === tarjetaCliente.asociacionId ? tarjetaCliente : tarjetaEmpleado
          await ruta
            .fulfill({
              status: 200,
              contentType: 'application/json',
              body: JSON.stringify(tarjeta),
            })
            .catch(() => undefined)
        } finally {
          barrera.terminar()
        }
        return
      }
    }
    await ruta.continue()
  })

  try {
    const region = page.locator('section[aria-labelledby="titulo-directorio-rfid"]')
    const filtro = page.getByRole('combobox', { name: 'Estado de tarjeta' })
    await filtro.selectOption('ACTIVA')
    await expect(region.getByRole('button', { name: 'Detalles', exact: true })).toHaveCount(1)
    const solicitudCliente = page.waitForRequest(
      (solicitud) =>
        new URL(solicitud.url()).pathname ===
        `/api/v1/tarjetas-rfid/${tarjetaCliente.asociacionId}`,
      { timeout: 20_000 },
    )
    await region.getByRole('button', { name: 'Detalles', exact: true }).click()
    const detalleCliente = page.getByRole('dialog', { name: 'Tarjeta RFID' })
    await solicitudCliente
    await barreras.get(tarjetaCliente.asociacionId)?.iniciada
    await page.keyboard.press('Escape')
    await expect(detalleCliente).toBeHidden()

    await region.getByRole('button', { name: 'EMPLEADO', exact: true }).click()
    await expect(region.getByRole('button', { name: 'Detalles', exact: true })).toHaveCount(1)
    const solicitudEmpleado = page.waitForRequest(
      (solicitud) =>
        new URL(solicitud.url()).pathname ===
        `/api/v1/tarjetas-rfid/${tarjetaEmpleado.asociacionId}`,
      { timeout: 20_000 },
    )
    const respuestaEmpleado = page.waitForResponse(
      (respuesta) =>
        new URL(respuesta.url()).pathname ===
        `/api/v1/tarjetas-rfid/${tarjetaEmpleado.asociacionId}`,
      { timeout: 20_000 },
    )
    await region.getByRole('button', { name: 'Detalles', exact: true }).click()
    const detalleEmpleado = page.getByRole('dialog', { name: 'Tarjeta RFID' })
    await solicitudEmpleado
    await barreras.get(tarjetaEmpleado.asociacionId)?.iniciada
    await expect(detalleEmpleado.getByRole('status')).toContainText('Cargando detalles…')

    barreras.get(tarjetaCliente.asociacionId)?.liberar()
    if (barreras.get(tarjetaCliente.asociacionId)?.fueIniciada) {
      await barreras.get(tarjetaCliente.asociacionId)?.finalizada
    }
    await expect(detalleEmpleado.getByRole('status')).toContainText('Cargando detalles…')
    const textoEntreRespuestas = (await detalleEmpleado.innerText()).toUpperCase()
    expect(
      textoEntreRespuestas.includes(tarjetaCliente.uid),
      'la UID del detalle cerrado no aparece en la asociación nueva',
    ).toBe(false)

    barreras.get(tarjetaEmpleado.asociacionId)?.liberar()
    expect((await respuestaEmpleado).status()).toBe(200)
    const textoFinal = (await detalleEmpleado.innerText()).toUpperCase()
    expect(
      textoFinal.includes(tarjetaEmpleado.uid),
      'el detalle final corresponde a EMPLEADO',
    ).toBe(true)
    expect(
      textoFinal.includes(tarjetaCliente.uid),
      'el detalle final no conserva la UID anterior',
    ).toBe(false)
  } finally {
    for (const barrera of barreras.values()) {
      barrera.liberar()
      if (barrera.fueIniciada) await barrera.finalizada
    }
    await page.unroute('**/api/v1/tarjetas-rfid/*')
  }
})

test('una segunda pestaña ya completada hace que el conflicto termine como éxito único', async ({
  page,
}) => {
  await page.route('**/api/v1/eventos/administracion**', async (ruta) => {
    await ruta.abort('failed')
  })
  await iniciarSesion(page)
  await page.goto(webUrl('/admin/tarjetas-rfid'))
  await cancelarCapturaActiva(page.context().request)
  await cancelarActivas(page.context().request, 'CLIENTE')
  const flujo = await crearVistaPrevia(page, 'CLIENTE')
  let autorizadaConfirmada = false
  await page.route(`**/api/v1/rfid-1/capturas/${flujo.capturaId}`, async (ruta) => {
    if (ruta.request().method() !== 'GET') return ruta.continue()
    const respuesta = await ruta.fetch()
    const estado = (await respuesta.json()) as Record<string, unknown>
    const json = autorizadaConfirmada ? estado : { ...estado, estado: 'VISTA_PREVIA' }
    await ruta.fulfill({ response: respuesta, json })
  })

  const otraPestana = await page.context().newPage()
  try {
    const respuestaVistaPreviaOtraPestana = otraPestana.waitForResponse(
      (respuesta) =>
        new URL(respuesta.url()).pathname ===
          `/api/v1/rfid-1/capturas/${flujo.capturaId}/vista-previa` &&
        respuesta.request().method() === 'GET' &&
        respuesta.status() === 200,
      { timeout: 20_000 },
    )
    await otraPestana.goto(webUrl('/admin/tarjetas-rfid'))
    expect((await respuestaVistaPreviaOtraPestana).status()).toBe(200)
    const dialogoOtraPestana = otraPestana.getByRole('dialog', { name: 'Asociar tarjeta' })
    await expect(
      dialogoOtraPestana.getByText('3. Confirmar asociación', { exact: true }),
    ).toBeVisible({ timeout: 20_000 })
    const confirmacionOtraPestana = otraPestana.waitForResponse(
      (respuesta) =>
        new URL(respuesta.url()).pathname ===
          `/api/v1/rfid-1/capturas/${flujo.capturaId}/confirmacion` &&
        respuesta.request().method() === 'POST',
    )
    await dialogoOtraPestana
      .getByRole('button', { name: 'Confirmar asociación', exact: true })
      .click()
    expect((await confirmacionOtraPestana).status()).toBe(200)
    await expect(dialogoOtraPestana).toBeHidden()

    const estadoCompletado = await page
      .context()
      .request.get(webUrl(`/api/v1/rfid-1/capturas/${flujo.capturaId}`))
    expect(estadoCompletado.status()).toBe(200)
    const capturaCompletada = (await estadoCompletado.json()) as { estado: string }
    expect(capturaCompletada.estado).toBe('COMPLETADA')
    expect((await consultarTarjetas(page.context().request, 'CLIENTE', 'ACTIVA')).total).toBe(1)

    let intentosEnPestanaInicial = 0
    let consultoEstadoCompletado = false
    page.on('request', (solicitud) => {
      const destino = new URL(solicitud.url())
      if (
        destino.pathname === `/api/v1/rfid-1/capturas/${flujo.capturaId}/confirmacion` &&
        solicitud.method() === 'POST'
      ) {
        intentosEnPestanaInicial += 1
      }
      if (
        destino.pathname === `/api/v1/rfid-1/capturas/${flujo.capturaId}` &&
        solicitud.method() === 'GET'
      ) {
        consultoEstadoCompletado = true
      }
    })
    await page.route(`**/api/v1/rfid-1/capturas/${flujo.capturaId}/confirmacion`, async (ruta) => {
      autorizadaConfirmada = true
      await ruta.fulfill({ status: 409, contentType: 'application/json', body: '{}' })
    })
    const conflicto = page.waitForResponse(
      (respuesta) =>
        new URL(respuesta.url()).pathname ===
          `/api/v1/rfid-1/capturas/${flujo.capturaId}/confirmacion` && respuesta.status() === 409,
    )
    await flujo.dialogo.getByRole('button', { name: 'Confirmar asociación', exact: true }).click()
    expect((await conflicto).status()).toBe(409)
    await expect(flujo.dialogo).toBeHidden()
    expect(intentosEnPestanaInicial).toBe(1)
    expect(consultoEstadoCompletado).toBe(true)
    expect((await consultarTarjetas(page.context().request, 'CLIENTE', 'ACTIVA')).total).toBe(1)
  } finally {
    await otraPestana.close()
  }
})
