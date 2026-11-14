import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext, type Page, type Playwright } from '@playwright/test'
import { baseURL } from './sesion'

type Estado = 'LIBRE' | 'OCUPADO'
type LecturaContador = {
  lecturasVision: number
  lecturasVisionDetalle: Array<{
    iniciadaEnMs: number
    completadaEnMs: number
    demoraMs: number
    estadoHttp: number
    ttlMs: string | null
    estados: Array<{
      etiqueta: string
      estado: string
      ultimoEstadoConfirmado: string | null
    }>
  }>
  solicitudesEventos: number
  solicitudesHeartbeat: number
}
type Marca = { id: string; estado: Estado; enMs: number }
type MarcaDom = { etiqueta: string; estado: string; mensaje: string; enMs: number }
type RespuestaVisionBff = {
  enMs: number
  estadoHttp: number
  estados: Array<{ etiqueta: string; estado: string; ultimoEstadoConfirmado: string | null }> | null
}
type Instrumentacion = {
  fuentes: number
  urls: string[]
  eventos: Marca[]
  latidos: number[]
  estadosDom: MarcaDom[]
}

const apiURL = process.env.TEST_API_BASE_URL || ''
const idFuente = process.env.QA_VISION_SOURCE_ID || ''
const urlFixture = process.env.QA_VISION_FIXTURE_URL || ''
const urlContador = process.env.TEST_VISION_COUNTER_URL || ''
const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const estadoC2Inicial: Estado = 'OCUPADO'
let apiDueno: APIRequestContext
let clienteFixture: APIRequestContext
let zonas: Array<{ visionZoneId: string; etiqueta: string; cajonId: null }>
let estadoC2: Estado = estadoC2Inicial

function validarEntorno(): void {
  if (!idFuente || !uuidV4.test(idFuente) || !apiURL || !urlFixture || !urlContador) {
    throw new Error('Falta una URL o un identificador privado del entorno Vision desechable.')
  }
  const api = new URL(apiURL)
  const fixture = new URL(urlFixture)
  const contador = new URL(urlContador)
  if (api.hostname !== 'api' || api.port !== '8080')
    throw new Error('La API debe ser api:8080 en la red aislada.')
  if (fixture.hostname !== 'vision-fixture' || fixture.port !== '8082')
    throw new Error('El publicador técnico debe ser vision-fixture:8082.')
  if (contador.hostname !== 'vision-counter' || contador.port !== '8081')
    throw new Error('El contador debe ser vision-counter:8081.')
}

async function iniciarClienteDueno(playwright: Playwright): Promise<APIRequestContext> {
  const correo = process.env.TEST_OWNER_EMAIL
  const contrasena = process.env.TEST_OWNER_PASSWORD
  if (!correo || !contrasena) throw new Error('Faltan credenciales sintéticas del DUENO.')
  const api = await playwright.request.newContext({ baseURL: apiURL })
  const csrf = await api.get('/api/v1/csrf')
  expect(csrf.status()).toBe(200)
  const token = String((await csrf.json()).token)
  const sesion = await api.post('/api/v1/sesion', {
    data: { correo, contrasena },
    headers: { 'X-CSRF-TOKEN': token },
  })
  expect(sesion.status()).toBe(200)
  return api
}

async function tokenCsrf(api: APIRequestContext): Promise<string> {
  const respuesta = await api.get('/api/v1/csrf')
  expect(respuesta.status()).toBe(200)
  return String((await respuesta.json()).token)
}

async function iniciarSesionSsr(page: Page, playwright: Playwright): Promise<void> {
  const correo = process.env.TEST_OWNER_EMAIL
  const contrasena = process.env.TEST_OWNER_PASSWORD
  if (!correo || !contrasena) throw new Error('Faltan credenciales sintéticas del DUENO.')
  const bff = await playwright.request.newContext({ baseURL })
  try {
    const csrf = await bff.get('/api/v1/csrf')
    expect(csrf.status()).toBe(200)
    const token = String((await csrf.json()).token)
    const sesion = await bff.post('/api/v1/sesion', {
      data: { correo, contrasena },
      headers: { 'X-CSRF-TOKEN': token },
    })
    expect(sesion.status()).toBe(200)
    const estado = await bff.storageState()
    expect(estado.cookies.length).toBeGreaterThan(0)
    await page.context().addCookies(estado.cookies)
  } finally {
    await bff.dispose()
  }
  const documento = await page.goto(`${baseURL}/admin`)
  expect(documento?.status()).toBe(200)
  await expect(page.getByRole('region', { name: 'Ocupación física' })).toBeVisible()
}

async function llamarFixture(ruta: string, cuerpo?: unknown) {
  const respuesta = await clienteFixture.post(`${urlFixture}${ruta}`, { data: cuerpo ?? {} })
  const resultado = await respuesta.json()
  return { estadoHttp: respuesta.status(), resultado }
}

