import { randomUUID } from 'node:crypto'
import { access, writeFile } from 'node:fs/promises'
import { expect, test, type Page, type PlaywrightRequest } from '@playwright/test'
import { baseURL, iniciarSesion } from './sesion'

type EventoObservado = { tipo: string; orden: number | null; enMs: number; tieneId: boolean }
type TelemetriaNavegador = {
  fuentes: EventSource[]
  eventos: EventoObservado[]
  aperturas: number
  cierres: number
  errores: number
  vivasMaximas: number
  cerrarTodo: () => void
  reiniciarEventos: () => void
}
declare global {
  interface Window {
    __qaPresion?: TelemetriaNavegador
  }
}

type RastreadorGet = {
  autoActivos: number
  autoMaximos: number
  autoTotal: number
  rafagaActivos: number
  rafagaMaximos: number
  rafagaTotal: number
  todosActivos: number
  todosMaximos: number
  reiniciar(): void
}
type Observacion = {
  estadoHttp: number
  inicioMs: number
  finMs: number
  commitMs: number | null
  estado: string
  cambio: boolean
}

const apiUrl = process.env.TEST_API_BASE_URL || ''
const fixtureUrl = process.env.QA_VISION_FIXTURE_URL || ''
const counterUrl = (process.env.TEST_VISION_COUNTER_URL || '').replace(/\/__conteo\/?$/, '')
const sourceId = process.env.QA_VISION_SOURCE_ID || ''
const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const pausa = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

async function instrumentar(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const datos: TelemetriaNavegador = {
      fuentes: [],
      eventos: [],
      aperturas: 0,
      cierres: 0,
      errores: 0,
      vivasMaximas: 0,
      cerrarTodo: () => {},
      reiniciarEventos: () => {},
    }
    const cerradas = new WeakSet<EventSource>()
    const Original = window.EventSource
    const guardar = (tipo: string, evento: Event) => {
      const mensaje = evento as MessageEvent
      const id = typeof mensaje.lastEventId === 'string' ? mensaje.lastEventId : ''
      const coincidencia = /(?:^|:)(\d+)$/.exec(id)
      datos.eventos.push({
        tipo,
        orden: coincidencia ? Number(coincidencia[1]) : null,
        enMs: Date.now(),
        tieneId: Boolean(id),
      })
      if (datos.eventos.length > 4096) datos.eventos.splice(0, datos.eventos.length - 4096)
    }
    class EventSourceMedido extends Original {
      constructor(url: string | URL, opciones?: EventSourceInit) {
        super(url, opciones)
        datos.aperturas += 1
        datos.fuentes.push(this)
        datos.vivasMaximas = Math.max(
          datos.vivasMaximas,
          datos.fuentes.filter((fuente) => fuente.readyState !== EventSource.CLOSED).length,
        )
        this.addEventListener('vision.ocupacion.actualizada', (evento) =>
          guardar('vision.ocupacion.actualizada', evento),
        )
        this.addEventListener('empleado.directorio.actualizado', (evento) =>
          guardar('empleado.directorio.actualizado', evento),
        )
        this.addEventListener('empleado.heartbeat', (evento) => guardar('empleado.heartbeat', evento))
        this.addEventListener('error', () => {
          datos.errores += 1
        })
      }
      close(): void {
        if (!cerradas.has(this)) {
          cerradas.add(this)
          datos.cierres += 1
        }
        super.close()
      }
    }
    window.EventSource = EventSourceMedido
    datos.cerrarTodo = () => {
      for (const fuente of datos.fuentes) fuente.close()
    }
    datos.reiniciarEventos = () => {
      datos.eventos.length = 0
      datos.errores = 0
    }
    window.__qaPresion = datos
  })
}

