import { expect, test, type Locator } from '@playwright/test'
import {
  cancelarCapturaActiva,
  crearUidSintetico,
  estadoEventosRfid,
  instrumentarEventosRfid,
  baseURL,
  enviarLecturaSintetica,
  iniciarSesion,
  webUrl,
} from './soporte'

interface InicioCaptura {
  capturaId: string
  estado: string
  expiraEn: string
}

interface PaginaTarjetas {
  total: number
}

async function verificarNumerosPasos(dialogo: Locator, pasoActual: number): Promise<void> {
  const numeros = dialogo.locator('.paso-asociacion-rfid__numero')
  await expect(numeros).toHaveText(['1', '2', '3'])
  for (let indice = 0; indice < 3; indice += 1) await expect(numeros.nth(indice)).toBeVisible()
  await expect(dialogo.locator('.pasos-asociacion-rfid li').nth(pasoActual - 1)).toHaveAttribute(
    'aria-current',
    'step',
  )
}

function rutaPersonas(): string {
  return new URL('/api/v1/rfid-1/capturas', baseURL).pathname
}

async function totalTarjetas(
  page: import('@playwright/test').Page,
  tipoEntidad: string,
): Promise<number> {
  const respuesta = await page
    .context()
    .request.get(webUrl(`/api/v1/tarjetas-rfid?tipoEntidad=${tipoEntidad}&estado=TODAS&pagina=1`))
  expect(respuesta.status()).toBe(200)
  const encabezados = respuesta.headers()
  expect(encabezados['cache-control']?.toLowerCase()).toContain('no-store')
  expect(encabezados.vary?.toLowerCase()).toContain('cookie')
  const pagina = (await respuesta.json()) as PaginaTarjetas
  return pagina.total
}

async function elegirPersona(
  page: import('@playwright/test').Page,
  tipoEntidad: 'CLIENTE' | 'EMPLEADO',
): Promise<import('@playwright/test').Locator> {
  await page.getByRole('button', { name: 'Asociar tarjeta', exact: true }).click()
  const dialogo = page.getByRole('dialog', { name: 'Asociar tarjeta' })
  await verificarNumerosPasos(dialogo, 1)
  if (tipoEntidad === 'EMPLEADO') {
    await dialogo.getByRole('button', { name: 'EMPLEADO', exact: true }).click()
  }
  const busqueda = dialogo.getByRole('combobox', { name: 'Buscar' })
  await busqueda.fill('Stage 2')
  const nombreCandidato = tipoEntidad === 'CLIENTE' ? /CLI-\d{4,}/ : /Empleado Stage 2 Sintetico/
  const candidato = dialogo.getByRole('option', { name: nombreCandidato }).first()
  await expect(candidato).toBeVisible()
  await candidato.click()
  await dialogo.getByRole('button', { name: 'Siguiente', exact: true }).click()
  await expect(dialogo.getByText('Lee la tarjeta', { exact: true })).toBeVisible()
  await verificarNumerosPasos(dialogo, 2)
  return dialogo
}

async function iniciarCaptura(
  page: import('@playwright/test').Page,
  dialogo: import('@playwright/test').Locator,
): Promise<InicioCaptura> {
  const respuesta = page.waitForResponse(
    (elemento) =>
      new URL(elemento.url()).pathname === rutaPersonas() && elemento.request().method() === 'POST',
  )
  const solicitud = page.waitForRequest(
    (elemento) =>
      new URL(elemento.url()).pathname === rutaPersonas() && elemento.method() === 'POST',
  )
  await dialogo.getByRole('button', { name: 'Iniciar lectura', exact: true }).click()
  const [recibo, peticion] = await Promise.all([respuesta, solicitud])
  expect(recibo.status()).toBe(201)
  const encabezados = await peticion.allHeaders()
  expect(Boolean(encabezados['x-csrf-token'])).toBe(true)
  expect(Boolean(encabezados['idempotency-key'])).toBe(true)
  return (await recibo.json()) as InicioCaptura
}