async function prepararFuente(api: APIRequestContext): Promise<void> {
  const alta = await api.post('/api/v1/vision/fuentes', {
    data: { fuenteId: idFuente },
    headers: { 'X-CSRF-TOKEN': await tokenCsrf(api) },
  })
  expect(alta.status()).toBe(200)

  zonas = [
    { visionZoneId: randomUUID(), etiqueta: 'C01', cajonId: null },
    { visionZoneId: randomUUID(), etiqueta: 'C02', cajonId: null },
  ]
  const hash = 'c'.repeat(64)
  const calibracion = await api.put(`/api/v1/vision/fuentes/${idFuente}/calibracion`, {
    data: { revisionCalibracion: 1, hashCalibracion: hash, zonas },
    headers: { 'X-CSRF-TOKEN': await tokenCsrf(api) },
  })
  expect(calibracion.status()).toBe(200)
  const preparada = await llamarFixture('/__preparar', {
    revisionCalibracion: 1,
    hashCalibracion: hash,
    zonas: zonas.map((zona, indice) => ({
      visionZoneId: zona.visionZoneId,
      estado: indice === 1 ? estadoC2Inicial : 'LIBRE',
    })),
  })
  expect(preparada.estadoHttp).toBe(200)
  expect(preparada.resultado.ok).toBe(true)
  expect(typeof preparada.resultado.commitAt).toBe('string')
  await new Promise((resolver) => setTimeout(resolver, 1_300))
}

async function restablecerContador(playwright: Playwright): Promise<void> {
  const destino = new URL(urlContador)
  destino.pathname = '/__reiniciar-conteo'
  const contexto = await playwright.request.newContext()
  const respuesta = await contexto.post(destino.toString())
  expect(respuesta.status()).toBe(204)
  await contexto.dispose()
}

async function leerContador(playwright: Playwright): Promise<LecturaContador> {
  const contexto = await playwright.request.newContext()
  const respuesta = await contexto.get(urlContador)
  expect(respuesta.status()).toBe(200)
  const datos = (await respuesta.json()) as LecturaContador
  await contexto.dispose()
  return datos
}

async function instalarInstrumentacion(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const ventana = window as typeof window & { __qaVisionC1: Instrumentacion }
    ventana.__qaVisionC1 = { fuentes: 0, urls: [], eventos: [], latidos: [], estadosDom: [] }
    const EventSourceNativo = window.EventSource
    class EventSourceMedido extends EventSourceNativo {
      constructor(url: string | URL, opciones?: EventSourceInit) {
        super(url, opciones)
        const datos = (window as typeof window & { __qaVisionC1: Instrumentacion }).__qaVisionC1
        datos.fuentes += 1
        datos.urls.push(String(url))
        this.addEventListener('vision.ocupacion.actualizada', (evento) => {
          datos.eventos.push({
            id: (evento as MessageEvent).lastEventId,
            estado: 'LIBRE',
            enMs: Date.now(),
          })
        })
        this.addEventListener('empleado.heartbeat', () => datos.latidos.push(Date.now()))
      }
    }
    window.EventSource = EventSourceMedido

    const registrarEstado = () => {
      const datos = (window as typeof window & { __qaVisionC1: Instrumentacion }).__qaVisionC1
      for (const tarjeta of document.querySelectorAll('li.cajon-vision')) {
        const etiqueta = tarjeta
          ?.querySelector('h1, h2, h3, h4, [role="heading"]')
          ?.textContent?.trim()
        if (etiqueta !== 'C02') continue
        const estado = tarjeta?.querySelector('.estado-cajon')?.textContent?.trim()
        if (!estado) continue
        const mensaje = document
          .querySelector('.ocupacion-vision .aviso-ocupacion')
          ?.textContent?.trim() ?? ''
        const ultima = datos.estadosDom.at(-1)
        if (
          ultima?.etiqueta === etiqueta &&
          ultima.estado === estado &&
          ultima.mensaje === mensaje
        ) {
          continue
        }
        datos.estadosDom.push({ etiqueta, estado, mensaje, enMs: Date.now() })
        if (datos.estadosDom.length > 512) datos.estadosDom.shift()
      }
    }
    const observar = new MutationObserver(registrarEstado)
    window.setInterval(registrarEstado, 25)
    const instalarObservador = () => {
      const raiz = document.documentElement
      if (!raiz) return
      observar.observe(raiz, { subtree: true, childList: true, characterData: true })
      registrarEstado()
    }
    if (document.documentElement) instalarObservador()
    else document.addEventListener('DOMContentLoaded', instalarObservador, { once: true })
  })
}

function tarjeta(page: Page, etiqueta: string) {
  return page
    .locator('li.cajon-vision')
    .filter({ has: page.getByRole('heading', { name: etiqueta, exact: true }) })
}

