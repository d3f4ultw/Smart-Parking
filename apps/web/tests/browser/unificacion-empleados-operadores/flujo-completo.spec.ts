import { randomUUID } from 'node:crypto'
import {
  expect,
  test,
  type APIRequestContext,
  type Browser,
  type BrowserContext,
  type Page,
} from '@playwright/test'
import { baseURL, iniciarSesion } from '../sesion'

const API = process.env.TEST_API_BASE_URL ?? 'http://api:8080'
const MAILPIT = process.env.TEST_MAILPIT_BASE_URL ?? 'http://mailpit:8025'
const NONCE = process.env.SPNEXT_TEST_FIXTURE_NONCE
const ASUNTO_ACTIVACION = 'Activa tu cuenta de Smart Parking'
const ASUNTO_RECUPERACION = 'Crea una nueva contraseña de Smart Parking'

test.beforeAll(async ({ browser }) => {
  const correoDueno = process.env.TEST_OWNER_EMAIL
  const contrasenaDueno = process.env.TEST_OWNER_PASSWORD
  if (!correoDueno || !contrasenaDueno) {
    throw new Error('Faltan las credenciales sintéticas del propietario de aceptación.')
  }
  await prepararDuenoSintetico(browser, correoDueno, contrasenaDueno)
})

test('empleados, operadores, sesiones, Mailpit, SSR, CSR y asociaciones conservan su contrato', async ({
  browser,
  page,
}) => {
  test.setTimeout(300_000)
  const correoDueno = process.env.TEST_OWNER_EMAIL
  const contrasenaDueno = process.env.TEST_OWNER_PASSWORD
  if (!correoDueno || !contrasenaDueno || !NONCE) {
    throw new Error('Falta la configuración sintética del runner de aceptación.')
  }

  const contextoFixture = await crearContextoDuenoApi(browser, correoDueno, contrasenaDueno)
  let fixture: { fixtureId: string; empleadoNombre: string; operadorNombre: string } | null = null
  try {
    const preparacion = await contextoFixture.api.post(
      `${API}/api/v1/__sandbox/unificacion/preparar`,
      {
        data: { nonce: NONCE },
        headers: { 'X-CSRF-TOKEN': contextoFixture.csrf },
      },
    )
    expect(preparacion.status()).toBe(201)
    const cuerpoPreparacion = (await preparacion.json()) as Partial<{
      fixtureId: string
      empleadoNombre: string
      operadorNombre: string
    }>
    if (
      typeof cuerpoPreparacion.fixtureId !== 'string' ||
      typeof cuerpoPreparacion.empleadoNombre !== 'string' ||
      typeof cuerpoPreparacion.operadorNombre !== 'string'
    ) {
      throw new Error('La preparación no devolvió un identificador y nombres sintéticos válidos.')
    }
    fixture = {
      fixtureId: cuerpoPreparacion.fixtureId,
      empleadoNombre: cuerpoPreparacion.empleadoNombre,
      operadorNombre: cuerpoPreparacion.operadorNombre,
    }
  } finally {
    await contextoFixture.context.close()
  }
  if (!fixture) throw new Error('No se preparó la fixture sintética de integración.')

  const sufijo = randomUUID().slice(0, 10)
  const nombres = `E2E-${sufijo}`
  const correoInicial = `e2e-${sufijo}@example.test`
  const correoNuevo = `e2e-nuevo-${sufijo}@example.test`
  const contrasenaInicial = `Inicial-${randomUUID()}-2026!`
  const contrasenaNueva = `Renovada-${randomUUID()}-2026!`
  const baseMensajes = await contarMensajes()

  await iniciarSesion(page)
  await abrirEmpleados(page)
  const solicitudesDirectorio: string[] = []
  page.on('request', (solicitud) => {
    const url = new URL(solicitud.url())
    if (solicitud.method() === 'GET' && url.pathname === '/api/v1/empleados') {
      solicitudesDirectorio.push(url.pathname)
    }
  })
  await page.goto(`${baseURL}/admin/empleados`)
  await esperarVueMontada(page)
  await expect(page.getByRole('region', { name: 'Lista de empleados' }).first()).toBeVisible()
  await expect(page.getByText(fixture.empleadoNombre, { exact: false })).toBeVisible()
  await page.waitForTimeout(750)
  expect(solicitudesDirectorio.length <= 1).toBe(true)
  const hidratacionInicial = await page.locator('#__NUXT_DATA__').textContent()
  expect(hidratacionInicial ?? '').not.toMatch(/(?:uidCanonico|uid_canonico|huellaUid|huella_uid)/i)

  const contextoSse = await browser.newContext()
  try {
    const paginaSse = await contextoSse.newPage()
    const respuestasDirectorioSse: number[] = []
    paginaSse.on('response', (respuesta) => {
      const url = new URL(respuesta.url())
      if (url.pathname === '/api/v1/empleados' && respuesta.request().method() === 'GET') {
        respuestasDirectorioSse.push(respuesta.status())
      }
    })
    await paginaSse.addInitScript(() => {
      type VentanaConEventos = Window & { __eventosSseAceptacion?: string[] }
      const ventana = window as VentanaConEventos
      ventana.__eventosSseAceptacion = []
      const FuenteOriginal = window.EventSource
      window.EventSource = class extends FuenteOriginal {
        constructor(url: string | URL, opciones?: EventSourceInit) {
          super(url, opciones)
          for (const nombre of [
            'empleado.directorio.actualizado',
            'administracion.directorio.resincronizar',
          ]) {
            this.addEventListener(nombre, () => ventana.__eventosSseAceptacion?.push(nombre))
          }
        }
      }
    })
    await iniciarSesion(paginaSse)
    const conexionSsePromise = esperarRespuesta(paginaSse, '/api/v1/eventos/administracion', 'GET')
    await abrirEmpleados(paginaSse)
    const conexionSse = await conexionSsePromise
    expect(conexionSse.status()).toBe(200)
    expect(conexionSse.headers()['content-type']).toContain('text/event-stream')
    await expect(paginaSse.getByText(fixture.empleadoNombre, { exact: false })).toBeVisible()
    const totalDirectorioSse = paginaSse.locator('.resumen-directorio > span')
    const textoTotalInicial = await totalDirectorioSse.textContent()
    const totalInicial = Number(textoTotalInicial?.match(/^\s*(\d+)/)?.[1])
    expect(Number.isSafeInteger(totalInicial)).toBe(true)
    const lecturasAntesDeRegistrar = respuestasDirectorioSse.length

    const registro = await registrarEmpleado(page, nombres, 'Unificacion')
    expect(/^E-\d{4,}$/.test(registro.codigo)).toBe(true)
    await expect
      .poll(() =>
        paginaSse.evaluate(
          () =>
            (window as Window & { __eventosSseAceptacion?: string[] }).__eventosSseAceptacion ?? [],
        ),
      )
      .toContain('empleado.directorio.actualizado')
    await expect
      .poll(() => respuestasDirectorioSse.length)
      .toBeGreaterThan(lecturasAntesDeRegistrar)
    expect(respuestasDirectorioSse.at(-1)).toBe(200)
    await expect(totalDirectorioSse).toHaveText(
      `${totalInicial + 1} ${totalInicial === 0 ? 'empleado' : 'empleados'}`,
    )
    const paginaFinal = Math.ceil((totalInicial + 1) / 10)
    if (paginaFinal > 1) await paginaSse.goto(`${baseURL}/admin/empleados?pagina=${paginaFinal}`)
    await expect(paginaSse.getByRole('row', { name: new RegExp(nombres) })).toBeVisible({
      timeout: 20_000,
    })
    await expect.poll(contarMensajes).toBe(baseMensajes)

    await abrirAdministracionEmpleado(page, `${nombres} Unificacion`)
    const dialogoEmpleado = page.getByRole('dialog')
    await dialogoEmpleado.getByLabel('Correo del empleado').fill(correoInicial)
    const respuestaCorreoInicial = esperarRespuesta(
      page,
      `/api/v1/empleados/${registro.idTexto}/correo`,
      'PATCH',
    )
    await dialogoEmpleado.getByRole('button', { name: 'Guardar correo', exact: true }).click()
    expect((await respuestaCorreoInicial).status()).toBe(200)
    await expect.poll(contarMensajes).toBe(baseMensajes)

    const respuestaPromocionPromise = esperarRespuesta(
      page,
      `/api/v1/empleados/${registro.idTexto}/operador/promocion`,
      'POST',
    )
    await dialogoEmpleado
      .getByRole('button', { name: 'Crear cuenta de operador', exact: true })
      .click()
    const grupoConfirmacion = dialogoEmpleado.getByRole('group', { name: 'Confirmar acción' })
    const solicitudPromocion = esperarSolicitud(
      page,
      `/api/v1/empleados/${registro.idTexto}/operador/promocion`,
      'POST',
    )
    await grupoConfirmacion.getByRole('button', { name: 'Confirmar', exact: true }).click()
    const [respuestaPromocion, peticionPromocion] = await Promise.all([
      respuestaPromocionPromise,
      solicitudPromocion,
    ])
    if (respuestaPromocion.status() !== 200) {
      let codigo = 'sin-codigo'
      try {
        const cuerpo = (await respuestaPromocion.json()) as { codigo?: unknown }
        if (typeof cuerpo.codigo === 'string') codigo = cuerpo.codigo
      } catch {
        codigo = 'respuesta-no-json'
      }
      throw new Error(`La promoción falló con HTTP ${respuestaPromocion.status()} (${codigo}).`)
    }
    const resultadoPromocion = (await respuestaPromocion.json()) as { operadorId?: string }
    const idOperador = String(resultadoPromocion.operadorId ?? '')
    expect(/^[0-9a-f-]{36}$/i.test(idOperador)).toBe(true)
    const cabecerasPromocion = peticionPromocion.headers()
    expect(/^"[0-9]+"$/.test(cabecerasPromocion['if-match'] ?? '')).toBe(true)
    expect(Boolean(cabecerasPromocion['idempotency-key'])).toBe(true)
    await expect.poll(contarMensajes).toBe(baseMensajes + 1)
    await esperarCorreo(correoInicial, ASUNTO_ACTIVACION)
    await expect(dialogoEmpleado.locator('dd').filter({ hasText: 'Por activar' })).toBeVisible()
    await expect(paginaSse.getByRole('row', { name: new RegExp(nombres) })).toContainText(
      'Por activar',
    )

    await activarDesdeCorreo(page, correoInicial, ASUNTO_ACTIVACION, contrasenaInicial)
    await expect(page.getByRole('heading', { name: 'Activar cuenta' })).toBeVisible()
    await expect(page.getByRole('status')).toContainText('Tu cuenta está lista.')
    await comprobarLoginOperadorRechazado(browser, correoInicial, contrasenaInicial)

    const contextoDueno = await crearContextoDuenoApi(browser, correoDueno, contrasenaDueno)
    let contextoOperador = await convertirSesionEnOperador(contextoDueno.context, idOperador)
    try {
      await comprobarSesionOperadorYPermisos(contextoOperador.api)
      await comprobarDuenoSigueActivo(page)

      const tokenRecuperacion = await iniciarRecuperacion(page, idOperador, correoInicial)
      const mensajesAntesCambioActivo = await contarMensajes()

      await abrirEmpleados(page, `${nombres} Unificacion`)
      await abrirAdministracionEmpleado(page, `${nombres} Unificacion`)
      const dialogoActivo = page.getByRole('dialog')
      await dialogoActivo.getByLabel('Correo del empleado').fill(correoNuevo)
      const respuestaCorreoActivo = esperarRespuesta(
        page,
        `/api/v1/empleados/${registro.idTexto}/correo`,
        'PATCH',
      )
      await dialogoActivo.getByRole('button', { name: 'Guardar correo', exact: true }).click()
      expect((await respuestaCorreoActivo).status()).toBe(200)
      await expect(dialogoActivo.locator('dd').filter({ hasText: 'Activa' })).toBeVisible()
      await expect.poll(contarMensajes).toBe(mensajesAntesCambioActivo)
      await comprobarSesionRevocada(contextoOperador.api)
      await comprobarDuenoSigueActivo(page)
      await comprobarTokenRecuperacionRevocado(page, tokenRecuperacion)
    } finally {
      await contextoDueno.context.close()
    }

    await page.keyboard.press('Escape')
    let contextoDespromocion = await crearContextoDuenoApi(browser, correoDueno, contrasenaDueno)
    contextoOperador = await convertirSesionEnOperador(contextoDespromocion.context, idOperador)
    try {
      await abrirEmpleados(page, `${nombres} Unificacion`)
      await abrirAdministracionEmpleado(page, `${nombres} Unificacion`)
      const dialogo = page.getByRole('dialog')
      const respuestaDespromocion = esperarRespuesta(
        page,
        `/api/v1/empleados/${registro.idTexto}/operador/desactivacion`,
        'POST',
      )
      await dialogo.getByRole('button', { name: 'Desactivar acceso', exact: true }).click()
      const grupo = dialogo.getByRole('group', { name: 'Confirmar acción' })
      await grupo.getByRole('button', { name: 'Confirmar', exact: true }).click()
      const resultadoDespromocion = await respuestaDespromocion
      expect(resultadoDespromocion.status()).toBe(200)
      const cuerpoDespromocion = (await resultadoDespromocion.json()) as { operadorId?: string }
      expect(String(cuerpoDespromocion.operadorId) === idOperador).toBe(true)
      await expect(dialogo.locator('dd').filter({ hasText: 'Desactivada' })).toBeVisible()
      await comprobarSesionRevocada(contextoOperador.api)
      await comprobarDuenoSigueActivo(page)
    } finally {
      await contextoDespromocion.context.close()
    }

    await page.getByRole('button', { name: 'Reactivar cuenta de operador', exact: true }).click()
    const dialogoReactivar = page.getByRole('dialog')
    const respuestaReactivacionPromise = esperarRespuesta(
      page,
      `/api/v1/empleados/${registro.idTexto}/operador/promocion`,
      'POST',
    )
    const mensajesAntesReactivacion = await contarMensajes()
    const grupoReactivacion = dialogoReactivar.getByRole('group', { name: 'Confirmar acción' })
    await grupoReactivacion.getByRole('button', { name: 'Confirmar', exact: true }).click()
    let resultadoReactivacion = await respuestaReactivacionPromise
    if (resultadoReactivacion.status() === 429) {
      const errorCuota = (await resultadoReactivacion.json()) as { codigo?: string }
      const espera = Number(resultadoReactivacion.headers()['retry-after'])
      expect(errorCuota.codigo).toBe('REENVIO_EN_ENFRIAMIENTO')
      expect(espera).toBeGreaterThan(0)
      expect(espera).toBeLessThanOrEqual(60)
      await page.waitForTimeout((espera + 1) * 1_000)
      const reintentoReactivacion = esperarRespuesta(
        page,
        `/api/v1/empleados/${registro.idTexto}/operador/promocion`,
        'POST',
      )
      await grupoReactivacion.getByRole('button', { name: 'Confirmar', exact: true }).click()
      resultadoReactivacion = await reintentoReactivacion
    }
    expect(resultadoReactivacion.status()).toBe(200)
    const cuerpoReactivacion = (await resultadoReactivacion.json()) as { operadorId?: string }
    expect(String(cuerpoReactivacion.operadorId) === idOperador).toBe(true)
    await expect.poll(contarMensajes).toBe(mensajesAntesReactivacion + 1)
    await esperarCorreo(correoNuevo, ASUNTO_ACTIVACION)
    await page.keyboard.press('Escape')
    await activarDesdeCorreo(page, correoNuevo, ASUNTO_ACTIVACION, contrasenaNueva)
    await expect(page.getByRole('status')).toContainText('Tu cuenta está lista.')
    await comprobarLoginOperadorRechazado(browser, correoNuevo, contrasenaNueva)

    const contextoDesactivacionEmpleado = await crearContextoDuenoApi(
      browser,
      correoDueno,
      contrasenaDueno,
    )
    contextoOperador = await convertirSesionEnOperador(
      contextoDesactivacionEmpleado.context,
      idOperador,
    )
    try {
      await abrirEmpleados(page, `${nombres} Unificacion`)
      await page
        .getByRole('button', {
          name: `Desactivar empleado ${nombres} Unificacion`,
          exact: true,
        })
        .click()
      const modalEstado = page.getByRole('dialog')
      const respuestaDesactivarEmpleado = esperarRespuesta(
        page,
        `/api/v1/empleados/${registro.idTexto}/estado`,
        'PATCH',
      )
      await modalEstado.getByRole('button', { name: 'Desactivar empleado', exact: true }).click()
      expect((await respuestaDesactivarEmpleado).status()).toBe(200)
      await comprobarSesionRevocada(contextoOperador.api)
      await comprobarDuenoSigueActivo(page)
      await expect(page.getByRole('row', { name: new RegExp(nombres) })).toContainText(
        'Desactivada',
      )

      await page
        .getByRole('button', {
          name: `Activar empleado ${nombres} Unificacion`,
          exact: true,
        })
        .click()
      const modalReactivarEmpleado = page.getByRole('dialog')
      const respuestaReactivarEmpleado = esperarRespuesta(
        page,
        `/api/v1/empleados/${registro.idTexto}/estado`,
        'PATCH',
      )
      await modalReactivarEmpleado
        .getByRole('button', { name: 'Activar empleado', exact: true })
        .click()
      expect((await respuestaReactivarEmpleado).status()).toBe(200)
      await abrirAdministracionEmpleado(page, `${nombres} Unificacion`)
      await expect(
        page.getByRole('dialog').locator('dd').filter({ hasText: 'Desactivada' }),
      ).toBeVisible()
      await expect(
        page.getByText('Reactivar el acceso conserva la misma cuenta', { exact: false }),
      ).toBeVisible()
      await page.keyboard.press('Escape')
    } finally {
      await contextoDesactivacionEmpleado.context.close()
    }

    let solicitudesDocumento = 0
    const observarDocumento = (solicitud: import('@playwright/test').Request) => {
      if (
        solicitud.isNavigationRequest() &&
        solicitud.resourceType() === 'document' &&
        solicitud.frame() === page.mainFrame()
      ) {
        solicitudesDocumento += 1
      }
    }
    page.on('request', observarDocumento)
    const respuestaDirectorioOperadores = esperarRespuesta(page, '/api/v1/operadores', 'GET')
    await page.getByRole('link', { name: 'Operadores', exact: true }).click()
    await expect(page).toHaveURL(/\/admin\/operadores$/)
    expect((await respuestaDirectorioOperadores).status()).toBe(200)
    const respuestaDirectorioEmpleados = esperarRespuesta(page, '/api/v1/empleados', 'GET')
    await page.getByRole('link', { name: 'Empleados', exact: true }).click()
    await expect(page).toHaveURL(/\/admin\/empleados$/)
    expect((await respuestaDirectorioEmpleados).status()).toBe(200)
    page.off('request', observarDocumento)
    expect(solicitudesDocumento).toBe(0)

    const nombreConflicto = `Conflicto-${sufijo}`
    const mensajesAntesConflicto = await contarMensajes()
    const conflicto = await registrarEmpleado(page, nombreConflicto, 'Correo', correoDueno)
    await abrirAdministracionEmpleado(page, `${nombreConflicto} Correo`)
    const dialogoConflicto = page.getByRole('dialog')
    const respuestaConflicto = esperarRespuesta(
      page,
      `/api/v1/empleados/${conflicto.idTexto}/operador/promocion`,
      'POST',
    )
    await dialogoConflicto
      .getByRole('button', { name: 'Crear cuenta de operador', exact: true })
      .click()
    await dialogoConflicto
      .getByRole('group', { name: 'Confirmar acción' })
      .getByRole('button', { name: 'Confirmar', exact: true })
      .click()
    expect((await respuestaConflicto).status()).toBe(409)
    await expect(
      dialogoConflicto.locator('dd').filter({ hasText: 'Sin cuenta de operador' }),
    ).toBeVisible()
    await page.keyboard.press('Escape')
    await expect.poll(contarMensajes).toBe(mensajesAntesConflicto)

    const conciliacionContexto = await crearContextoDuenoApi(browser, correoDueno, contrasenaDueno)
    try {
      const datosPreservacion = await conciliacionContexto.api.get(
        `${API}/api/v1/__sandbox/unificacion/preservacion-rfid/${fixture.fixtureId}`,
      )
      expect(datosPreservacion.status()).toBe(200)
      const preservacion = (await datosPreservacion.json()) as Record<string, boolean>
      expect(Object.values(preservacion).every(Boolean)).toBe(true)
    } finally {
      await conciliacionContexto.context.close()
    }

    await page.goto(`${baseURL}/admin/operadores`)
    await esperarVueMontada(page)
    await page.getByLabel('Buscar por nombre o apellido').fill(fixture.operadorNombre)
    await page
      .getByRole('button', {
        name: `Vincular la cuenta de ${fixture.operadorNombre} con un empleado`,
        exact: true,
      })
      .click()
    const dialogoConciliacion = page.getByRole('dialog')
    const selectorEmpleado = dialogoConciliacion.getByLabel('Empleado disponible')
    await selectorEmpleado.click()
    await page.getByRole('option', { name: new RegExp(fixture.empleadoNombre) }).click()
    await expect(dialogoConciliacion.getByText('Empleado seleccionado')).toBeVisible()
    const casillaPar = dialogoConciliacion.getByRole('checkbox', { name: /Confirmo vincular/ })
    const casillaCorreo = dialogoConciliacion.getByRole('checkbox', {
      name: 'Autorizo copiar el correo de la cuenta al empleado, que no tiene uno.',
    })
    await casillaPar.check()
    await casillaCorreo.check()
    const mensajesAntesConciliar = await contarMensajes()
    const respuestaVinculo = page.waitForResponse((respuesta) => {
      const url = new URL(respuesta.url())
      return (
        respuesta.request().method() === 'POST' &&
        /^\/api\/v1\/empleados\/\d+\/operador\/vinculacion$/.test(url.pathname)
      )
    })
    await dialogoConciliacion.getByRole('button', { name: 'Vincular cuenta', exact: true }).click()
    expect((await respuestaVinculo).status()).toBe(200)
    await expect.poll(contarMensajes).toBe(mensajesAntesConciliar)

    const contextoVerificacion = await crearContextoDuenoApi(browser, correoDueno, contrasenaDueno)
    try {
      const preservacionFinal = await contextoVerificacion.api.get(
        `${API}/api/v1/__sandbox/unificacion/preservacion-rfid/${fixture.fixtureId}`,
      )
      expect(preservacionFinal.status()).toBe(200)
      const resultadoPreservacion = (await preservacionFinal.json()) as Record<string, boolean>
      expect(Object.values(resultadoPreservacion).every(Boolean)).toBe(true)
    } finally {
      await contextoVerificacion.context.close()
    }
    await expect(page.getByRole('row', { name: new RegExp(fixture.operadorNombre) })).toContainText(
      'Vinculado',
    )
  } finally {
    await contextoSse.close()
  }
})

