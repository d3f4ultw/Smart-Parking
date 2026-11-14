import { randomUUID } from 'node:crypto'
import { writeFile } from 'node:fs/promises'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { baseURL, iniciarSesion } from './sesion'

type Evento = { tipo: string; orden: number | null; enMs: number }
type Telemetria = {
  fuentes: EventSource[]
  eventos: Evento[]
  aperturas: number
  abiertas: number
  abiertasEnMs: number[]
  cierres: number
  errores: number
  vivasMaximas: number
}
declare global {
  interface Window {
    __qaReconectarVision?: Telemetria
  }
}

type Conteo = {
  lecturasVision: number
  lecturasVisionDetalle: Array<{
    iniciadaEnMs: number
    completadaEnMs: number
    estadoHttp: number
    ttlMs: string | null
    estados: Array<{ etiqueta: string; estado: string; ultimoEstadoConfirmado: string | null }>
  }>
  solicitudesEventos: number
  eventSourcesActivos: number
  maxEventSourcesActivos: number
  heartbeatsObservados: number
  heartbeatsSseConId: number
  heartbeatsSseSinId: number
  cierresSseTrasHeartbeat: number
  cerrarSsePendiente: boolean
  solicitudesEventosConCursor: number
  solicitudesEventosConLastEventId: number
  solicitudesHeartbeat: number
  eventosSse: Array<{ tipo: string; orden: number | null; tieneId: boolean; enMs: number }>
  conteoEventosSse: Record<string, number>
}

type AltaMedida = { http: number; inicioMs: number; finMs: number; latenciaSseMs: number }

const apiUrl = process.env.TEST_API_BASE_URL || ''
const fixtureUrl = process.env.QA_VISION_FIXTURE_URL || ''
const counterUrl = (process.env.TEST_VISION_COUNTER_URL || '').replace(/\/__conteo\/?$/, '')
const sourceId = process.env.QA_VISION_SOURCE_ID || ''
const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const pausa = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

async function instrumentar(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const datos: Telemetria = {
      fuentes: [],
      eventos: [],
      aperturas: 0,
      abiertas: 0,
      abiertasEnMs: [],
      cierres: 0,
      errores: 0,
      vivasMaximas: 0,
    }
    const cerradas = new WeakSet<EventSource>()
    const Original = window.EventSource
    const guardar = (tipo: string, evento: Event) => {
      const mensaje = evento as MessageEvent
      const id = typeof mensaje.lastEventId === 'string' ? mensaje.lastEventId : ''
      const coincidencia = /(?:^|:)(\d+)$/.exec(id)
      datos.eventos.push({ tipo, orden: coincidencia ? Number(coincidencia[1]) : null, enMs: Date.now() })
      if (datos.eventos.length > 2048) datos.eventos.splice(0, datos.eventos.length - 2048)
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
        this.addEventListener('open', () => {
          datos.abiertas += 1
          datos.abiertasEnMs.push(Date.now())
        })
        this.addEventListener('error', () => {
          datos.errores += 1
        })
        for (const tipo of ['vision.ocupacion.actualizada', 'empleado.directorio.actualizado', 'empleado.heartbeat']) {
          this.addEventListener(tipo, (evento) => guardar(tipo, evento))
        }
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
    window.__qaReconectarVision = datos
  })
}

async function telemetria(page: Page) {
  return page.evaluate(() => {
    const datos = window.__qaReconectarVision
    if (!datos) return null
    return {
      aperturas: datos.aperturas,
      abiertas: datos.abiertas,
      abiertasEnMs: [...datos.abiertasEnMs],
      cierres: datos.cierres,
      errores: datos.errores,
      vivasMaximas: datos.vivasMaximas,
      vivasActuales: datos.fuentes.filter((fuente) => fuente.readyState !== EventSource.CLOSED).length,
      estadosReady: datos.fuentes.map((fuente) => fuente.readyState),
      eventos: datos.eventos.map((evento) => ({ ...evento })),
    }
  })
}

