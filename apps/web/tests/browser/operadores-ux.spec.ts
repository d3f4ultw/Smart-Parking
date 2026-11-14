import { expect, test } from '@playwright/test'
import {
  CORREO_SINTETICO,
  ID_ACTIVO,
  ID_EMPLEADO,
  ID_EXPIRADO,
  ID_INACTIVO,
  ID_PENDIENTE,
  ID_USADO,
  abrirDirectorioSintetico,
  instalarFixtures,
  seleccionarEmpleado,
  verificarSinErrores,
} from './operadores-ux-fixtures'

test('el directorio conserva búsqueda, estado y paginación de diez filas, sin desbordar en móvil', async ({
  page,
}) => {
  const guardia = await instalarFixtures(page)
  await abrirDirectorioSintetico(page)
  guardia.pasoActual = 'directorio listo; comienza búsqueda y paginación'

  await expect(page.getByRole('heading', { name: 'Operadores', exact: true })).toHaveCount(1)
  await expect(page.locator('.tabla-operadores tbody tr')).toHaveCount(10)
  const navegacion = page.getByRole('navigation', { name: /Páginas de operadores/ })
  await expect(navegacion.getByRole('button', { name: 'Ir a la página 1' })).toHaveAttribute(
    'aria-current',
    'page',
  )
  await navegacion.getByRole('button', { name: 'Ir a la página 2' }).click()
  await expect.poll(() => guardia.consultas.at(-1)?.pagina).toBe('2')
  await expect(page.getByText('Zoe PáginaDos Prueba')).toBeVisible()
  await page.getByRole('button', { name: 'Página anterior' }).click()

  const estado = page.getByRole('group', { name: 'Filtros de operadores' }).getByRole('combobox')
  await estado.selectOption('PENDIENTE')
  await expect.poll(() => guardia.consultas.at(-1)?.estado).toBe('PENDIENTE')
  await expect(page.getByRole('navigation', { name: /Páginas de operadores/ })).toHaveCount(0)
  const busqueda = page.getByLabel('Buscar por nombre o apellido')
  await busqueda.fill('Ana')
  await expect.poll(() => guardia.consultas.at(-1)?.busqueda).toBe('Ana')
  await expect(page.locator('.tabla-operadores tbody tr')).toHaveCount(1)
  await expect(page.getByText('Ana Pendiente Prueba')).toBeVisible()

  await page.setViewportSize({ width: 375, height: 812 })
  await expect(page.getByLabel('Buscar por nombre o apellido')).toBeVisible()
  const anchoDocumento = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(anchoDocumento).toBeLessThanOrEqual(375)
  await expect(page.getByRole('region', { name: /Tabla de operadores/ })).toBeVisible()
  await verificarSinErrores(guardia)
})

test('alta valida correo en el cliente y muestra carga y éxito con promoción interceptada', async ({
  page,
}) => {
  const guardia = await instalarFixtures(page)
  guardia.controles.demorarPromocionMs = 350
  await abrirDirectorioSintetico(page)
  await page.setViewportSize({ width: 375, height: 812 })
  guardia.pasoActual = 'antes de abrir alta'
  await page.getByRole('button', { name: 'Añadir operador' }).click()
  const dialogo = page.getByRole('dialog', { name: 'Añadir operador' })
  await expect(dialogo).toBeVisible()
  guardia.pasoActual = 'modal de alta abierto'
  const cajaDialogo = await dialogo.boundingBox()
  expect(cajaDialogo?.x).toBeGreaterThanOrEqual(0)
  expect((cajaDialogo?.x ?? 0) + (cajaDialogo?.width ?? 0)).toBeLessThanOrEqual(375)
  await expect(dialogo.getByRole('button', { name: 'Enviar invitación' })).toBeDisabled()
  await seleccionarEmpleado(page, guardia)

  const correo = dialogo.getByLabel('Correo para la cuenta y la invitación')
  const enviar = dialogo.getByRole('button', { name: 'Enviar invitación' })
  await correo.fill('correo-invalido')
  await enviar.click()
  await expect(
    dialogo.getByText('Escribe un correo válido para enviar la invitación.'),
  ).toBeVisible()
  expect(guardia.promociones).toHaveLength(0)

  await correo.fill(CORREO_SINTETICO)
  const solicitud = page.waitForRequest(
    (request) =>
      request.method() === 'POST' &&
      new URL(request.url()).pathname.endsWith('/operador/promocion'),
  )
  await enviar.click()
  const solicitudInterceptada = await solicitud
  await expect(dialogo.getByRole('button', { name: 'Enviando invitación…' })).toBeDisabled()
  expect(solicitudInterceptada.url()).toContain(`/empleados/${ID_EMPLEADO}/operador/promocion`)
  await dialogo.getByRole('button', { name: 'Enviando invitación…' }).dispatchEvent('click')
  await expect.poll(() => guardia.promociones.length).toBe(1)
  await expect(dialogo).toHaveCount(0)
  await expect(page.getByText('Cuenta de operador creada', { exact: true })).toBeVisible()
  expect(guardia.promociones).toEqual([
    { id: ID_EMPLEADO, correo: CORREO_SINTETICO, csrf: true, idempotencia: true, etag: true },
  ])
  await verificarSinErrores(guardia)
})