test('añade operadores desde su directorio con búsqueda, correo único e invitación', async ({
  page,
}) => {
  test.setTimeout(180_000)
  const sufijo = randomUUID().slice(0, 10)
  const nombreSinCorreo = `Alta-${sufijo}-SinCorreo`
  const nombreConCorreo = `Alta-${sufijo}-ConCorreo`
  const correoExistente = `empleado-${sufijo}@example.test`
  const correoActualizado = `operador-${sufijo}@example.test`
  const correoSinCorreo = `nuevo-${sufijo}@example.test`
  const mensajesAntes = await contarMensajes()

  await iniciarSesion(page)
  await abrirEmpleados(page)
  const empleadoSinCorreo = await registrarEmpleado(page, nombreSinCorreo, 'Alta')
  const empleadoConCorreo = await registrarEmpleado(page, nombreConCorreo, 'Alta', correoExistente)

  await page.addInitScript(() => {
    type VentanaConEventos = Window & { __eventosSseAlta?: string[] }
    const ventana = window as VentanaConEventos
    ventana.__eventosSseAlta = []
    const FuenteOriginal = window.EventSource
    window.EventSource = class extends FuenteOriginal {
      constructor(url: string | URL, opciones?: EventSourceInit) {
        super(url, opciones)
        for (const nombre of [
          'empleado.directorio.actualizado',
          'operador.directorio.actualizado',
        ]) {
          this.addEventListener(nombre, () => ventana.__eventosSseAlta?.push(nombre))
        }
      }
    }
  })
  const lecturasOperadores: number[] = []
  page.on('response', (respuesta) => {
    const url = new URL(respuesta.url())
    if (respuesta.request().method() === 'GET' && url.pathname === '/api/v1/operadores') {
      lecturasOperadores.push(respuesta.status())
    }
  })
  await page.goto(`${baseURL}/admin/operadores`)
  await esperarVueMontada(page)
  await expect(page.getByRole('region', { name: 'Lista de operadores' }).first()).toBeVisible()

  const paginaEmpleados = await page.context().newPage()
  try {
    await paginaEmpleados.addInitScript(() => {
      type VentanaConEventos = Window & { __eventosSseAlta?: string[] }
      const ventana = window as VentanaConEventos
      ventana.__eventosSseAlta = []
      const FuenteOriginal = window.EventSource
      window.EventSource = class extends FuenteOriginal {
        constructor(url: string | URL, opciones?: EventSourceInit) {
          super(url, opciones)
          this.addEventListener('empleado.directorio.actualizado', () =>
            ventana.__eventosSseAlta?.push('empleado.directorio.actualizado'),
          )
        }
      }
    })
    const lecturasEmpleados: number[] = []
    paginaEmpleados.on('response', (respuesta) => {
      const url = new URL(respuesta.url())
      if (respuesta.request().method() === 'GET' && url.pathname === '/api/v1/empleados') {
        lecturasEmpleados.push(respuesta.status())
      }
    })
    const conexionSse = esperarRespuesta(paginaEmpleados, '/api/v1/eventos/administracion', 'GET')
    await paginaEmpleados.goto(`${baseURL}/admin/empleados`)
    expect((await conexionSse).status()).toBe(200)
    await esperarVueMontada(paginaEmpleados)
    await expect(
      paginaEmpleados.getByRole('region', { name: 'Lista de empleados' }).first(),
    ).toBeVisible()
    const lecturasInicialesEmpleados = lecturasEmpleados.length
    const lecturasInicialesOperadores = lecturasOperadores.length

    await page.getByRole('button', { name: 'Añadir operador', exact: true }).click()
    const dialogo = page.getByRole('dialog')
    await expect(dialogo.getByRole('heading', { name: 'Añadir operador' })).toBeVisible()
    await dialogo.getByLabel('Buscar empleado').fill(empleadoSinCorreo.codigo)
    const opcionSinCorreo = dialogo.getByRole('button', {
      name: new RegExp(empleadoSinCorreo.codigo),
    })
    await expect(opcionSinCorreo).toBeVisible()
    await opcionSinCorreo.click()
    const campoCorreo = dialogo.getByLabel('Correo para la cuenta y la invitación')
    await expect(campoCorreo).toHaveValue('')
    await campoCorreo.fill(correoSinCorreo)

    const solicitudesCorreoSeparado: string[] = []
    page.on('request', (solicitud) => {
      const url = new URL(solicitud.url())
      if (solicitud.method() === 'PATCH' && url.pathname.endsWith('/correo')) {
        solicitudesCorreoSeparado.push(url.pathname)
      }
    })
    const peticionPromocion = esperarSolicitud(
      page,
      `/api/v1/empleados/${empleadoSinCorreo.idTexto}/operador/promocion`,
      'POST',
    )
    const respuestaPromocion = esperarRespuesta(
      page,
      `/api/v1/empleados/${empleadoSinCorreo.idTexto}/operador/promocion`,
      'POST',
    )
    await dialogo
      .getByRole('button', { name: 'Crear cuenta y enviar invitación', exact: true })
      .click()
    const [solicitud, respuesta] = await Promise.all([peticionPromocion, respuestaPromocion])
    expect(respuesta.status()).toBe(200)
    expect(solicitud.postDataJSON()).toEqual({ correo: correoSinCorreo })
    expect(solicitud.headers()['if-match']).toMatch(/^"\d+"$/)
    expect(solicitud.headers()['idempotency-key']).toMatch(/^[0-9a-f-]{36}$/i)
    expect(solicitud.headers()['x-csrf-token']).toBeTruthy()
    expect(solicitudesCorreoSeparado).toEqual([])

    const resultadoPromocion = (await respuesta.json()) as {
      operadorId: string
      estadoOperador: string
      estadoInvitacion: string
    }
    expect(/^[0-9a-f-]{36}$/i.test(resultadoPromocion.operadorId)).toBe(true)
    expect(resultadoPromocion.estadoOperador).toBe('PENDIENTE')
    expect(resultadoPromocion.estadoInvitacion).toBe('ENVIADO')
    await expect
      .poll(() =>
        paginaEmpleados.evaluate(
          () => (window as Window & { __eventosSseAlta?: string[] }).__eventosSseAlta ?? [],
        ),
      )
      .toContain('empleado.directorio.actualizado')
    await expect
      .poll(() =>
        page.evaluate(
          () => (window as Window & { __eventosSseAlta?: string[] }).__eventosSseAlta ?? [],
        ),
      )
      .toContain('operador.directorio.actualizado')
    await expect.poll(() => lecturasEmpleados.length).toBeGreaterThan(lecturasInicialesEmpleados)
    await expect.poll(() => lecturasOperadores.length).toBeGreaterThan(lecturasInicialesOperadores)
    await esperarCorreo(correoSinCorreo, ASUNTO_ACTIVACION)
    await expect.poll(contarMensajes).toBe(mensajesAntes + 1)

    await page.getByRole('button', { name: 'Añadir operador', exact: true }).click()
    const dialogoDuplicado = page.getByRole('dialog')
    await dialogoDuplicado.getByLabel('Buscar empleado').fill(empleadoSinCorreo.codigo)
    await expect(
      dialogoDuplicado.getByText('No encontramos empleados disponibles con esos datos.'),
    ).toBeVisible()
    await dialogoDuplicado.getByRole('button', { name: 'Cancelar', exact: true }).click()

    await page.getByRole('button', { name: 'Añadir operador', exact: true }).click()
    const dialogoConCorreo = page.getByRole('dialog')
    await dialogoConCorreo.getByLabel('Buscar empleado').fill(nombreConCorreo)
    const opcionConCorreo = dialogoConCorreo.getByRole('button', {
      name: new RegExp(nombreConCorreo),
    })
    await expect(opcionConCorreo).toBeVisible()
    await opcionConCorreo.click()
    const campoCorreoExistente = dialogoConCorreo.getByLabel(
      'Correo para la cuenta y la invitación',
    )
    await expect(campoCorreoExistente).toHaveValue(correoExistente)
    await campoCorreoExistente.fill(correoActualizado)
    const rutaPromocionConCorreo = `/api/v1/empleados/${empleadoConCorreo.idTexto}/operador/promocion`
    const peticionPromocionConCorreo = esperarSolicitud(page, rutaPromocionConCorreo, 'POST')
    const respuestaPromocionConCorreo = esperarRespuesta(page, rutaPromocionConCorreo, 'POST')
    const lecturasEmpleadosTrasPrimera = lecturasEmpleados.length
    const lecturasOperadoresTrasPrimera = lecturasOperadores.length
    await dialogoConCorreo
      .getByRole('button', { name: 'Crear cuenta y enviar invitación', exact: true })
      .click()
    const [solicitudConCorreo, respuestaConCorreo] = await Promise.all([
      peticionPromocionConCorreo,
      respuestaPromocionConCorreo,
    ])
    expect(respuestaConCorreo.status()).toBe(200)
    expect(solicitudConCorreo.postDataJSON()).toEqual({ correo: correoActualizado })
    expect(solicitudConCorreo.headers()['if-match']).toMatch(/^"\d+"$/)
    expect(solicitudConCorreo.headers()['idempotency-key']).toMatch(/^[0-9a-f-]{36}$/i)
    expect(solicitudConCorreo.headers()['x-csrf-token']).toBeTruthy()
    expect(solicitudesCorreoSeparado).toEqual([])
    const resultadoConCorreo = (await respuestaConCorreo.json()) as {
      estadoOperador: string
      estadoInvitacion: string
    }
    expect(resultadoConCorreo.estadoOperador).toBe('PENDIENTE')
    expect(resultadoConCorreo.estadoInvitacion).toBe('ENVIADO')
    const datosCuenta = await page.evaluate(async (idTexto) => {
      const respuestaDetalle = await fetch(`/api/v1/empleados/${idTexto}`, { cache: 'no-store' })
      return (await respuestaDetalle.json()) as {
        correo: string | null
        operador: { estado: string } | null
      }
    }, empleadoConCorreo.idTexto)
    expect(datosCuenta.correo).toBe(correoActualizado)
    expect(datosCuenta.operador?.estado).toBe('PENDIENTE')
    await esperarCorreo(correoActualizado, ASUNTO_ACTIVACION)
    await expect.poll(contarMensajes).toBe(mensajesAntes + 2)
    await expect.poll(() => lecturasEmpleados.length).toBeGreaterThan(lecturasEmpleadosTrasPrimera)
    await expect
      .poll(() => lecturasOperadores.length)
      .toBeGreaterThan(lecturasOperadoresTrasPrimera)
  } finally {
    await paginaEmpleados.close()
  }
})