async function leerConteo(): Promise<Conteo> {
  const respuesta = await fetch(counterUrl + '/__conteo')
  expect(respuesta.status).toBe(200)
  return (await respuesta.json()) as Conteo
}

async function instalarFuente(playwright: import('@playwright/test').Playwright) {
  const dueno = await playwright.request.newContext({ baseURL: apiUrl })
  const fixture = await playwright.request.newContext()
  const csrf = await dueno.get('/api/v1/csrf')
  expect(csrf.status()).toBe(200)
  const tokenInicial = String((await csrf.json()).token || '')
  const login = await dueno.post('/api/v1/sesion', {
    data: {
      correo: process.env.TEST_OWNER_EMAIL || '',
      contrasena: process.env.TEST_OWNER_PASSWORD || '',
    },
    headers: { 'X-CSRF-TOKEN': tokenInicial },
  })
  expect(login.status()).toBe(200)
  const csrfDueno = await dueno.get('/api/v1/csrf')
  expect(csrfDueno.status()).toBe(200)
  const tokenDueno = String((await csrfDueno.json()).token || '')
  const idZonaC1 = process.env.QA_VISION_ZONE_C1_ID || randomUUID()
  const idZonaC2 = process.env.QA_VISION_ZONE_C2_ID || randomUUID()
  expect(uuidV4.test(idZonaC1) && uuidV4.test(idZonaC2)).toBe(true)
  if (process.env.QA_REUSE_REGISTERED_SOURCE !== 'true') {
    const fuente = await dueno.post('/api/v1/vision/fuentes', {
      data: { fuenteId: sourceId },
      headers: { 'X-CSRF-TOKEN': tokenDueno },
    })
    expect(fuente.status()).toBe(200)
  }
  const hashCalibracion = 'a'.repeat(64)
  const calibracion = await dueno.put('/api/v1/vision/fuentes/' + sourceId + '/calibracion', {
    data: {
      revisionCalibracion: 1,
      hashCalibracion,
      zonas: [
        { visionZoneId: idZonaC1, etiqueta: 'C01', cajonId: null },
        { visionZoneId: idZonaC2, etiqueta: 'C02', cajonId: null },
      ],
    },
    headers: { 'X-CSRF-TOKEN': tokenDueno },
  })
  expect(calibracion.status()).toBe(200)
  const preparada = await fixture.post(fixtureUrl + '/__preparar', {
    data: {
      revisionCalibracion: 1,
      hashCalibracion,
      zonas: [
        { visionZoneId: idZonaC1, estado: 'LIBRE' },
        { visionZoneId: idZonaC2, estado: 'OCUPADO' },
      ],
    },
  })
  expect(preparada.status()).toBe(200)
  const cuerpoPreparada = await preparada.json()
  expect(cuerpoPreparada.ok).toBe(true)
  return { dueno, fixture, idZonaC1, idZonaC2, hashCalibracion }
}

async function leerCsrfBff(page: Page): Promise<string> {
  return page.evaluate(async () => {
    const respuesta = await fetch('/api/v1/csrf', { cache: 'no-store' })
    if (!respuesta.ok) throw new Error('No se obtuvo CSRF por BFF.')
    const cuerpo = await respuesta.json()
    if (typeof cuerpo.token !== 'string') throw new Error('La respuesta CSRF no tenía token.')
    return cuerpo.token
  })
}

