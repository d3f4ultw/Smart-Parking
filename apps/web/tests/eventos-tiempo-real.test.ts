import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { crearControladorEventosTiempoReal } from '../app/utils/eventos-tiempo-real.ts'

const WEB_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')

class FuenteEventosFalsa {
  readyState = 0
  onopen: ((this: EventSource, evento: Event) => unknown) | null = null
  onerror: ((this: EventSource, evento: Event) => unknown) | null = null
  readonly listeners = new Map<string, EventListener[]>()
  readonly url: string
  cierres = 0

  constructor(url: string) {
    this.url = url
  }

  addEventListener(tipo: string, listener: EventListenerOrEventListenerObject) {
    const callback: EventListener = typeof listener === 'function'
      ? listener
      : (evento) => listener.handleEvent(evento)
    const listeners = this.listeners.get(tipo) ?? []
    listeners.push(callback)
    this.listeners.set(tipo, listeners)
  }

  close() {
    this.cierres += 1
    this.readyState = 2
  }

  abrir() {
    this.readyState = 1
    this.onopen?.call(this as unknown as EventSource, new Event('open'))
  }

  fallar(estado: number) {
    this.readyState = estado
    this.onerror?.call(this as unknown as EventSource, new Event('error'))
  }

  emitir(tipo: string, data: string, lastEventId: string) {
    const evento = new MessageEvent<string>(tipo, { data, lastEventId })
    for (const listener of this.listeners.get(tipo) ?? []) {
      listener(evento)
    }
  }
}

type TemporizadorPrueba = {
  callback: () => void
  demora: number
  cancelado: boolean
}

function crearProgramador(temporizadores: TemporizadorPrueba[]) {
  return {
    programar(callback: () => void, demora: number) {
      const temporizador = { callback, demora, cancelado: false }
      temporizadores.push(temporizador)
      return temporizador as unknown as ReturnType<typeof setTimeout>
    },
    cancelar(id: ReturnType<typeof setTimeout>) {
      ;(id as unknown as TemporizadorPrueba).cancelado = true
    },
  }
}

function manejadores(
  actualizaciones: number[] = [],
  creaciones: Array<[number, string]> = [],
  resyncs: number[] = [],
) {
  return {
    alActualizarOperador: (id: number) => actualizaciones.push(id),
    alCrearOperador: (id: number, cursor: string) => creaciones.push([id, cursor]),
    alResync: () => {
      resyncs.push(1)
    },
  }
}

function emitirOperador(
  fuente: FuenteEventosFalsa,
  tipo: 'operador.actualizado' | 'operador.creado',
  recursoId: number,
  cursor: string,
) {
  fuente.emitir(
    tipo,
    JSON.stringify({ recurso_tipo: 'operador', recurso_id: recursoId, ocurrido_en: '2026-10-04T12:00:00Z' }),
    cursor,
  )
}

test('el controlador no abre durante SSR y crea una sola fuente por layout al iniciar', () => {
  const fuentes: FuenteEventosFalsa[] = []
  const controlador = crearControladorEventosTiempoReal({
    crearFuente: (url) => {
      const fuente = new FuenteEventosFalsa(url)
      fuentes.push(fuente)
      return fuente as unknown as EventSource
    },
    alPerderSesion: () => {},
  })
  controlador.suscribir('41', manejadores())
  assert.equal(fuentes.length, 0, 'No EventSource is created during setup/SSR')

  controlador.iniciar()
  controlador.iniciar()
  assert.equal(fuentes.length, 1, 'Repeated lifecycle start does not duplicate the stream')
  assert.equal(fuentes[0]?.url, '/api/eventos?cursor_eventos=41')
  assert.equal(controlador.estado.value, 'conectando')
  controlador.detener()
  assert.equal(fuentes[0]?.cierres, 1)
})