function textoEstado(estado: Estado): string {
  return estado === 'LIBRE' ? 'Libre' : 'Ocupado'
}

async function observarEstado(estado: Estado) {
  const respuesta = await llamarFixture('/__observar', {
    cambios: [{ visionZoneId: zonas[1].visionZoneId, estado }],
  })
  expect(respuesta.estadoHttp).toBe(200)
  expect(respuesta.resultado.ok).toBe(true)
  expect(typeof respuesta.resultado.commitAt).toBe('string')
  estadoC2 = estado
  return Date.parse(respuesta.resultado.commitAt as string)
}

async function esperarEvento(page: Page, indice: number): Promise<Marca> {
  await expect
    .poll(() => page.evaluate(() => (window as any).__qaVisionC1.eventos.length), {
      timeout: 8_000,
    })
    .toBe(indice + 1)
  return page.evaluate((index) => (window as any).__qaVisionC1.eventos[index], indice) as Promise<Marca>
}

async function esperarMarcaDom(page: Page, estado: Estado, desdeMs: number): Promise<number> {
  await expect(tarjeta(page, 'C02').locator('.estado-cajon')).toHaveText(textoEstado(estado))
  try {
    await expect
      .poll(
        () =>
          page.evaluate(
            ({ estadoEsperado, limite }) =>
              (window as any).__qaVisionC1.estadosDom.some(
                (marca: MarcaDom) => marca.estado === estadoEsperado && marca.enMs >= limite,
              ),
            { estadoEsperado: textoEstado(estado), limite: desdeMs },
          ),
        { timeout: 8_000 },
      )
      .toBe(true)
  } catch (error) {
    const diagnostico = await page.evaluate(() => ({
      ahora: Date.now(),
      marcas: (window as any).__qaVisionC1.estadosDom,
      tarjetas: Array.from(document.querySelectorAll('li.cajon-vision')).map((elemento) => ({
        encabezado: elemento.querySelector('h1, h2, h3, h4, [role="heading"]')?.textContent?.trim(),
        estado: elemento.querySelector('.estado-cajon')?.textContent?.trim(),
      })),
    }))
    console.log(
      'VISION_C1_DOM_DEBUG ' +
        JSON.stringify({ esperado: textoEstado(estado), desdeMs, diagnostico }),
    )
    throw error
  }
  const marcas = (await page.evaluate(
    () => (window as any).__qaVisionC1.estadosDom,
  )) as MarcaDom[]
  return Math.min(
    ...marcas
      .filter((marca) => marca.estado === textoEstado(estado) && marca.enMs >= desdeMs)
      .map((marca) => marca.enMs),
  )
}

function percentil(valores: number[], porcentaje: number): number {
  const ordenados = [...valores].sort((a, b) => a - b)
  return ordenados[Math.max(0, Math.ceil((porcentaje / 100) * ordenados.length) - 1)]
}

test.describe.configure({ timeout: 240_000 })

test.beforeAll(async ({ playwright }) => {
  validarEntorno()
  clienteFixture = await playwright.request.newContext()
  apiDueno = await iniciarClienteDueno(playwright)
  const estadoFixture = await clienteFixture.get(`${urlFixture}/__estado`)
  const datosFixture = (await estadoFixture.json()) as {
    ok: boolean
    zonas: Array<{ visionZoneId: string; estado: Estado }>
  }
  if (estadoFixture.status() === 200 && datosFixture.ok && datosFixture.zonas.length >= 2) {
    zonas = datosFixture.zonas.map((zona, indice) => ({
      visionZoneId: zona.visionZoneId,
      etiqueta: `C${String(indice + 1).padStart(2, '0')}`,
      cajonId: null,
    }))
    estadoC2 = datosFixture.zonas[1].estado
    return
  }
  await prepararFuente(apiDueno)
})

test.afterAll(async () => {
  await apiDueno?.dispose()
  await clienteFixture?.dispose()
})