async function crearEmpleado(page: Page, tokenCsrf: string, prefijo: string, orden: number): Promise<AltaMedida> {
  const antes = (await telemetria(page))?.eventos.filter((evento) => evento.tipo === 'empleado.directorio.actualizado').length || 0
  const claveIdempotencia = randomUUID()
  const nombre = 'QA ' + prefijo + ' ' + orden + ' ' + randomUUID()
  const respuesta = await page.evaluate(async ({ token, clave, nombre }) => {
    const inicioMs = Date.now()
    const resultado = await fetch('/api/v1/empleados', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'X-CSRF-TOKEN': token,
        'Idempotency-Key': clave,
      },
      body: JSON.stringify({
        nombres: nombre,
        primerApellido: 'Sintetico',
        segundoApellido: 'Reconecta',
      }),
      cache: 'no-store',
    })
    return { http: resultado.status, inicioMs, finMs: Date.now() }
  }, { token: tokenCsrf, clave: claveIdempotencia, nombre })
  await expect.poll(async () => {
    const datos = await telemetria(page)
    const eventos = datos?.eventos.filter((item) => item.tipo === 'empleado.directorio.actualizado') || []
    return eventos.length > antes ? eventos[antes] || null : null
  }, { timeout: 8_000 }).toBeTruthy()
  const datosFinales = await telemetria(page)
  const eventoSse = (datosFinales?.eventos.filter((item) => item.tipo === 'empleado.directorio.actualizado') || [])[antes]!
  return { ...respuesta, latenciaSseMs: eventoSse.enMs - respuesta.inicioMs }
}

async function publicarVision(
  fixture: APIRequestContext,
  cambios: Array<{ visionZoneId: string; estado: 'LIBRE' | 'OCUPADO' }>,
) {
  const respuesta = await fixture.post(fixtureUrl + '/__observar', { data: { cambios } })
  const cuerpo = await respuesta.json()
  return { http: respuesta.status(), commitAt: typeof cuerpo.commitAt === 'string' ? cuerpo.commitAt : null }
}

async function leerSnapshotDom(page: Page) {
  return page.locator('li.cajon-vision').evaluateAll((elementos) => elementos.map((elemento) => ({
    etiqueta: elemento.querySelector('h3')?.textContent?.trim() || '',
    estado: elemento.querySelector('.estado-cajon')?.textContent?.trim() || '',
  })).sort((a, b) => a.etiqueta.localeCompare(b.etiqueta)))
}

function percentil(valores: number[], p: number): number | null {
  if (!valores.length) return null
  const ordenados = [...valores].sort((a, b) => a - b)
  return ordenados[Math.min(ordenados.length - 1, Math.ceil(p * ordenados.length) - 1)]
}

function resumirLatencias(valores: number[]) {
  return { n: valores.length, p50Ms: percentil(valores, 0.5), p95Ms: percentil(valores, 0.95), maxMs: valores.length ? Math.max(...valores) : null }
}

async function estadoSesion(page: Page) {
  return page.evaluate(async () => {
    const respuesta = await fetch('/api/v1/sesion', { cache: 'no-store' })
    let autenticada = false
    let dueno = false
    try {
      const cuerpo = await respuesta.json()
      autenticada = cuerpo?.autenticada === true
      dueno = autenticada && cuerpo?.rol === 'DUENO'
    } catch {
      // El informe guarda solo estados, no cuerpo de sesión.
    }
    return { http: respuesta.status, autenticada, dueno }
  })
}

async function escribirEvidencia(contenido: unknown) {
  await writeFile('/results/reconnect-evidence.json', JSON.stringify(contenido, null, 2) + '\n', { mode: 0o600 })
}