async function abrirEmpleados(page: Page, empleadoReciente?: string): Promise<void> {
  await page.goto(`${baseURL}/admin/empleados`)
  await esperarVueMontada(page)
  await expect(page.getByRole('region', { name: 'Lista de empleados' }).first()).toBeVisible()
  if (empleadoReciente) {
    const textoTotal = await page.locator('.resumen-directorio > span').textContent()
    const total = Number(textoTotal?.match(/^\s*(\d+)/)?.[1])
    expect(Number.isSafeInteger(total) && total > 0).toBe(true)
    const paginaFinal = Math.ceil(total / 10)
    if (paginaFinal > 1) await page.goto(`${baseURL}/admin/empleados?pagina=${paginaFinal}`)
    await expect(page.getByRole('row', { name: new RegExp(empleadoReciente) })).toBeVisible()
  }
}

async function prepararDuenoSintetico(
  browser: Browser,
  correo: string,
  contrasena: string,
): Promise<void> {
  const contexto = await browser.newContext()
  try {
    const api = contexto.request
    const estadoRespuesta = await api.get(`${API}/api/v1/configuracion/estado`)
    expect(estadoRespuesta.status()).toBe(200)
    const estado = (await estadoRespuesta.json()) as { estado?: string }
    if (estado.estado === 'SIN_CONFIGURAR') {
      const respuestaCsrf = await api.get(`${API}/api/v1/csrf`)
      expect(respuestaCsrf.status()).toBe(200)
      const csrf = String(((await respuestaCsrf.json()) as { token?: string }).token ?? '')
      expect(csrf).not.toBe('')
      const configuracion = await api.post(`${API}/api/v1/configuracion/inicial`, {
        data: {
          propietario: {
            nombres: 'Propietario',
            primerApellido: 'Sintetico',
            segundoApellido: null,
            correo,
            contrasenaAcceso: contrasena,
            contrasenaAdministrativa: `Administrativa-${randomUUID()}!`,
          },
          estacionamiento: {
            nombre: 'Estacionamiento de prueba',
            tipo: 'PRIVADO',
            horario: {
              modo: 'CONTINUO_24_7',
              zonaHoraria: 'America/Mexico_City',
              horaApertura: null,
              horaCierre: null,
            },
          },
        },
        headers: {
          'X-CSRF-TOKEN': csrf,
          'Idempotency-Key': randomUUID(),
        },
      })
      expect(configuracion.status()).toBe(201)
      const resultado = (await configuracion.json()) as { estado?: string }
      expect(resultado.estado).toBe('CONFIGURADA')
    } else {
      expect(estado.estado).toBe('CONFIGURADA')
    }

    const propietario = await crearContextoDuenoApi(browser, correo, contrasena)
    await propietario.context.close()
  } finally {
    await contexto.close()
  }
}