function rastrearGetVision(page: Page, todos: RastreadorGet): void {
  const pendientes = new Map<PlaywrightRequest, boolean>()
  const liberar = (solicitud: PlaywrightRequest) => {
    const rafaga = pendientes.get(solicitud)
    if (rafaga === undefined) return
    pendientes.delete(solicitud)
    if (rafaga) todos.rafagaActivos = Math.max(0, todos.rafagaActivos - 1)
    else todos.autoActivos = Math.max(0, todos.autoActivos - 1)
    todos.todosActivos = Math.max(0, todos.todosActivos - 1)
  }
  page.on('request', (solicitud) => {
    const url = new URL(solicitud.url())
    if (solicitud.method() !== 'GET' || url.pathname !== '/api/v1/vision/cajones') return
    const rafaga = solicitud.headers()['x-qa-pressure-burst'] === '1'
    pendientes.set(solicitud, rafaga)
    todos.todosActivos += 1
    todos.todosMaximos = Math.max(todos.todosMaximos, todos.todosActivos)
    if (rafaga) {
      todos.rafagaTotal += 1
      todos.rafagaActivos += 1
      todos.rafagaMaximos = Math.max(todos.rafagaMaximos, todos.rafagaActivos)
    } else {
      todos.autoTotal += 1
      todos.autoActivos += 1
      todos.autoMaximos = Math.max(todos.autoMaximos, todos.autoActivos)
    }
  })
  page.on('requestfinished', liberar)
  page.on('requestfailed', liberar)
}

async function leerTelemetria(page: Page) {
  return page.evaluate(() => {
    const datos = window.__qaPresion
    if (!datos) return null
    return {
      aperturas: datos.aperturas,
      cierres: datos.cierres,
      errores: datos.errores,
      vivasMaximas: datos.vivasMaximas,
      vivasActuales: datos.fuentes.filter((fuente) => fuente.readyState !== EventSource.CLOSED).length,
      readyStates: datos.fuentes.map((fuente) => fuente.readyState),
      eventos: datos.eventos.map((evento) => ({ ...evento })),
    }
  })
}

async function llamarBff(
  page: Page,
  ruta: string,
  metodo: string,
  datos?: unknown,
  encabezados: Record<string, string> = {},
) {
  return page.evaluate(
    async ({ ruta, metodo, datos, encabezados }) => {
      const respuesta = await fetch(ruta, {
        method: metodo,
        headers: {
          ...(datos === undefined ? {} : { 'content-type': 'application/json' }),
          ...encabezados,
        },
        body: datos === undefined ? undefined : JSON.stringify(datos),
        cache: 'no-store',
      })
      const texto = await respuesta.text()
      let cuerpo: unknown = null
      try {
        cuerpo = texto ? JSON.parse(texto) : null
      } catch {
        cuerpo = null
      }
      return { estadoHttp: respuesta.status, cuerpo }
    },
    { ruta, metodo, datos, encabezados },
  )
}

async function leerContador() {
  const respuesta = await fetch(counterUrl + '/__conteo')
  expect(respuesta.status).toBe(200)
  return await respuesta.json()
}

async function reiniciarContador(): Promise<void> {
  const respuesta = await fetch(counterUrl + '/__reiniciar-conteo', { method: 'POST' })
  expect(respuesta.status).toBe(204)
}

async function escribirMarca(nombre: string, contenido: unknown = {}): Promise<void> {
  await writeFile('/results/' + nombre, JSON.stringify(contenido), { mode: 0o600 })
}

async function esperarMarca(nombre: string, tiempoMaximoMs: number): Promise<boolean> {
  const limite = Date.now() + tiempoMaximoMs
  while (Date.now() < limite) {
    try {
      await access('/results/' + nombre)
      return true
    } catch {
      await pausa(100)
    }
  }
  return false
}

async function esperarUnaMarca(nombres: string[], tiempoMaximoMs: number): Promise<string | null> {
  const limite = Date.now() + tiempoMaximoMs
  while (Date.now() < limite) {
    for (const nombre of nombres) {
      try {
        await access('/results/' + nombre)
        return nombre
      } catch {
        // Sigue esperando una marca de control privada del host.
      }
    }
    await pausa(100)
  }
  return null
}