test('SSE Vision recupera sesión y snapshot completo tras cierre de stream y compara eventos intercalados', async ({ browser, playwright }) => {
  test.setTimeout(120_000)
    expect(Boolean(uuidV4.test(sourceId) && apiUrl && fixtureUrl && counterUrl)).toBe(true)
  const contexto = await browser.newContext()
  const page = await contexto.newPage()
  const navegaciones: string[] = []
  const respuestasGetVision: number[] = []
  await instrumentar(page)
  page.on('framenavigated', (frame) => {
    if (frame === page.mainFrame()) {
      try { navegaciones.push(new URL(frame.url()).pathname) } catch { /* Ignora navegación no HTTP. */ }
    }
  })
  page.on('response', (respuesta) => {
    try {
      if (respuesta.request().method() === 'GET' && new URL(respuesta.url()).pathname === '/api/v1/vision/cajones')
        respuestasGetVision.push(respuesta.status())
    } catch { /* Ignora responses no HTTP. */ }
  })

  let dueno: APIRequestContext | undefined
  let fixture: APIRequestContext | undefined
  try {
    const fuente = await instalarFuente(playwright)
    dueno = fuente.dueno
    fixture = fuente.fixture
    await iniciarSesion(page)
    await expect(page.getByRole('region', { name: 'Ocupación física' })).toBeVisible()
    await expect.poll(async () => (await telemetria(page))?.vivasActuales || 0, { timeout: 10_000 }).toBe(1)
    await expect.poll(async () => (await leerConteo()).eventSourcesActivos, { timeout: 10_000 }).toBe(1)
    await expect.poll(async () => (await leerSnapshotDom(page)).length, { timeout: 10_000 }).toBe(2)
    const streamInicialAntesReset = await leerConteo()
    expect(streamInicialAntesReset.eventSourcesActivos).toBe(1)
    expect(streamInicialAntesReset.solicitudesEventos).toBeGreaterThan(0)
    const resetConteo = await fetch(counterUrl + '/__reiniciar-conteo', { method: 'POST' })
    expect(resetConteo.status).toBe(204)
    expect((await leerConteo()).eventSourcesActivos).toBe(1)
    const csrf = await leerCsrfBff(page)

    const antesSinCarga = (await telemetria(page))?.eventos.length || 0
    const loteSinVision: AltaMedida[] = []
    for (let i = 0; i < 3; i += 1) {
      const medida = await crearEmpleado(page, csrf, 'sin-vision', i + 1)
      expect(medida.http).toBe(201)
      loteSinVision.push(medida)
      if (i < 2) await pausa(150)
    }
    const eventosSinCarga = ((await telemetria(page))?.eventos || []).slice(antesSinCarga)
    expect(eventosSinCarga.filter((evento) => evento.tipo === 'vision.ocupacion.actualizada')).toHaveLength(0)

    const inicioIntercalado = (await telemetria(page))?.eventos.length || 0
    const loteConVision: AltaMedida[] = []
    const resultadosVision: Array<{ http: number; commitAt: string | null }> = []
    const visionConcurrente = (async () => {
      const estados: Array<'LIBRE' | 'OCUPADO'> = ['OCUPADO', 'LIBRE', 'OCUPADO']
      for (let i = 0; i < estados.length; i += 1) {
        const datosAntes = await telemetria(page)
        const eventosAntes = datosAntes?.eventos.filter((evento) => evento.tipo === 'vision.ocupacion.actualizada').length || 0
        const estado = estados[i]!
        const resultado = await publicarVision(fixture!, [
          { visionZoneId: fuente.idZonaC1, estado },
        ])
        resultadosVision.push(resultado)
        expect(resultado.http).toBe(200)
        await expect.poll(async () => {
          const datos = await telemetria(page)
          return datos?.eventos.filter((evento) => evento.tipo === 'vision.ocupacion.actualizada').length || 0
        }, { timeout: 5_000 }).toBeGreaterThan(eventosAntes)
        if (i < estados.length - 1) await pausa(450)
      }
    })()
    const empleadosConcurrentes = (async () => {
      await pausa(200)
      for (let i = 0; i < 3; i += 1) {
        const medida = await crearEmpleado(page, csrf, 'con-vision', i + 1)
        expect(medida.http).toBe(201)
        loteConVision.push(medida)
        if (i < 2) await pausa(2_800)
      }
    })()
    await Promise.all([visionConcurrente, empleadosConcurrentes])
    const eventosIntercalados = ((await telemetria(page))?.eventos || []).slice(inicioIntercalado)
    const indiceEmpleados = eventosIntercalados.map((evento, indice) => ({ evento, indice }))
      .filter(({ evento }) => evento.tipo === 'empleado.directorio.actualizado')
      .map(({ indice }) => indice)
    const visionEntreAltas = indiceEmpleados.slice(1).map((indice, posicion) =>
      eventosIntercalados.slice(indiceEmpleados[posicion] + 1, indice)
        .some((evento) => evento.tipo === 'vision.ocupacion.actualizada'),
    )
    expect(loteConVision).toHaveLength(3)
    expect(resultadosVision).toHaveLength(3)
    expect(indiceEmpleados).toHaveLength(3)
    expect(visionEntreAltas.some(Boolean)).toBe(true)

    const apiHealthAntes = await fetch(new URL('/actuator/health', apiUrl))
    expect(apiHealthAntes.status).toBe(200)
    const conteoAntesCierre = await leerConteo()
    const estadoSesionAntes = await estadoSesion(page)
    expect(estadoSesionAntes).toEqual({ http: 200, autenticada: true, dueno: true })
    expect(conteoAntesCierre.eventSourcesActivos).toBe(1)
    const navegacionesAlCorte = [...navegaciones]
    const armada = await fetch(counterUrl + '/__armar-cierre-sse-tras-heartbeat', { method: 'POST' })
    expect(armada.status).toBe(204)
    await expect.poll(async () => (await leerConteo()).cierresSseTrasHeartbeat, { timeout: 20_000 }).toBe(1)
    await expect.poll(async () => (await leerConteo()).eventSourcesActivos, { timeout: 5_000 }).toBe(0)
    await expect.poll(async () => (await telemetria(page))?.errores || 0, { timeout: 5_000 }).toBeGreaterThan(0)
    const desconexion = await leerConteo()
    expect(desconexion.heartbeatsObservados).toBeGreaterThan(0)
    const sesionDuranteCorte = await estadoSesion(page)
    expect(sesionDuranteCorte).toEqual({ http: 200, autenticada: true, dueno: true })
    const rutaDuranteCorte = new URL(page.url()).pathname
    expect(rutaDuranteCorte).toBe('/admin')

    const eventosVisionAntesGap = desconexion.conteoEventosSse['vision.ocupacion.actualizada'] || 0
    const finalGap = await publicarVision(fixture!, [
      { visionZoneId: fuente.idZonaC1, estado: 'OCUPADO' },
      { visionZoneId: fuente.idZonaC2, estado: 'LIBRE' },
    ])
    expect(finalGap.http).toBe(200)
    const conteoTrasGap = await leerConteo()
    expect(conteoTrasGap.conteoEventosSse['vision.ocupacion.actualizada'] || 0).toBe(eventosVisionAntesGap)

    await expect.poll(async () => {
      const conteo = await leerConteo()
      return conteo.solicitudesEventos >= 1 && conteo.eventSourcesActivos === 1
    }, { timeout: 18_000 }).toBe(true)
    await expect.poll(async () => (await telemetria(page))?.abiertas || 0, { timeout: 8_000 }).toBeGreaterThanOrEqual(2)
    const datosAlReabrir = await telemetria(page)
    const reaperturaEnMs = datosAlReabrir?.abiertasEnMs.at(-1) || 0
    const commitGapMs = finalGap.commitAt ? Date.parse(finalGap.commitAt) : 0
    expect(reaperturaEnMs).toBeGreaterThan(0)
    expect(commitGapMs).toBeGreaterThan(0)
    await expect.poll(async () => {
      const conteo = await leerConteo()
      return conteo.lecturasVisionDetalle.some((lectura) =>
        lectura.iniciadaEnMs > reaperturaEnMs && lectura.iniciadaEnMs > commitGapMs,
      )
    }, { timeout: 8_000 }).toBe(true)
    await expect.poll(async () => {
      const snapshot = await leerSnapshotDom(page)
      return JSON.stringify(snapshot)
    }, { timeout: 8_000 }).toBe(JSON.stringify([
      { etiqueta: 'C01', estado: 'Ocupado' },
      { etiqueta: 'C02', estado: 'Libre' },
    ]))
    const sesionTrasReconectar = await estadoSesion(page)
    expect(sesionTrasReconectar).toEqual({ http: 200, autenticada: true, dueno: true })
    expect(new URL(page.url()).pathname).toBe('/admin')
    const datosFinales = await telemetria(page)
    const conteoFinal = await leerConteo()
    const apiHealthDespues = await fetch(new URL('/actuator/health', apiUrl))
    expect(apiHealthDespues.status).toBe(200)
    expect(datosFinales?.vivasMaximas).toBe(1)
    expect(datosFinales?.vivasActuales).toBe(1)
    expect(conteoFinal.maxEventSourcesActivos).toBe(1)
    expect(conteoFinal.cierresSseTrasHeartbeat).toBe(1)
    expect(conteoFinal.solicitudesEventos).toBeGreaterThanOrEqual(1)
    expect(conteoFinal.solicitudesEventosConCursor).toBeGreaterThanOrEqual(1)
    expect(datosFinales?.aperturas).toBeGreaterThanOrEqual(2)
    expect(datosFinales?.abiertas).toBeGreaterThanOrEqual(2)
    const timeline = datosFinales?.eventos || []
    const eventosNegocio = timeline.filter((evento) =>
      evento.tipo === 'vision.ocupacion.actualizada' || evento.tipo === 'empleado.directorio.actualizado',
    )
    const ids = eventosNegocio.filter((evento) => evento.orden !== null).map((evento) => evento.orden as number)
    const idsMonotonos = ids.every((id, indice) => indice === 0 || id > ids[indice - 1]!)
    expect(ids.length).toBe(eventosNegocio.length)
    expect(idsMonotonos).toBe(true)
    const framesProxyNegocio = conteoFinal.eventosSse.filter((evento) =>
      evento.tipo === 'vision.ocupacion.actualizada' || evento.tipo === 'empleado.directorio.actualizado',
    )
    const ordenesProxy = framesProxyNegocio.map((evento) => evento.orden)
    expect(ordenesProxy.length).toBeGreaterThan(0)
    const ordenesProxyValidas = ordenesProxy.filter((orden): orden is number => orden !== null)
    expect(ordenesProxyValidas.length).toBe(framesProxyNegocio.length)
    expect(ordenesProxyValidas.every((orden, indice) => indice === 0 || orden > ordenesProxyValidas[indice - 1]!)).toBe(true)
    const heartbeatsProxy = conteoFinal.eventosSse.filter((evento) => evento.tipo === 'empleado.heartbeat')
    expect(heartbeatsProxy.length).toBeGreaterThan(0)
    expect(conteoFinal.heartbeatsSseSinId).toBeGreaterThan(0)
    expect(conteoFinal.heartbeatsSseConId).toBe(0)
    expect(heartbeatsProxy.every((evento) => !evento.tieneId)).toBe(true)
    const snapshotProxy = conteoFinal.lecturasVisionDetalle
      .filter((lectura) => lectura.iniciadaEnMs > reaperturaEnMs && lectura.iniciadaEnMs > commitGapMs)
      .at(-1)
    expect(snapshotProxy?.estadoHttp).toBe(200)
    const cajonesSnapshot = snapshotProxy?.estados
      .filter((cajon) => cajon.etiqueta === 'C01' || cajon.etiqueta === 'C02')
      .map((cajon) => ({ etiqueta: cajon.etiqueta, estado: cajon.estado }))
      .sort((a, b) => a.etiqueta.localeCompare(b.etiqueta))
    expect(cajonesSnapshot).toEqual([
      { etiqueta: 'C01', estado: 'OCUPADO' },
      { etiqueta: 'C02', estado: 'LIBRE' },
    ])
    expect(respuestasGetVision.at(-1)).toBe(200)
    const despuesNavegaciones = [...navegaciones]
    expect(despuesNavegaciones.slice(-1)[0]).toBe('/admin')
    expect(despuesNavegaciones).toEqual(navegacionesAlCorte)

    const evidencia = {
      lotesEmpleados: {
        sinVision: {
          altasHttp: loteSinVision.map((medida) => medida.http),
          latenciaInicioPostASseMs: resumirLatencias(loteSinVision.map((medida) => medida.latenciaSseMs)),
          eventosVisionEntreAltas: false,
          timeline: eventosSinCarga.map((evento) => ({ tipo: evento.tipo, orden: evento.orden, enMs: evento.enMs })),
        },
        duranteVisionEspaciada: {
          altasHttp: loteConVision.map((medida) => medida.http),
          visionPublicacionesHttp: resultadosVision.map((resultado) => resultado.http),
          visionCommitTimestamps: resultadosVision.filter((resultado) => resultado.commitAt !== null).length,
          latenciaInicioPostASseMs: resumirLatencias(loteConVision.map((medida) => medida.latenciaSseMs)),
          visionEventosEntreAltas: visionEntreAltas,
          timeline: eventosIntercalados.map((evento) => ({ tipo: evento.tipo, orden: evento.orden, enMs: evento.enMs })),
        },
      },
      reconexion: {
        apiHealthHttpAntesDespues: [apiHealthAntes.status, apiHealthDespues.status],
        sesionValidaAntesCorteDuranteCorteTrasReconexion: [estadoSesionAntes.dueno, sesionDuranteCorte.dueno, sesionTrasReconectar.dueno],
        rutaFinal: new URL(page.url()).pathname,
        heartbeatObservadoPorProxy: desconexion.heartbeatsObservados,
        cierresDespuesHeartbeat: conteoFinal.cierresSseTrasHeartbeat,
        streamsActivosMaxPorPestana: datosFinales?.vivasMaximas,
        streamsActivosFinalPorPestana: datosFinales?.vivasActuales,
        solicitudesSseProxy: conteoFinal.solicitudesEventos,
          solicitudesSseInicialAntesReset: streamInicialAntesReset.solicitudesEventos,
        reconexionesConCursor: conteoFinal.solicitudesEventosConCursor,
        eventSourceObjetosAbiertos: datosFinales?.abiertas,
        erroresEventSource: datosFinales?.errores,
        visionEventosObservados: timeline.filter((evento) => evento.tipo === 'vision.ocupacion.actualizada').length,
        secuenciasNegocioCliente: {
          eventos: eventosNegocio.map((evento) => ({ tipo: evento.tipo, orden: evento.orden, enMs: evento.enMs })),
          ordenes: ids,
          monotonas: idsMonotonos,
        },
        framesProxySinPayload: conteoFinal.eventosSse.map((evento) => ({ ...evento })),
        heartbeatsSseProxy: {
          framesSinLineaId: conteoFinal.heartbeatsSseSinId,
          framesConLineaId: conteoFinal.heartbeatsSseConId,
        },
        postVisionDuranteCorteHttp: finalGap.http,
        getVisionAntesReconectar: conteoAntesCierre.lecturasVision,
        getVisionAlReabrir: datosAlReabrir?.abiertasEnMs.length,
        getVisionDespuesReabrir: conteoFinal.lecturasVision,
        getVisionRespuestasHttp: respuestasGetVision,
        snapshotCompletoHttp: snapshotProxy?.estadoHttp,
        snapshotPosteriorAlCommitYReapertura: true,
        navegacionesRegistradas: despuesNavegaciones,
        snapshotFinal: await leerSnapshotDom(page),
        navegacionesPosterioresAlCorte: despuesNavegaciones.length - navegacionesAlCorte.length,
        interaccionUsuarioDespuesDelMontaje: false,
      },
      evidenciaSse: {
        sinPayloadsNiCuerpos: true,
        timelineGlobal: timeline.map((evento) => ({ tipo: evento.tipo, orden: evento.orden, enMs: evento.enMs })),
      },
    }
    await escribirEvidencia(evidencia)
    console.log('QA_VISION_RECONNECT ' + JSON.stringify(evidencia))
  } finally {
    await dueno?.dispose()
    await fixture?.dispose()
    await contexto.close()
  }
})