async function registrarEmpleado(
  page: Page,
  nombres: string,
  primerApellido: string,
  correo?: string,
): Promise<{ idTexto: string; codigo: string }> {
  const totalAntesTexto = await page.locator('.resumen-directorio > span').textContent()
  const totalAntes = Number(totalAntesTexto?.match(/^\s*(\d+)/)?.[1])
  expect(Number.isSafeInteger(totalAntes)).toBe(true)
  await page.getByRole('button', { name: 'Agregar empleado', exact: true }).first().click()
  const dialogo = page.getByRole('dialog')
  await dialogo.getByLabel('Nombres').fill(nombres)
  await dialogo.getByLabel('Primer apellido').fill(primerApellido)
  if (correo) await dialogo.getByLabel('Correo (opcional)').fill(correo)

  const formulario = dialogo.locator('form')
  const solicitudPromise = esperarSolicitud(page, '/api/v1/empleados', 'POST')
  const respuestaPromise = esperarRespuesta(page, '/api/v1/empleados', 'POST')
  await dialogo.getByRole('button', { name: 'Agregar', exact: true }).click()
  await expect(formulario).toHaveAttribute('aria-busy', 'true')
  const [solicitud, respuesta] = await Promise.all([solicitudPromise, respuestaPromise])
  expect(respuesta.status()).toBe(201)
  const cuerpo = solicitud.postDataJSON() as Record<string, unknown>
  if (correo) expect(cuerpo.correo === correo).toBe(true)
  else expect(Object.hasOwn(cuerpo, 'correo')).toBe(false)
  const recibo = (await respuesta.json()) as { idTexto?: string; codigo?: string }
  const idTexto = String(recibo.idTexto ?? '')
  const codigo = String(recibo.codigo ?? '')
  expect(/^\d+$/.test(idTexto)).toBe(true)
  await expect
    .poll(async () => {
      const totalTexto = await page.locator('.resumen-directorio > span').textContent()
      return Number(totalTexto?.match(/^\s*(\d+)/)?.[1])
    })
    .toBe(totalAntes + 1)
  const paginaFinal = Math.max(1, Math.ceil((totalAntes + 1) / 10))
  const paginaActual = new URL(page.url()).searchParams.get('pagina')
  if (paginaFinal > 1 && paginaActual !== String(paginaFinal)) {
    await page.goto(`${baseURL}/admin/empleados?pagina=${paginaFinal}`)
  }
  await expect(page.getByRole('row', { name: new RegExp(nombres) })).toBeVisible()
  return { idTexto, codigo }
}