test('ingesta real, SSR, replay SSR→SSE, invalidación, coalescencia y latencias', async ({
  page,
  playwright,
}) => {
  validarEntorno()
  await observarEstado('OCUPADO')
  await restablecerContador(playwright)
  await instalarInstrumentacion(page)

  let eventoSseVisto!: () => void
  let liberarSse!: () => void
  const primeraSolicitudSse = new Promise<void>((resolver) => {
    eventoSseVisto = resolver
  })
  const compuertaSse = new Promise<void>((resolver) => {
    liberarSse = resolver
  })
  let bloquearSse = true
  let urlSse = ''
  let getVisionEnBrowser = 0
  await page.route('**/api/v1/eventos/administracion*', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname !== '/api/v1/eventos/administracion' || !bloquearSse) {
      await route.continue()
      return
    }
    bloquearSse = false
    urlSse = route.request().url()
    eventoSseVisto()
    await compuertaSse
    await route.continue()
  })
  page.on('request', (solicitud) => {
    const url = new URL(solicitud.url())
    if (solicitud.method() === 'GET' && url.pathname === '/api/v1/vision/cajones')
      getVisionEnBrowser += 1
  })

  await iniciarSesionSsr(page, playwright)
  await expect(page.getByRole('region', { name: 'Ocupación física' })).toBeVisible()
  await expect(tarjeta(page, 'C02').locator('.estado-cajon')).toHaveText('Ocupado')
  await primeraSolicitudSse
  await expect.poll(() => page.evaluate(() => (window as any).__qaVisionC1.fuentes)).toBe(1)
  const antesDelReplay = await leerContador(playwright)
  expect(antesDelReplay.lecturasVision).toBe(1)
  expect(antesDelReplay.solicitudesEventos).toBe(0)
  expect(getVisionEnBrowser).toBe(0)
  expect(new URL(urlSse).searchParams.get('despues')).toBeTruthy()

  const eventoInicial = await observarEstado('LIBRE')
  await page.waitForTimeout(1_250)
  liberarSse()
  await esperarEvento(page, 0)
  const eventoCarrera = (await page.evaluate(
    () => (window as any).__qaVisionC1.eventos[0],
  )) as Marca
  const domCarrera = await esperarMarcaDom(page, 'LIBRE', eventoInicial)
  const despuesDelReplay = await leerContador(playwright)
  expect(despuesDelReplay.lecturasVision).toBe(2)
  expect(despuesDelReplay.solicitudesEventos).toBe(1)
  expect(getVisionEnBrowser).toBe(1)
  expect(eventoCarrera.enMs).toBeGreaterThanOrEqual(eventoInicial)
  expect(domCarrera).toBeGreaterThanOrEqual(eventoCarrera.enMs)
  console.log(
    'VISION_C1_REPLAY ' +
      JSON.stringify({
        ssrGet: 1,
        hydrationBrowserGet: 0,
        sharedSse: despuesDelReplay.solicitudesEventos,
        eventSourceObjects: 1,
        c2: 'OCUPADO→LIBRE',
        commitToSseMs: eventoCarrera.enMs - eventoInicial,
        commitToDomMs: domCarrera - eventoInicial,
      }),
  )

  const latenciaSse: number[] = []
  const latenciaDom: number[] = []
  for (let indice = 0; indice < 20; indice += 1) {
    const destino: Estado = estadoC2 === 'LIBRE' ? 'OCUPADO' : 'LIBRE'
    const marcaCommit = await observarEstado(destino)
    const numeroEvento = indice + 1
    const evento = await esperarEvento(page, numeroEvento)
    const marcaDom = await esperarMarcaDom(page, destino, marcaCommit)
    latenciaSse.push(evento.enMs - marcaCommit)
    latenciaDom.push(marcaDom - marcaCommit)
  }
  const tiempos = {
    n: latenciaDom.length,
    commitSseMs: {
      p50: percentil(latenciaSse, 50),
      p95: percentil(latenciaSse, 95),
      max: Math.max(...latenciaSse),
    },
    commitDomMs: {
      p50: percentil(latenciaDom, 50),
      p95: percentil(latenciaDom, 95),
      max: Math.max(...latenciaDom),
    },
  }
  console.log('VISION_C1_LATENCIA ' + JSON.stringify(tiempos))
  expect(tiempos.commitDomMs.p95).toBeLessThanOrEqual(2_000)
  expect(tiempos.commitDomMs.max).toBeLessThanOrEqual(5_000)

  const conteoAntesSinCambio = await leerContador(playwright)
  const eventosAntesSinCambio = await page.evaluate(
    () => (window as any).__qaVisionC1.eventos.length,
  )
  const sinCambio = await llamarFixture('/__observar', {
    cambios: [{ visionZoneId: zonas[1].visionZoneId, estado: estadoC2 }],
  })
  expect(sinCambio.estadoHttp).toBe(200)
  await page.waitForTimeout(5_500)
  const conteoTrasSinCambio = await leerContador(playwright)
  const eventosTrasSinCambio = await page.evaluate(
    () => (window as any).__qaVisionC1.eventos.length,
  )
  expect(eventosTrasSinCambio).toBe(eventosAntesSinCambio)
  expect(conteoTrasSinCambio.lecturasVision).toBe(conteoAntesSinCambio.lecturasVision)

  const eventosAntesSimultaneo = await page.evaluate(
    () => (window as any).__qaVisionC1.eventos.length,
  )
  const contadorAntesSimultaneo = await leerContador(playwright)
  const siguienteC2: Estado = estadoC2 === 'LIBRE' ? 'OCUPADO' : 'LIBRE'
  const simultaneo = await llamarFixture('/__observar', {
    cambios: [
      { visionZoneId: zonas[0].visionZoneId, estado: 'OCUPADO' },
      { visionZoneId: zonas[1].visionZoneId, estado: siguienteC2 },
    ],
  })
  expect(simultaneo.estadoHttp).toBe(200)
  estadoC2 = siguienteC2
  await esperarEvento(page, eventosAntesSimultaneo)
  await expect(tarjeta(page, 'C01').locator('.estado-cajon')).toHaveText('Ocupado')
  await expect(tarjeta(page, 'C02').locator('.estado-cajon')).toHaveText(textoEstado(siguienteC2))
  const contadorDespuesSimultaneo = await leerContador(playwright)
  expect(
    contadorDespuesSimultaneo.lecturasVision - contadorAntesSimultaneo.lecturasVision,
  ).toBe(1)

  const estadoAntesRollback = estadoC2
  const eventosAntesRollback = await page.evaluate(
    () => (window as any).__qaVisionC1.eventos.length,
  )
  const contadorAntesRollback = await leerContador(playwright)
  const rollbackArmado = await llamarFixture('/__armar_rollback')
  expect(rollbackArmado.estadoHttp).toBe(200)
  const respuestaRollback = await llamarFixture('/__observar', {
    cambios: [
      {
        visionZoneId: zonas[1].visionZoneId,
        estado: estadoAntesRollback === 'LIBRE' ? 'OCUPADO' : 'LIBRE',
      },
    ],
  })
  expect(respuestaRollback.estadoHttp).toBe(500)
  const rollbackDesarmado = await llamarFixture('/__desarmar_rollback')
  expect(rollbackDesarmado.estadoHttp).toBe(200)
  await page.waitForTimeout(1_250)
  const eventosTrasRollback = await page.evaluate(
    () => (window as any).__qaVisionC1.eventos.length,
  )
  const contadorTrasRollback = await leerContador(playwright)
  const snapshotJava = await apiDueno.get('/api/v1/vision/cajones')
  expect(snapshotJava.status()).toBe(200)
  const cajonesJava = (await snapshotJava.json()) as Array<{ etiqueta: string; estado: string }>
  expect(cajonesJava.find((cajon) => cajon.etiqueta === 'C02')?.estado).toBe(estadoAntesRollback)
  expect(eventosTrasRollback).toBe(eventosAntesRollback)
  expect(contadorTrasRollback.lecturasVision).toBe(contadorAntesRollback.lecturasVision)

  const final = await leerContador(playwright)
  const instrumentacion = (await page.evaluate(
    () => (window as any).__qaVisionC1,
  )) as Instrumentacion
  expect(instrumentacion.fuentes).toBe(1)
  expect(final.solicitudesEventos).toBe(1)
  console.log(
    'VISION_C1_CONTEOS ' +
      JSON.stringify({
        visionGetTotal: final.lecturasVision,
        eventStreamConnections: final.solicitudesEventos,
        heartbeatAcks: final.solicitudesHeartbeat,
        eventSourceObjects: instrumentacion.fuentes,
        browserVisionGets: getVisionEnBrowser,
        eventsObserved: instrumentacion.eventos.length,
        unchangedObservationEvents: 0,
        rollback: {
          http: respuestaRollback.estadoHttp,
          eventDelta: eventosTrasRollback - eventosAntesRollback,
          visionGetDelta: contadorTrasRollback.lecturasVision - contadorAntesRollback.lecturasVision,
        },
      }),
  )
  await page.unrouteAll({ behavior: 'wait' })
})