test('un layout sin snapshot arranca en el high-water actual del backend', () => {
  const fuentes: FuenteEventosFalsa[] = []
  const controlador = crearControladorEventosTiempoReal({
    crearFuente: (url) => {
      const fuente = new FuenteEventosFalsa(url)
      fuentes.push(fuente)
      return fuente as unknown as EventSource
    },
    alPerderSesion: () => {},
  })
  controlador.iniciar()
  assert.equal(fuentes[0]?.url, '/api/eventos')
  controlador.detener()
})

test('la tabla recibe eventos tipados, descarta duplicados y los suscriptores nuevos reproducen el buffer', () => {
  const fuentes: FuenteEventosFalsa[] = []
  const actualizaciones: number[] = []
  const creaciones: Array<[number, string]> = []
  const resyncs: number[] = []
  const controlador = crearControladorEventosTiempoReal({
    crearFuente: (url) => {
      const fuente = new FuenteEventosFalsa(url)
      fuentes.push(fuente)
      return fuente as unknown as EventSource
    },
    alPerderSesion: () => {},
  })
  const suscripcion = controlador.suscribir('10', manejadores(actualizaciones, creaciones, resyncs))
  controlador.iniciar()
  const fuente = fuentes[0]!
  fuente.abrir()
  emitirOperador(fuente, 'operador.actualizado', 7, '11')
  emitirOperador(fuente, 'operador.creado', 8, '12')
  emitirOperador(fuente, 'operador.creado', 8, '12')
  assert.deepEqual(actualizaciones, [7])
  assert.deepEqual(creaciones, [[8, '12']])

  const actualizacionesReproducidas: number[] = []
  const creacionesReproducidas: Array<[number, string]> = []
  const nuevaSuscripcion = controlador.suscribir(
    '11',
    manejadores(actualizacionesReproducidas, creacionesReproducidas),
  )
  assert.deepEqual(actualizacionesReproducidas, [])
  assert.deepEqual(creacionesReproducidas, [[8, '12']])
  nuevaSuscripcion.detener()
  suscripcion.detener()
  controlador.detener()
})

test('un cursor anterior al buffer descartado fuerza resync en lugar de fingir continuidad', () => {
  const fuentes: FuenteEventosFalsa[] = []
  let resyncs = 0
  const controlador = crearControladorEventosTiempoReal({
    limiteBuffer: 2,
    crearFuente: (url) => {
      const fuente = new FuenteEventosFalsa(url)
      fuentes.push(fuente)
      return fuente as unknown as EventSource
    },
    alPerderSesion: () => {},
  })
  controlador.iniciar()
  const fuente = fuentes[0]!
  fuente.abrir()
  emitirOperador(fuente, 'operador.actualizado', 1, '1')
  emitirOperador(fuente, 'operador.actualizado', 2, '2')
  emitirOperador(fuente, 'operador.actualizado', 3, '3')

  controlador.suscribir('0', {
    alActualizarOperador: () => {},
    alCrearOperador: () => {},
    alResync: () => {
      resyncs += 1
    },
  })
  assert.equal(resyncs, 1)
  controlador.detener()
})

test('error nativo CONNECTING conserva la fuente y no consulta /me; CLOSED consulta /me', async () => {
  const fuentes: FuenteEventosFalsa[] = []
  const temporizadores: TemporizadorPrueba[] = []
  let comprobaciones = 0
  const programador = crearProgramador(temporizadores)
  const controlador = crearControladorEventosTiempoReal({
    crearFuente: (url) => {
      const fuente = new FuenteEventosFalsa(url)
      fuentes.push(fuente)
      return fuente as unknown as EventSource
    },
    comprobarSesion: async () => {
      comprobaciones += 1
      return 200
    },
    alPerderSesion: () => {},
    ...programador,
  })
  controlador.iniciar()
  const fuente = fuentes[0]!
  fuente.fallar(0)
  assert.equal(comprobaciones, 0)
  assert.equal(fuentes.length, 1)
  assert.equal(temporizadores[0]?.demora, 500)
  temporizadores[0]!.callback()
  assert.equal(controlador.estado.value, 'reconectando')
  assert.equal(fuentes.length, 1, 'Native retry does not create an overlapping EventSource')

  fuente.fallar(2)
  await new Promise((resolver) => setTimeout(resolver, 0))
  assert.equal(comprobaciones, 1)
  assert.equal(temporizadores.at(-1)?.demora, 1000)
  assert.equal(controlador.estado.value, 'reconectando')
  controlador.detener()
})