function percentil(valores: number[], p: number): number | null {
  if (!valores.length) return null
  const ordenados = [...valores].sort((a, b) => a - b)
  return ordenados[Math.min(ordenados.length - 1, Math.ceil(p * ordenados.length) - 1)]
}

function contarPorSegundo(eventos: EventoObservado[], inicioMs: number, tipo: string) {
  const cubetas: Record<string, number> = {}
  for (const evento of eventos) {
    if (evento.tipo !== tipo) continue
    const segundo = Math.max(0, Math.floor((evento.enMs - inicioMs) / 1000))
    const clave = String(segundo)
    cubetas[clave] = (cubetas[clave] || 0) + 1
  }
  return cubetas
}

test('presión Vision y empleados, eventos SSE y SIGTERM con stream abierto/cerrado', async ({ browser, playwright }) => {
  test.setTimeout(240_000)
  if (!uuidV4.test(sourceId) || !apiUrl || !fixtureUrl || !counterUrl)
    throw new Error('Faltan destinos o UUID sintéticos para el stack QA.')

  const contextoA = await browser.newContext()
  const contextoB = await browser.newContext()
  const paginaA = await contextoA.newPage()
  const paginaB = await contextoB.newPage()
  let apiDueno: APIRequestContext | null = null
  const rastreador: RastreadorGet = {
    autoActivos: 0,
    autoMaximos: 0,
    autoTotal: 0,
    rafagaActivos: 0,
    rafagaMaximos: 0,
    rafagaTotal: 0,
    todosActivos: 0,
    todosMaximos: 0,
    reiniciar() {
      this.autoActivos = 0
      this.autoMaximos = 0
      this.autoTotal = 0
      this.rafagaActivos = 0
      this.rafagaMaximos = 0
      this.rafagaTotal = 0
      this.todosActivos = 0
      this.todosMaximos = 0
    },
  }

  try {
    await instrumentar(paginaA)
    await instrumentar(paginaB)
    rastrearGetVision(paginaA, rastreador)
    rastrearGetVision(paginaB, rastreador)
    await iniciarSesion(paginaA)
    await iniciarSesion(paginaB)
    const cookiesA = await contextoA.cookies(baseURL)
    const cookiesB = await contextoB.cookies(baseURL)
    const sesionA = cookiesA.find((cookie) => cookie.name === 'JSESSIONID')
    const sesionB = cookiesB.find((cookie) => cookie.name === 'JSESSIONID')
    expect(Boolean(sesionA && sesionB && sesionA.value !== sesionB.value)).toBe(true)
    await Promise.all([
      paginaA.goto(baseURL + '/admin'),
      paginaB.goto(baseURL + '/admin'),
    ])
    await Promise.all([
      expect(paginaA.getByRole('region', { name: 'Ocupación física' })).toBeVisible(),
      expect(paginaB.getByRole('region', { name: 'Ocupación física' })).toBeVisible(),
    ])
    await expect.poll(async () => (await leerTelemetria(paginaA))?.vivasActuales || 0).toBeGreaterThan(0)
    await expect.poll(async () => (await leerTelemetria(paginaB))?.vivasActuales || 0).toBeGreaterThan(0)

    const csrf = await llamarBff(paginaA, '/api/v1/csrf', 'GET')
    expect(csrf.estadoHttp).toBe(200)
    const tokenCsrf = String((csrf.cuerpo as { token?: unknown })?.token || '')
    expect(tokenCsrf.length).toBeGreaterThan(10)
    apiDueno = await playwright.request.newContext({ baseURL: apiUrl })
    const csrfApi = await apiDueno.get('/api/v1/csrf')
    expect(csrfApi.status()).toBe(200)
    const tokenLoginApi = String((await csrfApi.json()).token)
    const correoDueno = process.env.TEST_OWNER_EMAIL || ''
    const contrasenaDueno = process.env.TEST_OWNER_PASSWORD || ''
    const sesionApi = await apiDueno.post('/api/v1/sesion', {
      data: { correo: correoDueno, contrasena: contrasenaDueno },
      headers: { 'X-CSRF-TOKEN': tokenLoginApi },
    })
    expect(sesionApi.status()).toBe(200)
    const csrfAutorizado = await apiDueno.get('/api/v1/csrf')
    expect(csrfAutorizado.status()).toBe(200)
    const tokenApi = String((await csrfAutorizado.json()).token)
    const idZonaC1 = randomUUID()
    const idZonaC2 = randomUUID()
    // La fuente sintética se registró durante la línea base; el preflight
    // directo a la DB QA confirmó una fila existente antes de esta repetición.
    const hashCalibracion = 'e'.repeat(64)
    const calibracion = await apiDueno.put('/api/v1/vision/fuentes/' + sourceId + '/calibracion', {
      data: {
        revisionCalibracion: 2,
        hashCalibracion,
        zonas: [
          { visionZoneId: idZonaC1, etiqueta: 'C01', cajonId: null },
          { visionZoneId: idZonaC2, etiqueta: 'C02', cajonId: null },
        ],
      },
      headers: { 'X-CSRF-TOKEN': tokenApi },
    })
    expect(calibracion.status()).toBe(200)

    const fixture = await playwright.request.newContext()
    try {
      const preparar = await fixture.post(fixtureUrl + '/__preparar', {
        data: {
          revisionCalibracion: 2,
          hashCalibracion,
          zonas: [
            { visionZoneId: idZonaC1, estado: 'LIBRE' },
            { visionZoneId: idZonaC2, estado: 'OCUPADO' },
          ],
        },
      })
      expect(preparar.status()).toBe(200)
      const preparada = await preparar.json()
      expect(preparada.ok).toBe(true)
      await pausa(1_300)
      await expect.poll(async () => (await leerContador()).eventSourcesActivos).toBe(2)

      rastreador.reiniciar()
      await paginaA.evaluate(() => window.__qaPresion?.reiniciarEventos())
      await paginaB.evaluate(() => window.__qaPresion?.reiniciarEventos())
      await reiniciarContador()
      const inicioCargaMs = Date.now()
      const observaciones: Observacion[] = []
      const empleados: Array<{ estadoHttp: number; inicioMs: number; finMs: number }> = []

      const tareaVision = (async () => {
        let estado = 'LIBRE'
        for (let indice = 0; indice < 40; indice += 1) {
          const cambio = indice % 4 !== 3
          if (cambio) estado = estado === 'LIBRE' ? 'OCUPADO' : 'LIBRE'
          const inicioMs = Date.now()
          const respuesta = await fixture.post(fixtureUrl + '/__observar', {
            data: { cambios: [{ visionZoneId: idZonaC1, estado }] },
          })
          const finMs = Date.now()
          const cuerpo = await respuesta.json()
          observaciones.push({
            estadoHttp: respuesta.status(),
            inicioMs,
            finMs,
            commitMs: typeof cuerpo.commitAt === 'string' ? Date.parse(cuerpo.commitAt) : null,
            estado,
            cambio,
          })
          if (indice < 39) await pausa(75)
        }
      })()

      const tareaEmpleados = (async () => {
        const altas = await Promise.all(
          Array.from({ length: 8 }, async (_, indice) => {
            const inicioMs = Date.now()
            const respuesta = await llamarBff(
              paginaA,
              '/api/v1/empleados',
              'POST',
              {
                nombres: 'QA Presion ' + String(indice + 1) + ' ' + randomUUID().slice(0, 8),
                primerApellido: 'Sintetico',
                segundoApellido: 'Vision',
              },
              { 'X-CSRF-TOKEN': tokenCsrf, 'Idempotency-Key': randomUUID() },
            )
            const cuerpo = respuesta.cuerpo && typeof respuesta.cuerpo === 'object'
              ? respuesta.cuerpo as Record<string, unknown>
              : {}
            const codigo = typeof cuerpo.codigo === 'string' && /^[A-Z0-9_]{1,64}$/.test(cuerpo.codigo)
              ? cuerpo.codigo
              : null
            return { estadoHttp: respuesta.estadoHttp, codigoSeguro: codigo, idempotencyKeyPresente: true, inicioMs, finMs: Date.now() }
          }),
        )
        empleados.push(...altas)
      })()

      const tareaRafagaGet = paginaA.evaluate(async () => {
        const solicitudes = Array.from({ length: 4 }, async () => {
          const respuesta = await fetch('/api/v1/vision/cajones', {
            cache: 'no-store',
            headers: { 'X-QA-Pressure-Burst': '1' },
          })
          return respuesta.status
        })
        return await Promise.all(solicitudes)
      })
      const promesasCarga = Promise.all([tareaVision, tareaEmpleados, tareaRafagaGet])
      await escribirMarca('load-v2-started.json', { inicioMs: inicioCargaMs, observaciones: 40, altasEmpleado: 8, getRafaga: 4 })
      const [, , estadosGetRafaga] = await promesasCarga
      await pausa(1_500)

      const finalVision = await llamarBff(paginaA, '/api/v1/vision/cajones', 'GET')
      expect(finalVision.estadoHttp).toBe(200)
      const cajonesFinales = Array.isArray(finalVision.cuerpo)
        ? finalVision.cuerpo as Array<Record<string, unknown>>
        : []
      const estadoFinal = Object.fromEntries(
        cajonesFinales
          .filter((cajon) => cajon.etiqueta === 'C01' || cajon.etiqueta === 'C02')
          .map((cajon) => [String(cajon.etiqueta), String(cajon.estado)]),
      )
      const datosA = await leerTelemetria(paginaA)
      const datosB = await leerTelemetria(paginaB)
      const eventosA = datosA?.eventos || []
      const eventosB = datosB?.eventos || []
      const visionA = eventosA.filter((evento) => evento.tipo === 'vision.ocupacion.actualizada')
      const empleadosA = eventosA.filter((evento) => evento.tipo === 'empleado.directorio.actualizado')
      const cambios = observaciones.filter((observacion) => observacion.cambio)
      const latenciasVision = visionA
        .slice(0, Math.min(visionA.length, cambios.length))
        .map((evento, indice) => {
          const commitMs = cambios[indice]?.commitMs
          return commitMs === null || commitMs === undefined ? NaN : evento.enMs - commitMs
        })
        .filter(Number.isFinite)
      const secuencias = eventosA.filter((evento) => evento.tipo !== 'empleado.heartbeat').map((evento) => evento.orden).filter((orden): orden is number => orden !== null)
      const eventosConOrden = eventosA.filter((evento) => evento.tipo !== 'empleado.heartbeat')
      const ordenGlobalMonotono = secuencias.length === eventosConOrden.length && secuencias.every((orden, indice) => indice === 0 || orden > secuencias[indice - 1])
      const ordenablesA = eventosA.filter((evento) => evento.tipo !== 'empleado.heartbeat')
      const ordenablesB = eventosB.filter((evento) => evento.tipo !== 'empleado.heartbeat')
      const mismoOrdenEnAmbasPestanas = ordenablesA.length === ordenablesB.length && ordenablesA.every((evento, indice) =>
        evento.tipo === ordenablesB[indice]?.tipo && evento.orden === ordenablesB[indice]?.orden,
      )
      const inicioAlta = empleados.length ? Math.min(...empleados.map((empleado) => empleado.inicioMs)) : null
      const finAlta = empleados.length ? Math.max(...empleados.map((empleado) => empleado.finMs)) : null
      const latenciasEmpleadoDesdeInicio = inicioAlta === null
        ? []
        : empleadosA.map((evento) => evento.enMs - inicioAlta)
      const contador = await leerContador()
      const resultadoPresion = {
        duracionMs: Date.now() - inicioCargaMs,
        observaciones: {
          total: observaciones.length,
          cambiantes: cambios.length,
          repetidas: observaciones.length - cambios.length,
          http200: observaciones.filter((observacion) => observacion.estadoHttp === 200).length,
          conCommitTimestamp: observaciones.filter((observacion) => observacion.commitMs !== null).length,
        },
        eventosVisionPorSegundo: contarPorSegundo(eventosA, inicioCargaMs, 'vision.ocupacion.actualizada'),
        eventosEmpleadoPorSegundo: contarPorSegundo(eventosA, inicioCargaMs, 'empleado.directorio.actualizado'),
        entregaVision: {
          eventosEnPestanaA: visionA.length,
          eventosEnPestanaB: eventosB.filter((evento) => evento.tipo === 'vision.ocupacion.actualizada').length,
          coincideEventosConObservacionesCambiantes: visionA.length === cambios.length,
          commitASseMs: {
            p50: percentil(latenciasVision, 0.5),
            p95: percentil(latenciasVision, 0.95),
            maximo: latenciasVision.length ? Math.max(...latenciasVision) : null,
          },
        },
        entregaAdministrativa: {
          altasSolicitadas: empleados.length,
          http201: empleados.filter((empleado) => empleado.estadoHttp === 201).length,
          distribucionHttp: Object.fromEntries([...new Set(empleados.map((empleado) => empleado.estadoHttp))].map((estado) => [String(estado), empleados.filter((empleado) => empleado.estadoHttp === estado).length])),
          camposCodigoPresentes: empleados.filter((empleado) => empleado.codigoSeguro !== null).length,
          claveIdempotenciaPresente: empleados.length > 0 && empleados.every((empleado) => empleado.idempotencyKeyPresente),
          eventosEnPestanaA: empleadosA.length,
          eventosEnPestanaB: eventosB.filter((evento) => evento.tipo === 'empleado.directorio.actualizado').length,
          coincideEventosConAltas: empleadosA.length === empleados.length,
          eventosRecibidosDuranteLote: inicioAlta === null || finAlta === null
            ? null
            : empleadosA.filter((evento) => evento.enMs >= inicioAlta && evento.enMs <= finAlta).length,
          inicioPrimeraAltaMs: inicioAlta === null ? null : inicioAlta - inicioCargaMs,
          finUltimaRespuestaMs: finAlta === null ? null : finAlta - inicioCargaMs,
          eventoDesdeInicioLoteMs: {
            minimo: latenciasEmpleadoDesdeInicio.length ? Math.min(...latenciasEmpleadoDesdeInicio) : null,
            maximo: latenciasEmpleadoDesdeInicio.length ? Math.max(...latenciasEmpleadoDesdeInicio) : null,
          },
        },
        orden: {
          idsMonotonosEnSseGlobal: ordenGlobalMonotono,
          mismasClasesYOrdenEnDosSesiones: mismoOrdenEnAmbasPestanas,
          eventosObservadosEnOrden: eventosA.map((evento) => evento.tipo),
        },
        lecturasVision: {
          maxClienteAutomaticoEntrePestanas: rastreador.autoMaximos,
          maxRafagaArtificialEnPestanaA: rastreador.rafagaMaximos,
          maxClienteTotal: rastreador.todosMaximos,
          solicitudesAutomaticas: rastreador.autoTotal,
          solicitudesRafagaArtificial: rastreador.rafagaTotal,
          respuestasRafaga: estadosGetRafaga,
          maxProxyApi: contador.maxGetVisionActivos,
        },
        eventSource: {
          pestanaA: { aperturas: datosA?.aperturas || 0, vivasMaximas: datosA?.vivasMaximas || 0, vivasActuales: datosA?.vivasActuales || 0, errores: datosA?.errores || 0 },
          pestanaB: { aperturas: datosB?.aperturas || 0, vivasMaximas: datosB?.vivasMaximas || 0, vivasActuales: datosB?.vivasActuales || 0, errores: datosB?.errores || 0 },
          maxProxyApi: contador.maxEventSourcesActivos,
          activosAlFinal: contador.eventSourcesActivos,
          solicitudesProxy: contador.solicitudesEventos,
        },
        estadoFinal: {
          cajones: estadoFinal,
          esperadoC01: observaciones.at(-1)?.estado || null,
          coincideC01: estadoFinal.C01 === observaciones.at(-1)?.estado,
        },
        contadorSseProxy: contador.conteoEventosSse,
        conteoClienteLoteNoIncluyeIdsNiCuerpos: true,
      }
      await escribirMarca('pressure-summary-v2.json', resultadoPresion)
      console.log('QA_PRESSURE_SUMMARY ' + JSON.stringify(resultadoPresion))

      const contadorAntesTerm = await leerContador()
      await escribirMarca('ready-open-v2.json', {
        enMs: Date.now(),
        eventSourcesActivos: contadorAntesTerm.eventSourcesActivos,
        streamsA: datosA?.vivasActuales || 0,
        streamsB: datosB?.vivasActuales || 0,
      })
      const openTermDone = await esperarMarca('open-term-finished-v2.json', 45_000)
      if (!openTermDone) throw new Error('Timeout esperando el SIGTERM abierto del host.')
      await pausa(500)
      const abiertoTrasTerm = {
        enMs: Date.now(),
        pestanaA: await leerTelemetria(paginaA),
        pestanaB: await leerTelemetria(paginaB),
        proxy: await leerContador(),
      }
      await escribirMarca('open-case-observed-v2.json', abiertoTrasTerm)

      const recuperacion = await esperarUnaMarca(
        ['api-restarted-v2.json', 'api-restart-skipped-v2.json', 'api-restart-failed-v2.json'],
        45_000,
      )
      if (recuperacion !== 'api-restarted-v2.json') {
        await Promise.all([
          paginaA.evaluate(() => window.__qaPresion?.cerrarTodo()),
          paginaB.evaluate(() => window.__qaPresion?.cerrarTodo()),
        ])
        await escribirMarca('closed-case-skipped-v2.json', { razon: recuperacion || 'timeout de control' })
      } else {
        const reconectado = await (async () => {
          const limite = Date.now() + 20_000
          while (Date.now() < limite) {
            const [a, b] = await Promise.all([leerTelemetria(paginaA), leerTelemetria(paginaB)])
            const listoA = Boolean(a?.readyStates.includes(1))
            const listoB = Boolean(b?.readyStates.includes(1))
            if (listoA && listoB) return true
            await pausa(200)
          }
          return false
        })()
        await Promise.all([
          paginaA.evaluate(() => window.__qaPresion?.cerrarTodo()),
          paginaB.evaluate(() => window.__qaPresion?.cerrarTodo()),
        ])
        const esperaCierre = Date.now() + 5_000
        let contadorStreamsCerrados = await leerContador()
        while (Date.now() < esperaCierre && contadorStreamsCerrados.eventSourcesActivos !== 0) {
          await pausa(100)
          contadorStreamsCerrados = await leerContador()
        }
        await Promise.all([paginaA.close(), paginaB.close()])
        await escribirMarca('ready-closed-v2.json', {
          enMs: Date.now(),
          reconectadoTrasReinicio: reconectado,
          eventSourcesActivos: contadorStreamsCerrados.eventSourcesActivos,
          maximoEventSources: contadorStreamsCerrados.maxEventSourcesActivos,
          paginasCerradas: true,
        })
        const closedTermDone = await esperarMarca('closed-term-finished-v2.json', 45_000)
        if (!closedTermDone) throw new Error('Timeout esperando el SIGTERM sin streams del host.')
        await escribirMarca('closed-case-observed-v2.json', {
          enMs: Date.now(),
          proxy: await leerContador(),
          paginasCerradas: true,
        })
      }
    } finally {
      await fixture.dispose()
    }
  } finally {
    await apiDueno?.dispose()
    await Promise.all([contextoA.close(), contextoB.close()])
  }
})