test('la fecha límite de frescura produce NO_VERIFICABLE sin nuevas observaciones', async ({
  page,
  playwright,
}) => {
  await restablecerContador(playwright)
  await instalarInstrumentacion(page)
  let browserGets = 0
  page.on('request', (solicitud) => {
    if (
      solicitud.method() === 'GET' &&
      new URL(solicitud.url()).pathname === '/api/v1/vision/cajones'
    )
      browserGets += 1
  })
  await iniciarSesionSsr(page, playwright)
  await expect.poll(async () => (await leerContador(playwright)).solicitudesEventos).toBe(1)
  const contadorInicial = await leerContador(playwright)
  expect(contadorInicial.lecturasVision).toBe(1)
  expect(browserGets).toBe(0)
  const c2 = tarjeta(page, 'C02')
  await expect(c2).toBeVisible()
  await expect(c2.locator('.estado-cajon')).toHaveText(textoEstado(estadoC2))
  const inicio = Date.now()
  await expect(c2.locator('.estado-cajon')).toHaveText('No verificable', { timeout: 52_000 })
  const transcurrido = Date.now() - inicio
  const conteo = await leerContador(playwright)
  expect(transcurrido).toBeGreaterThanOrEqual(40_000)
  expect(conteo.lecturasVision).toBeGreaterThanOrEqual(1)
  console.log(
    'VISION_C1_DEADLINE ' +
      JSON.stringify({ estado: 'NO_VERIFICABLE', tiempoMs: transcurrido, visionGetTotal: conteo.lecturasVision }),
  )
})