async function prepararVistaPrevia(
  page: import('@playwright/test').Page,
  dialogo: import('@playwright/test').Locator,
  capturaId: string,
  uid?: string,
): Promise<string> {
  const respuestaPrevia = page.waitForResponse(
    (elemento) =>
      new URL(elemento.url()).pathname === `/api/v1/rfid-1/capturas/${capturaId}/vista-previa` &&
      elemento.status() === 200,
  )
  const lectura = await enviarLecturaSintetica(capturaId, uid)
  expect(lectura.estadoHttp).toBe(200)
  expect(lectura.resultado?.estado).toBe('VISTA_PREVIA')
  const respuesta = await respuestaPrevia
  const encabezados = await respuesta.allHeaders()
  expect(encabezados['cache-control']?.toLowerCase()).toContain('no-store')
  expect(encabezados.vary?.toLowerCase()).toContain('cookie')
  await expect(dialogo.getByText('Revisa la tarjeta', { exact: true })).toBeVisible()
  await verificarNumerosPasos(dialogo, 3)
  const texto = (await dialogo.innerText()).toUpperCase()
  expect(
    texto.includes(lectura.uid),
    'la vista previa muestra la UID temporal sin imprimirla',
  ).toBe(true)
  await expect(dialogo.getByText('Código', { exact: true })).toBeVisible()
  await expect(dialogo.getByText('Estado inicial', { exact: true })).toHaveCount(0)
  expect(texto.includes('ACTIVA'), 'no se repite el estado inicial').toBe(false)
  return lectura.uid
}