test('alta conserva el formulario ante una duplicación simulada por la API', async ({ page }) => {
  const guardia = await instalarFixtures(page)
  guardia.controles.respuestaPromocion = 'duplicado'
  await abrirDirectorioSintetico(page)
  guardia.pasoActual = 'antes de abrir alta duplicada'
  await page.getByRole('button', { name: 'Añadir operador' }).click()
  const dialogo = page.getByRole('dialog', { name: 'Añadir operador' })
  guardia.pasoActual = 'modal de alta duplicada abierto'
  await seleccionarEmpleado(page, guardia)
  await dialogo.getByLabel('Correo para la cuenta y la invitación').fill(CORREO_SINTETICO)
  await dialogo.getByRole('button', { name: 'Enviar invitación' }).click()
  await expect(dialogo.getByRole('alert')).toBeVisible()
  expect(guardia.promociones).toHaveLength(1)
  await verificarSinErrores(guardia)
})

test('administración muestra invitaciones y acciones por estado, con teclado y recuperación de carga', async ({
  page,
}) => {
  const guardia = await instalarFixtures(page)
  guardia.controles.fallosDetallePorId.set(ID_PENDIENTE, 20)
  guardia.controles.demorarSiguienteDetalleMs = 250
  await abrirDirectorioSintetico(page)
  guardia.pasoActual = 'directorio listo; antes de detalle'

  const botonAna = page.getByRole('button', { name: 'Ver detalles de Ana Pendiente Prueba' })
  await botonAna.focus()
  await page.keyboard.press('Enter')
  let dialogo = page.getByRole('dialog')
  await expect(dialogo).toBeVisible()
  const overlay = page.locator('[class~="bg-black/55"]')
  await expect(overlay).toBeVisible()
  const estiloOverlay = await overlay.evaluate((element) => {
    const estilo = getComputedStyle(element)
    return { fondo: estilo.backgroundColor, desenfoque: estilo.backdropFilter }
  })
  expect(estiloOverlay.fondo).toMatch(/0\.55|55%/)
  expect(estiloOverlay.desenfoque).toBe('none')
  await expect(dialogo.getByRole('status')).toContainText('Cargando la información')
  await expect.poll(() => guardia.detallesFallidosAplicados).toBeGreaterThan(0)
  await expect(
    dialogo.getByRole('alert'),
    `GET detalle: ${JSON.stringify({ ids: guardia.detallesSolicitados, respuestas: guardia.detallesRespuestas })}`,
  ).toBeVisible()
  expect(
    guardia.detallesRespuestas
      .filter((respuesta) => respuesta.id === ID_PENDIENTE)
      .every((respuesta) => respuesta.estado === 503),
  ).toBe(true)
  console.log(
    `[fixture] GET detalle antes del reintento: ${JSON.stringify(guardia.detallesRespuestas)}`,
  )
  guardia.controles.fallosDetallePorId.set(ID_PENDIENTE, 0)
  await dialogo.getByRole('button', { name: 'Reintentar' }).click()
  await expect
    .poll(() =>
      guardia.detallesRespuestas.some(
        (respuesta) => respuesta.id === ID_PENDIENTE && respuesta.estado === 200,
      ),
    )
    .toBe(true)
  console.log(
    `[fixture] GET detalle tras reintento manual: ${JSON.stringify(guardia.detallesRespuestas)}`,
  )
  await expect(dialogo.getByRole('banner').getByText('Por activar', { exact: true })).toBeVisible()
  await expect(dialogo.getByText('Enviado', { exact: true })).toBeVisible()
  await expect(dialogo.getByRole('button', { name: 'Reenviar invitación' })).toBeVisible()
  await expect(dialogo.getByRole('button', { name: 'Desactivar cuenta' })).toHaveCount(0)
  await dialogo.getByRole('button', { name: 'Reenviar invitación' }).click()
  await expect(dialogo.getByRole('heading', { name: 'Reenviar invitación' })).toBeVisible()
  await expect(
    dialogo.getByText('El enlace anterior dejará de funcionar y se enviará una invitación nueva.', {
      exact: true,
    }),
  ).toBeVisible()
  await dialogo.getByRole('button', { name: 'Cancelar' }).click()
  await page.keyboard.press('Escape')
  await expect(dialogo).toHaveCount(0)
  await expect(botonAna).toBeFocused()

  await page.getByRole('button', { name: 'Ver detalles de Beto Expirado Prueba' }).click()
  dialogo = page.getByRole('dialog')
  await expect(dialogo.getByText('Venció', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Ver detalles de Cora Usado Prueba' }).click()
  dialogo = page.getByRole('dialog')
  await expect(dialogo.getByRole('banner').getByText('Activa', { exact: true })).toBeVisible()
  await expect(dialogo.getByText('Usada', { exact: true })).toBeVisible()
  await expect(dialogo.getByRole('button', { name: 'Recuperar contraseña' })).toBeVisible()
  await expect(dialogo.getByRole('button', { name: 'Reenviar invitación' })).toHaveCount(0)
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Ver detalles de Dalia Activa Prueba' }).click()
  dialogo = page.getByRole('dialog')
  await expect(dialogo.getByRole('banner').getByText('Activa', { exact: true })).toBeVisible()
  await expect(dialogo.getByRole('button', { name: 'Recuperar contraseña' })).toBeVisible()
  await expect(dialogo.getByRole('button', { name: 'Desactivar cuenta' })).toBeVisible()
  await expect(dialogo.getByRole('button', { name: 'Reenviar invitación' })).toHaveCount(0)
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Ver detalles de Eli Inactivo Prueba' }).click()
  dialogo = page.getByRole('dialog')
  await expect(dialogo.getByRole('banner').getByText('Desactivada', { exact: true })).toBeVisible()
  await expect(dialogo.getByRole('button', { name: 'Reactivar cuenta' })).toBeVisible()
  await expect(dialogo.getByRole('button', { name: 'Reenviar invitación' })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect.poll(() => guardia.promociones.length).toBe(0)
  await verificarSinErrores(guardia)
})

test('el directorio expone carga, error y reintento sin filtrar solicitudes', async ({ page }) => {
  const guardia = await instalarFixtures(page)
  await abrirDirectorioSintetico(page)
  guardia.pasoActual = 'directorio listo; antes de error de listado'
  guardia.controles.demorarSiguienteListadoMs = 250
  await page.getByRole('button', { name: 'Actualizar lista' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Cargando operadores' })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: 'Cargando operadores' })).toHaveCount(0)
  await expect(page.locator('.tabla-operadores tbody tr')).toHaveCount(10)

  guardia.controles.fallosListado = 20
  const inicioFallo = guardia.consultas.length
  await page.getByRole('button', { name: 'Actualizar lista' }).click()
  await expect.poll(() => guardia.fallosListadoAplicados).toBeGreaterThan(0)
  await expect(
    page.getByRole('alert'),
    `Listado: ${JSON.stringify({ consultas: guardia.consultas.slice(inicioFallo), http: guardia.respuestasHttp, erroresRed: guardia.erroresRed })}`,
  ).toBeVisible()
  const consultasFallidas = guardia.consultas.slice(inicioFallo)
  expect(consultasFallidas.length).toBeGreaterThan(0)
  expect(consultasFallidas.every((consulta) => consulta.respuestaHttp === 503)).toBe(true)
  console.log(`[fixture] GET operadores tras refresh: ${JSON.stringify(consultasFallidas)}`)
  guardia.controles.fallosListado = 0
  await page.getByRole('button', { name: 'Reintentar' }).click()
  await expect(page.locator('.tabla-operadores tbody tr')).toHaveCount(10)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await verificarSinErrores(guardia)
})