test('el GET de vencimiento lleva NO_VERIFICABLE al DOM en menos de 5 s', async ({
  page,
  playwright,
}) => {
  await restablecerContador(playwright)
  await instalarInstrumentacion(page)
  await observarEstado('OCUPADO')

  const respuestasVisionBff: RespuestaVisionBff[] = []
  const tareasRespuesta: Promise<void>[] = []
  page.on('response', (respuesta) => {
    if (new URL(respuesta.url()).pathname !== '/api/v1/vision/cajones') return
    const marca: RespuestaVisionBff = {
      enMs: Date.now(),
      estadoHttp: respuesta.status(),
      estados: null,
    }
    respuestasVisionBff.push(marca)
    tareasRespuesta.push(
      respuesta
        .json()
        .then((cuerpo: unknown) => {
          if (!Array.isArray(cuerpo)) return
          marca.estados = cuerpo.map((cajon: any) => ({
            etiqueta: typeof cajon.etiqueta === 'string' ? cajon.etiqueta : '',
            estado: typeof cajon.estado === 'string' ? cajon.estado : '',
            ultimoEstadoConfirmado:
              typeof cajon.ultimoEstadoConfirmado === 'string' ? cajon.ultimoEstadoConfirmado : null,
          }))
        })
        .catch(() => {
          marca.estados = []
        }),
    )
  })

  await iniciarSesionSsr(page, playwright)
  await expect.poll(async () => (await leerContador(playwright)).solicitudesEventos).toBe(1)
  const c2 = tarjeta(page, 'C02')
  await expect(c2.locator('.estado-cajon')).toHaveText('Ocupado')
  await page.waitForTimeout(20_000)

  const commitAt = await observarEstado('LIBRE')
  await expect(c2.locator('.estado-cajon')).toHaveText('Libre')
  await expect.poll(() => page.evaluate(() => (window as any).__qaVisionC1.eventos.length)).toBe(1)
  await expect
    .poll(
      () =>
        respuestasVisionBff.some((respuesta) =>
          respuesta.estados?.some((cajon) => cajon.etiqueta === 'C02' && cajon.estado === 'NO_VERIFICABLE'),
        ),
      { timeout: 60_000, intervals: [100, 250, 500, 1_000] },
    )
    .toBe(true)
  await Promise.all(tareasRespuesta)

  const respuestaVencida = respuestasVisionBff.find((respuesta) =>
    respuesta.estados?.some((cajon) => cajon.etiqueta === 'C02' && cajon.estado === 'NO_VERIFICABLE'),
  )
  expect(respuestaVencida).toBeDefined()
  const marcaDomVencida = ((await page.evaluate(
    () => (window as any).__qaVisionC1.estadosDom,
  )) as MarcaDom[]).find(
    (marca) => marca.etiqueta === 'C02' && marca.estado === 'No verificable',
  )
  expect(marcaDomVencida).toBeDefined()
  const diferenciaGetDomMs = marcaDomVencida!.enMs - respuestaVencida!.enMs
  const estadoFinal = await c2.locator('.estado-cajon').innerText()
  console.log(
    'VISION_C1_GET_VENCIMIENTO ' +
      JSON.stringify({
        commitToGetMs: respuestaVencida!.enMs - commitAt,
        getToDomMs: diferenciaGetDomMs,
        respuestaHttp: respuestaVencida!.estadoHttp,
        estadoJava: respuestaVencida!.estados?.find((cajon) => cajon.etiqueta === 'C02')?.estado,
        estadoDom: marcaDomVencida!.estado,
        mensajeDom: marcaDomVencida!.mensaje,
        estadoFinal: estadoFinal.trim(),
        eventSources: await page.evaluate(() => (window as any).__qaVisionC1.fuentes),
        eventRequests: (await leerContador(playwright)).solicitudesEventos,
      }),
  )
  expect(respuestaVencida!.estadoHttp).toBe(200)
  expect(Math.abs(diferenciaGetDomMs)).toBeLessThanOrEqual(5_000)
  await expect(c2.locator('.estado-cajon')).toHaveText('No verificable', { timeout: 5_000 })
})