test('una nueva instantanea autoritativa fija el cursor de la reconexion', async () => {
  const fuentes: FuenteEventosFalsa[] = []
  const temporizadores: TemporizadorPrueba[] = []
  const programador = crearProgramador(temporizadores)
  const controlador = crearControladorEventosTiempoReal({
    crearFuente: (url) => {
      const fuente = new FuenteEventosFalsa(url)
      fuentes.push(fuente)
      return fuente as unknown as EventSource
    },
    comprobarSesion: async () => 200,
    alPerderSesion: () => {},
    ...programador,
  })
  const suscripcion = controlador.suscribir('10', manejadores())
  controlador.iniciar()
  assert.equal(fuentes[0]?.url, '/api/eventos?cursor_eventos=10')
  fuentes[0]!.fallar(2)
  await new Promise((resolver) => setTimeout(resolver, 0))
  suscripcion.actualizarCursor('100')
  temporizadores.at(-1)!.callback()
  assert.equal(fuentes[1]?.url, '/api/eventos?cursor_eventos=100')
  suscripcion.detener()
  controlador.detener()
})

test('solo un 401 confirmado por /me cierra sesion; 429, 5xx y red reintentan', async () => {
  for (const status of [0, 429, 503, 401]) {
    const fuentes: FuenteEventosFalsa[] = []
    const temporizadores: TemporizadorPrueba[] = []
    let sesionesPerdidas = 0
    const programador = crearProgramador(temporizadores)
    const controlador = crearControladorEventosTiempoReal({
      crearFuente: (url) => {
        const fuente = new FuenteEventosFalsa(url)
        fuentes.push(fuente)
        return fuente as unknown as EventSource
      },
      comprobarSesion: async () => status,
      alPerderSesion: () => {
        sesionesPerdidas += 1
      },
      ...programador,
    })
    controlador.iniciar()
    fuentes[0]!.fallar(2)
    await new Promise((resolver) => setTimeout(resolver, 0))
    if (status === 401) {
      assert.equal(sesionesPerdidas, 1)
      assert.equal(controlador.estado.value, 'sesion-perdida')
      assert.equal(temporizadores.filter((temporizador) => !temporizador.cancelado).length, 0)
    } else {
      assert.equal(sesionesPerdidas, 0, `HTTP ${status} must preserve the authenticated session`)
      assert.equal(temporizadores.at(-1)?.demora, 1000)
      assert.equal(controlador.estado.value, 'reconectando')
    }
    controlador.detener()
  }
})

test('los layouts poseen la fuente y los componentes de pagina solo se suscriben', () => {
  const adminLayout = readFileSync(join(WEB_ROOT, 'app', 'layouts', 'admin.vue'), 'utf8')
  const operatorLayout = readFileSync(join(WEB_ROOT, 'app', 'layouts', 'operador.vue'), 'utf8')
  const operatorPage = readFileSync(join(WEB_ROOT, 'app', 'pages', 'operador.vue'), 'utf8')
  const tablePage = readFileSync(
    join(WEB_ROOT, 'app', 'pages', 'admin', 'operadores', 'index.vue'),
    'utf8',
  )
  assert.match(adminLayout, /crearControladorEventosTiempoReal/)
  assert.match(adminLayout, /eventosTiempoReal\.iniciar\(\)/)
  assert.match(operatorLayout, /crearControladorEventosTiempoReal/)
  assert.match(operatorLayout, /eventosTiempoReal\.iniciar\(\)/)
  assert.match(operatorPage, /layout: 'operador'/)
  assert.match(tablePage, /eventosTiempoReal\.suscribir\(/)
  assert.doesNotMatch(tablePage, /new EventSource|crearStreamOperadores/)
})