test('CLIENTE y EMPLEADO se asocian solo tras confirmación explícita', async ({ page }) => {
  await instrumentarEventosRfid(page)
  await iniciarSesion(page)
  await page.goto(new URL('/admin/tarjetas-rfid', baseURL).toString())

  const dialogoCliente = await elegirPersona(page, 'CLIENTE')
  const capturaDescartada = await iniciarCaptura(page, dialogoCliente)
  const uidDescartada = crearUidSintetico()
  await prepararVistaPrevia(page, dialogoCliente, capturaDescartada.capturaId, uidDescartada)
  expect(await totalTarjetas(page, 'CLIENTE'), 'una vista previa tampoco crea la asociación').toBe(
    0,
  )

  const cancelacionPrevia = page.waitForResponse(
    (elemento) =>
      new URL(elemento.url()).pathname ===
        `/api/v1/rfid-1/capturas/${capturaDescartada.capturaId}` &&
      elemento.request().method() === 'DELETE',
  )
  const nuevaCaptura = page.waitForResponse(
    (elemento) =>
      new URL(elemento.url()).pathname === '/api/v1/rfid-1/capturas' &&
      elemento.request().method() === 'POST',
  )
  await dialogoCliente.getByRole('button', { name: 'Escanear otra tarjeta', exact: true }).click()
  const [respuestaCancelacionPrevia, respuestaNuevaCaptura] = await Promise.all([
    cancelacionPrevia,
    nuevaCaptura,
  ])
  expect(respuestaCancelacionPrevia.status()).toBe(204)
  expect(respuestaNuevaCaptura.status()).toBe(201)
  const capturaCliente = (await respuestaNuevaCaptura.json()) as InicioCaptura
  expect(
    capturaCliente.capturaId === capturaDescartada.capturaId,
    'la nueva lectura usa otra captura',
  ).toBe(false)
  const dialogoSinUidAnterior = (await dialogoCliente.innerText()).toUpperCase()
  expect(
    dialogoSinUidAnterior.includes(uidDescartada),
    'la vista previa anterior se elimina al reemplazarla',
  ).toBe(false)
  await expect(dialogoCliente.getByText(/cada 8 segundos/i)).toHaveCount(0)

  const uidCliente = crearUidSintetico()
  let uidEnConsola = false
  let uidEnUrl = false
  let bearerEnWeb = false
  const inspeccionesRequests: Promise<void>[] = []
  page.on('console', (mensaje) => {
    uidEnConsola ||= mensaje.text().toUpperCase().includes(uidCliente)
  })
  page.on('request', (solicitud) => {
    uidEnUrl ||= solicitud.url().toUpperCase().includes(uidCliente)
    inspeccionesRequests.push(
      solicitud.allHeaders().then((encabezados) => {
        bearerEnWeb ||= encabezados.authorization?.toLowerCase().startsWith('bearer ') ?? false
      }),
    )
  })
  await prepararVistaPrevia(page, dialogoCliente, capturaCliente.capturaId, uidCliente)
  expect(await totalTarjetas(page, 'CLIENTE'), 'no se crea antes de pulsar confirmar').toBe(0)
  const eventos = await estadoEventosRfid(page)
  expect(eventos.maximoActivos).toBe(1)
  expect(eventos.tipos).toContain('rfid1.captura.actualizada')
  expect(eventos.tamanosPayload.length).toBeGreaterThan(0)
  expect(
    eventos.tamanosPayload.every((tamano) => tamano === 2),
    'las invalidaciones RFID transmiten un objeto JSON vacío',
  ).toBe(true)

  const respuestaRecarga = await page.reload()
  expect(Boolean(respuestaRecarga)).toBe(true)
  if (!respuestaRecarga) throw new Error('No se recibió la respuesta SSR de la recarga.')
  expect(respuestaRecarga.status()).toBe(200)
  const htmlRecargado = (await respuestaRecarga?.text())?.toUpperCase() ?? ''
  expect(htmlRecargado.includes(uidCliente), 'la respuesta SSR no contiene la UID temporal').toBe(
    false,
  )
  await expect(page.getByRole('dialog', { name: 'Asociar tarjeta' })).toBeVisible()
  await expect(page.getByText('Revisa la tarjeta', { exact: true })).toBeVisible()
  const datosPayload = page.locator('#__NUXT_DATA__')
  await expect(datosPayload).toHaveCount(1)
  const datosHidratados = (await datosPayload.textContent())?.toUpperCase() ?? ''
  expect(
    datosHidratados.includes(uidCliente),
    'el payload de hidratación no contiene la UID temporal',
  ).toBe(false)
  const datosPersistidosIncluyenUid = await page.evaluate((uid) => {
    const almacenes = [window.localStorage, window.sessionStorage]
    return almacenes.some((almacen) =>
      Array.from({ length: almacen.length }, (_, indice) => almacen.key(indice))
        .filter((clave): clave is string => clave !== null)
        .some((clave) => `${clave}=${almacen.getItem(clave) ?? ''}`.toUpperCase().includes(uid)),
    )
  }, uidCliente)
  expect(datosPersistidosIncluyenUid, 'localStorage y sessionStorage no contienen la UID').toBe(
    false,
  )
  expect(page.url().toUpperCase().includes(uidCliente), 'la URL no contiene la UID').toBe(false)
  await Promise.all(inspeccionesRequests)
  expect(uidEnConsola, 'la consola de la página no contiene la UID').toBe(false)
  expect(uidEnUrl, 'las solicitudes del navegador no contienen la UID').toBe(false)
  expect(bearerEnWeb, 'el Bearer técnico permanece fuera de las solicitudes de la página').toBe(
    false,
  )

  let respuestaPerdida = true
  let confirmaciones: string[] = []
  let incluyoUidEnCuerpo = false
  let confirmacionClienteConCsrf = false
  let consultoEstado = false
  page.on('request', (solicitud) => {
    const destino = new URL(solicitud.url())
    if (
      destino.pathname === `/api/v1/rfid-1/capturas/${capturaCliente.capturaId}` &&
      solicitud.method() === 'GET'
    ) {
      consultoEstado = true
    }
  })
  await page.route(
    `**/api/v1/rfid-1/capturas/${capturaCliente.capturaId}/confirmacion`,
    async (ruta) => {
      const solicitud = ruta.request()
      const encabezados = await solicitud.allHeaders()
      confirmaciones.push(encabezados['idempotency-key'] ?? '')
      confirmacionClienteConCsrf ||= Boolean(encabezados['x-csrf-token'])
      const cuerpo = solicitud.postData() ?? ''
      incluyoUidEnCuerpo ||= cuerpo.toUpperCase().includes(uidCliente)
      const respuesta = await ruta.fetch()
      if (respuestaPerdida) {
        respuestaPerdida = false
        await ruta.abort('failed')
        return
      }
      await ruta.fulfill({ response: respuesta })
    },
  )

  consultoEstado = false
  await dialogoCliente.getByRole('button', { name: 'Confirmar asociación', exact: true }).click()
  await expect(dialogoCliente).toBeHidden({ timeout: 15_000 })
  expect(confirmaciones.length).toBe(1)
  expect(Boolean(confirmaciones[0])).toBe(true)
  expect(confirmaciones.every((clave) => clave === confirmaciones[0])).toBe(true)
  expect(incluyoUidEnCuerpo).toBe(false)
  expect(confirmacionClienteConCsrf).toBe(true)
  expect(consultoEstado, 'tras perder la respuesta consulta el estado autoritativo').toBe(true)
  expect(await totalTarjetas(page, 'CLIENTE')).toBe(1)
  await expect
    .poll(async () => (await estadoEventosRfid(page)).tipos.includes('rfid1.tarjetas.actualizadas'))
    .toBe(true)

  const dialogoEmpleado = await elegirPersona(page, 'EMPLEADO')
  const capturaEmpleado = await iniciarCaptura(page, dialogoEmpleado)
  const lecturaDuplicada = await enviarLecturaSintetica(capturaEmpleado.capturaId, uidCliente)
  expect(lecturaDuplicada.estadoHttp).toBe(409)
  await expect(dialogoEmpleado.getByRole('status', { name: 'Estado de la lectura' })).toBeVisible()
  await expect(dialogoEmpleado.getByText('Lee la tarjeta', { exact: true })).toBeVisible()

  const respuestaEstado = await page
    .context()
    .request.get(webUrl(`/api/v1/rfid-1/capturas/${capturaEmpleado.capturaId}`))
  expect(respuestaEstado.status()).toBe(200)
  const estado = (await respuestaEstado.json()) as { estado: string }
  expect(estado.estado).toBe('ESCANEANDO')

  const dialogoConEmpleado = page.getByRole('dialog', { name: 'Asociar tarjeta' })
  const uidEmpleado = await prepararVistaPrevia(page, dialogoConEmpleado, capturaEmpleado.capturaId)
  expect(uidEmpleado === uidCliente, 'la nueva lectura debe usar otro UID').toBe(false)
  expect(await totalTarjetas(page, 'EMPLEADO')).toBe(0)
  let reintentoPerdido = true
  let clavesEmpleado: string[] = []
  let confirmacionEmpleadoConCsrf = false
  let consultoCapturaEmpleado = false
  let confirmacionEmpleadoAbortada = false
  page.on('request', (solicitud) => {
    if (
      new URL(solicitud.url()).pathname ===
        `/api/v1/rfid-1/capturas/${capturaEmpleado.capturaId}` &&
      solicitud.method() === 'GET'
    ) {
      consultoCapturaEmpleado = true
    }
  })
  await page.route(
    `**/api/v1/rfid-1/capturas/${capturaEmpleado.capturaId}/confirmacion`,
    async (ruta) => {
      const encabezados = await ruta.request().allHeaders()
      clavesEmpleado.push(encabezados['idempotency-key'] ?? '')
      confirmacionEmpleadoConCsrf ||= Boolean(encabezados['x-csrf-token'])
      if (reintentoPerdido) {
        reintentoPerdido = false
        confirmacionEmpleadoAbortada = true
        await ruta.abort('failed')
        return
      }
      const respuesta = await ruta.fetch()
      await ruta.fulfill({ response: respuesta })
    },
  )
  const solicitudReconciliacionEmpleado = page.waitForRequest(
    (solicitud) =>
      new URL(solicitud.url()).pathname ===
        `/api/v1/rfid-1/capturas/${capturaEmpleado.capturaId}` &&
      solicitud.method() === 'GET' &&
      confirmacionEmpleadoAbortada,
    { timeout: 15_000 },
  )
  await dialogoConEmpleado
    .getByRole('button', { name: 'Confirmar asociación', exact: true })
    .click()
  const solicitudReconciliacion = await solicitudReconciliacionEmpleado
  const estadoReconciliado = await solicitudReconciliacion.response()
  if (!estadoReconciliado) throw new Error('La reconciliación no devolvió respuesta de estado.')
  expect(estadoReconciliado.status()).toBe(200)
  const capturaReconciliada = (await estadoReconciliado.json()) as { estado: string }
  expect(capturaReconciliada.estado).toBe('VISTA_PREVIA')
  await expect(dialogoConEmpleado.getByText('Revisa la tarjeta', { exact: true })).toBeVisible()
  expect(
    consultoCapturaEmpleado,
    'si sigue en vista previa consulta el estado antes de reintentar',
  ).toBe(true)
  expect(clavesEmpleado.length).toBe(1)
  const confirmacion = page.waitForResponse(
    (elemento) =>
      new URL(elemento.url()).pathname ===
        `/api/v1/rfid-1/capturas/${capturaEmpleado.capturaId}/confirmacion` &&
      elemento.request().method() === 'POST',
  )
  await dialogoConEmpleado
    .getByRole('button', { name: 'Confirmar asociación', exact: true })
    .click()
  const respuestaConfirmacion = await confirmacion
  expect(respuestaConfirmacion.status()).toBe(200)
  expect(clavesEmpleado.length).toBe(2)
  expect(Boolean(clavesEmpleado[0])).toBe(true)
  expect(
    clavesEmpleado[0] === clavesEmpleado[1],
    'el reintento conserva la clave idempotente',
  ).toBe(true)
  expect(confirmacionEmpleadoConCsrf).toBe(true)
  await expect(dialogoConEmpleado).toBeHidden()
  expect(await totalTarjetas(page, 'EMPLEADO')).toBe(1)
})

test.afterEach(async ({ page }) => {
  await cancelarCapturaActiva(page.context().request)
})