test('monitoreo visible durante 120 s sin interacción humana y recuperación posterior a 60 s', async ({
  page,
  playwright,
}) => {
  const siguiente: Estado = estadoC2 === 'LIBRE' ? 'OCUPADO' : 'LIBRE'
  const renovacion = await observarEstado(siguiente)
  expect(Date.now() - renovacion).toBeLessThan(1_000)
  await new Promise((resolver) => setTimeout(resolver, 1_250))

  await restablecerContador(playwright)
  await instalarInstrumentacion(page)
  let browserGets = 0
  const solicitudesSse: number[] = []
  const respuestasSse: Array<{ enMs: number; estado: number }> = []
  const solicitudesHeartbeat: number[] = []
  const respuestasHeartbeat: Array<{ enMs: number; estado: number }> = []
  const solicitudesVision: number[] = []
  const respuestasVision: Array<{ enMs: number; estado: number }> = []
  const respuestasSesion: Array<{ enMs: number; estado: number }> = []
  const fallosRed: string[] = []
  page.on('request', (solicitud) => {
    if (
      solicitud.method() === 'GET' &&
      new URL(solicitud.url()).pathname === '/api/v1/vision/cajones'
    ) {
      browserGets += 1
      solicitudesVision.push(Date.now())
    }
    const path = new URL(solicitud.url()).pathname
    if (solicitud.method() === 'GET' && path === '/api/v1/eventos/administracion')
      solicitudesSse.push(Date.now())
    if (solicitud.method() === 'POST' && path === '/api/v1/eventos/administracion/heartbeat')
      solicitudesHeartbeat.push(Date.now())
  })
  page.on('response', (respuesta) => {
    const path = new URL(respuesta.url()).pathname
    const marca = { enMs: Date.now(), estado: respuesta.status() }
    if (path === '/api/v1/eventos/administracion') respuestasSse.push(marca)
    if (path === '/api/v1/eventos/administracion/heartbeat') respuestasHeartbeat.push(marca)
    if (path === '/api/v1/vision/cajones') respuestasVision.push(marca)
    if (path === '/api/v1/sesion') respuestasSesion.push(marca)
  })
  page.on('requestfailed', (solicitud) => {
    const path = new URL(solicitud.url()).pathname
    if (
      path === '/api/v1/eventos/administracion' ||
      path === '/api/v1/eventos/administracion/heartbeat' ||
      path === '/api/v1/vision/cajones' ||
      path === '/api/v1/sesion'
    ) {
      fallosRed.push(path)
    }
  })
  await iniciarSesionSsr(page, playwright)
  await expect.poll(async () => (await leerContador(playwright)).solicitudesEventos).toBe(1)
  const c2 = tarjeta(page, 'C02')
  await expect(c2.locator('.estado-cajon')).toHaveText(textoEstado(estadoC2))
  const contadorInicial = await leerContador(playwright)
  expect(contadorInicial.lecturasVision).toBe(1)
  expect(browserGets).toBe(0)
  expect(await page.evaluate(() => (window as any).__qaVisionC1.fuentes)).toBe(1)

  const inicioMedicion = Date.now()
  const inicio = Date.now()
  const actualizacionPosterior = (async () => {
    await page.waitForTimeout(65_000)
    const posterior: Estado = estadoC2 === 'LIBRE' ? 'OCUPADO' : 'LIBRE'
    try {
      await observarEstado(posterior)
      await expect(c2.locator('.estado-cajon')).toHaveText(textoEstado(posterior), {
        timeout: 8_000,
      })
      return { ok: true, estado: posterior }
    } catch {
      return { ok: false, estado: posterior }
    }
  })()
  const ventanas: Array<Record<string, unknown>> = []
  for (let numero = 1; numero <= 4; numero += 1) {
    await page.waitForTimeout(30_000)
    const estadoVisible = await c2
      .locator('.estado-cajon')
      .innerText()
      .catch(() => 'SIN_ELEMENTO')
    const pagina = await page.evaluate(() => ({
      visible: document.visibilityState === 'visible',
      online: navigator.onLine,
      ubicacion: location.pathname,
      eventSources: (window as any).__qaVisionC1.fuentes,
      visionEvents: (window as any).__qaVisionC1.eventos.length,
      heartbeatEvents: (window as any).__qaVisionC1.latidos.length,
    }))
    const conteoVentana = await leerContador(playwright)
    const ventana = {
      elapsedMs: Date.now() - inicio,
      state: estadoVisible.trim(),
      message: await page.locator('.ocupacion-vision .aviso-ocupacion').innerText().catch(() => ''),
      ...pagina,
      visionGets: conteoVentana.lecturasVision,
      sseRequests: conteoVentana.solicitudesEventos,
      heartbeatAcks: conteoVentana.solicitudesHeartbeat,
      sseStatuses: respuestasSse.map((marca) => marca.estado),
      heartbeatStatuses: respuestasHeartbeat.map((marca) => marca.estado),
      sessionStatuses: respuestasSesion.map((marca) => marca.estado),
      browserVisionGets: browserGets,
      visionResponses: conteoVentana.lecturasVisionDetalle.map((lectura) => ({
        elapsedMs: lectura.completadaEnMs - inicioMedicion,
        demoraMs: lectura.demoraMs,
        estadoHttp: lectura.estadoHttp,
        ttlMs: lectura.ttlMs,
        estados: lectura.estados,
      })),
    }
    ventanas.push(ventana)
    console.log('VISION_C1_WINDOW ' + JSON.stringify(ventana))
  }
  const resultadoPosterior = await actualizacionPosterior
  const duracion = Date.now() - inicio
  const conteo = await leerContador(playwright)
  const instrumentacion = (await page.evaluate(
    () => (window as any).__qaVisionC1,
  )) as Instrumentacion
  const estadoFinal = await c2.locator('.estado-cajon').innerText()
  console.log(
    'VISION_C1_PASIVO_TIMELINE ' +
      JSON.stringify({
        durationMs: duracion,
        changeAfterMs: 65_000,
        updateDeliveredAfter60s: resultadoPosterior.ok,
        updateState: resultadoPosterior.estado,
        windows: ventanas,
        requests: {
          sseOpens: solicitudesSse.length,
          sseStatuses: respuestasSse.map((marca) => marca.estado),
          heartbeatRequests: solicitudesHeartbeat.length,
          heartbeatStatuses: respuestasHeartbeat.map((marca) => marca.estado),
          visionBrowserGets: solicitudesVision.length,
          visionStatuses: respuestasVision.map((marca) => marca.estado),
          sessionStatuses: respuestasSesion.map((marca) => marca.estado),
          failedRequestPaths: fallosRed,
        },
        counters: conteo,
        visionResponses: conteo.lecturasVisionDetalle.map((lectura) => ({
          elapsedMs: lectura.completadaEnMs - inicioMedicion,
          demoraMs: lectura.demoraMs,
          estadoHttp: lectura.estadoHttp,
          ttlMs: lectura.ttlMs,
          estados: lectura.estados,
        })),
        instrumentation: {
          eventSources: instrumentacion.fuentes,
          events: instrumentacion.eventos.map((evento) => ({
            elapsedMs: evento.enMs - inicioMedicion,
            state: evento.estado,
          })),
          heartbeatCount: instrumentacion.latidos.length,
          domStates: instrumentacion.estadosDom.map((estado) => ({
            elapsedMs: estado.enMs - inicioMedicion,
            state: estado.estado,
            message: estado.mensaje,
          })),
        },
        finalState: estadoFinal.trim(),
        message: await page.locator('.ocupacion-vision .aviso-ocupacion').innerText().catch(() => ''),
      }),
  )
  expect(duracion).toBeGreaterThanOrEqual(120_000)
  expect(resultadoPosterior.ok).toBe(true)
  expect(conteo.solicitudesEventos).toBeLessThanOrEqual(4)
  expect(conteo.lecturasVision).toBeGreaterThanOrEqual(4)
  expect(conteo.lecturasVision).toBeLessThanOrEqual(8)
  expect(instrumentacion.eventos.length).toBe(1)
  await expect(c2.locator('.estado-cajon')).toHaveText('No verificable')
})