async function abrirAdministracionEmpleado(page: Page, nombreCompleto: string): Promise<void> {
  await page
    .getByRole('button', {
      name: `Administrar cuenta de ${nombreCompleto}`,
      exact: true,
    })
    .click()
  await expect(
    page.getByRole('dialog').getByRole('heading', { name: 'Administrar empleado' }),
  ).toBeVisible()
}

async function activarDesdeCorreo(
  page: Page,
  destinatario: string,
  asunto: string,
  contrasena: string,
): Promise<void> {
  const texto = await esperarCorreo(destinatario, asunto)
  const coincidencia = texto.match(/https?:\/\/[^\s<#]+\/activar-operador#[A-Za-z0-9_-]{43}/)
  if (!coincidencia) throw new Error('Mailpit no contiene el enlace de activación sintético.')
  const enlace = new URL(coincidencia[0])
  const origenWeb = new URL(baseURL)
  const destinoInterno = `${origenWeb.origin}${enlace.pathname}${enlace.hash}`
  const respuesta = await page.goto(destinoInterno)
  expect(respuesta?.status() === 200).toBe(true)
  const html = await respuesta!.text()
  const token = enlace.hash.slice(1)
  expect(html.includes(token)).toBe(false)
  await expect(page.getByRole('heading', { name: 'Activar cuenta' })).toBeVisible()
  await expect.poll(() => new URL(page.url()).hash).toBe('')
  expect((await page.content()).includes(token)).toBe(false)
  const datosHidratados = await page.locator('#__NUXT_DATA__').textContent()
  expect(Boolean(datosHidratados?.includes(token))).toBe(false)
  await page.getByLabel('Contraseña', { exact: true }).fill(contrasena)
  await page.getByLabel('Confirmar contraseña').fill(contrasena)
  await page.getByRole('button', { name: 'Activar cuenta', exact: true }).click()
}

async function iniciarRecuperacion(
  page: Page,
  idOperador: string,
  destinatario: string,
): Promise<string> {
  const api = page.context().request
  const detalle = await api.get(`${baseURL}/api/v1/operadores/${idOperador}`)
  expect(detalle.status()).toBe(200)
  const etiqueta = detalle.headers()['etag']
  expect(/^"\d+"$/.test(etiqueta ?? '')).toBe(true)
  const csrf = await obtenerCsrf(page.context().request)
  const solicitud = await api.post(`${baseURL}/api/v1/operadores/${idOperador}/recuperacion`, {
    headers: {
      'X-CSRF-TOKEN': csrf,
      'If-Match': etiqueta,
      'Idempotency-Key': randomUUID(),
    },
  })
  expect(solicitud.status()).toBe(200)
  const texto = await esperarCorreo(destinatario, ASUNTO_RECUPERACION)
  const token = texto.match(/https?:\/\/[^\s<#]+\/restablecer-contrasena#([A-Za-z0-9_-]{43})/)?.[1]
  if (!token) throw new Error('Mailpit no contiene el enlace de recuperación sintético.')
  const validar = await api.post(`${baseURL}/api/v1/operadores/recuperacion/validar`, {
    data: { token },
    headers: { 'X-CSRF-TOKEN': csrf },
  })
  expect(validar.status()).toBe(200)
  return token
}

async function comprobarTokenRecuperacionRevocado(page: Page, token: string): Promise<void> {
  const csrf = await obtenerCsrf(page.context().request)
  const validar = await page
    .context()
    .request.post(`${baseURL}/api/v1/operadores/recuperacion/validar`, {
      data: { token },
      headers: { 'X-CSRF-TOKEN': csrf },
    })
  expect(validar.status() !== 200).toBe(true)
}

async function comprobarLoginOperadorRechazado(
  browser: Browser,
  correo: string,
  contrasena: string,
): Promise<void> {
  const contexto = await browser.newContext()
  try {
    const api = contexto.request
    const csrf = await api.get(`${API}/api/v1/csrf`)
    expect(csrf.status()).toBe(200)
    const token = (await csrf.json()).token as string
    const login = await api.post(`${API}/api/v1/sesion`, {
      data: { correo, contrasena },
      headers: { 'X-CSRF-TOKEN': token },
    })
    expect(login.status()).toBe(401)
  } finally {
    await contexto.close()
  }
}

async function crearContextoDuenoApi(
  browser: Browser,
  correo: string,
  contrasena: string,
): Promise<{ context: BrowserContext; api: APIRequestContext; csrf: string }> {
  const context = await browser.newContext()
  const api = context.request
  const csrfInicial = await api.get(`${API}/api/v1/csrf`)
  expect(csrfInicial.status()).toBe(200)
  const token = (await csrfInicial.json()).token as string
  const login = await api.post(`${API}/api/v1/sesion`, {
    data: { correo, contrasena },
    headers: { 'X-CSRF-TOKEN': token },
  })
  expect(login.status()).toBe(200)
  const csrfActivo = (await login.json()).csrfToken as string
  return { context, api, csrf: csrfActivo }
}

async function convertirSesionEnOperador(
  context: BrowserContext,
  idOperador: string,
): Promise<{ api: APIRequestContext }> {
  const api = context.request
  const respuesta = await api.post(
    `${API}/api/v1/__sandbox/unificacion/sesion-operador/${idOperador}`,
    {
      data: { nonce: NONCE },
      headers: { 'X-CSRF-TOKEN': await obtenerCsrfApi(api) },
    },
  )
  expect(respuesta.status()).toBe(200)
  return { api }
}

async function comprobarSesionOperadorYPermisos(api: APIRequestContext): Promise<void> {
  const sesion = await api.get(`${API}/api/v1/sesion`)
  expect(sesion.status()).toBe(200)
  const identidad = await sesion.json()
  expect(identidad.autenticada === true && identidad.rol === 'OPERADOR').toBe(true)
  const csrf = await obtenerCsrfApi(api)
  const prohibida = await api.post(`${API}/api/v1/empleados`, {
    data: { nombres: 'No autorizado', primerApellido: 'E2E' },
    headers: { 'X-CSRF-TOKEN': csrf, 'Idempotency-Key': randomUUID() },
  })
  expect(prohibida.status()).toBe(403)
}

async function comprobarSesionRevocada(api: APIRequestContext): Promise<void> {
  const protegida = await api.get(`${API}/api/v1/empleados`)
  expect(protegida.status()).toBe(401)
  const sesion = await api.get(`${API}/api/v1/sesion`)
  if (sesion.status() === 200) {
    const identidad = await sesion.json()
    expect(identidad.autenticada === false).toBe(true)
  } else {
    expect(sesion.status() === 401).toBe(true)
  }
}

async function comprobarDuenoSigueActivo(page: Page): Promise<void> {
  const sesion = await page.context().request.get(`${baseURL}/api/v1/sesion`)
  expect(sesion.status()).toBe(200)
  const identidad = await sesion.json()
  expect(identidad.autenticada === true && identidad.rol === 'DUENO').toBe(true)
}

async function obtenerCsrf(api: APIRequestContext): Promise<string> {
  const respuesta = await api.get(`${baseURL}/api/v1/csrf`)
  expect(respuesta.status()).toBe(200)
  return String((await respuesta.json()).token)
}

async function obtenerCsrfApi(api: APIRequestContext): Promise<string> {
  const respuesta = await api.get(`${API}/api/v1/csrf`)
  expect(respuesta.status()).toBe(200)
  return String((await respuesta.json()).token)
}

async function esperarCorreo(destinatario: string, asunto: string): Promise<string> {
  let texto = ''
  await expect
    .poll(
      async () => {
        texto = await leerCorreo(destinatario, asunto)
        return texto.length > 0
      },
      { timeout: 20_000 },
    )
    .toBe(true)
  return texto
}

async function leerCorreo(destinatario: string, asunto: string): Promise<string> {
  const respuestaListado = await fetch(`${MAILPIT}/api/v1/messages?limit=100`)
  if (!respuestaListado.ok) return ''
  const listado = (await respuestaListado.json()) as {
    messages?: Array<{
      ID?: string
      Subject?: string
      To?: Array<{ Address?: string }>
    }>
  }
  const mensaje = (listado.messages ?? []).find(
    (elemento) =>
      elemento.Subject === asunto &&
      elemento.To?.some((direccion) => direccion.Address === destinatario),
  )
  if (!mensaje?.ID) return ''
  const respuestaDetalle = await fetch(
    `${MAILPIT}/api/v1/message/${encodeURIComponent(mensaje.ID)}`,
  )
  if (!respuestaDetalle.ok) return ''
  const detalle = (await respuestaDetalle.json()) as { Text?: string; HTML?: string }
  return `${detalle.Text ?? ''}\n${detalle.HTML ?? ''}`
}

async function contarMensajes(): Promise<number> {
  const respuesta = await fetch(`${MAILPIT}/api/v1/messages?limit=1`)
  if (!respuesta.ok) throw new Error('Mailpit sintético no está disponible.')
  const listado = (await respuesta.json()) as {
    total?: number
    Total?: number
    messages?: unknown[]
  }
  return Number(listado.total ?? listado.Total ?? listado.messages?.length ?? 0)
}

async function abrirEmpleadosSinRecargar(page: Page): Promise<void> {
  const enlace = page.getByRole('link', { name: 'Empleados', exact: true })
  await enlace.click()
  await expect(page).toHaveURL(/\/admin\/empleados$/)
  await expect(page.getByRole('region', { name: 'Lista de empleados' }).first()).toBeVisible()
}

async function esperarVueMontada(page: Page): Promise<void> {
  await page.waitForFunction(() => {
    const raiz = document.querySelector('#__nuxt') as
      | (HTMLElement & { __vue_app__?: unknown })
      | null
    return Boolean(raiz?.__vue_app__)
  })
}

function esperarRespuesta(page: Page, ruta: string, metodo: string) {
  return page.waitForResponse((respuesta) => {
    const url = new URL(respuesta.url())
    return url.pathname === ruta && respuesta.request().method() === metodo
  })
}

function esperarSolicitud(page: Page, ruta: string, metodo: string) {
  return page.waitForRequest((solicitud) => {
    const url = new URL(solicitud.url())
    return url.pathname === ruta && solicitud.method() === metodo
  })
}