test('navegación CSR y responsive conservan el snapshot sin una nueva navegación documental', async ({
  page,
  playwright,
}) => {
  await restablecerContador(playwright)
  await iniciarSesionSsr(page, playwright)
  let documentosAdmin = 0
  page.on('request', (solicitud) => {
    if (
      solicitud.isNavigationRequest() &&
      solicitud.frame() === page.mainFrame() &&
      new URL(solicitud.url()).pathname === '/admin'
    ) {
      documentosAdmin += 1
    }
  })
  const principal = page.getByRole('navigation', { name: 'Principal' }).first()
  await principal.getByRole('link', { name: 'Empleados' }).click()
  await expect(page).toHaveURL(/\/admin\/empleados$/)
  await expect(page.getByRole('region', { name: 'Lista de empleados' }).first()).toBeVisible()
  await page.getByRole('link', { name: 'Smart Parking, Inicio' }).click()
  await expect(page).toHaveURL(/\/admin$/)
  await expect(page.getByRole('region', { name: 'Ocupación física' })).toBeVisible()
  expect(documentosAdmin).toBe(0)

  for (const viewport of [
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 1440, height: 900 },
  ]) {
    await page.setViewportSize(viewport)
    const anchura = await page.evaluate(() => ({
      ventana: window.innerWidth,
      documento: document.documentElement.scrollWidth,
      cuerpo: document.body.scrollWidth,
    }))
    expect(Math.max(anchura.documento, anchura.cuerpo)).toBeLessThanOrEqual(anchura.ventana + 1)
  }
  const conteo = await leerContador(playwright)
  console.log(
    'VISION_C1_NAV_RESPONSIVE ' +
      JSON.stringify({ documentosAdminPorCSR: documentosAdmin, viewports: [390, 768, 1440], visionGetTotal: conteo.lecturasVision }),
  )
})
