import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { aplicarInstantaneaCajon } from '../app/utils/cajones.ts'
import {
  crearControladorEventosTiempoReal,
  type InstantaneaEventoCajon,
} from '../app/utils/eventos-tiempo-real.ts'
import type { RespuestaListaCajones } from '../app/utils/cajones.ts'

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

function datosEventoCajon(overrides: Record<string, unknown> = {}): string {
  return JSON.stringify({
    recurso_tipo: 'cajon',
    recurso_id: 3,
    ocurrido_en: '2026-10-06T12:00:00Z',
    datos: {
      cajon_id: 3,
      numero: 1,
      vision_zone_id: '00000000-0000-4000-8000-000000000003',
      activa: true,
      vision_desactualizada: false,
      estado_fisico: 'OCUPADO',
      estado_operativo: 'DISPONIBLE',
      motivo_operativo: null,
      estado_efectivo: 'OCUPADO',
      estado_fisico_actualizado_en: '2026-10-06T11:59:00Z',
      estado_operativo_actualizado_en: '2026-10-06T10:00:00Z',
      actualizado_en: '2026-10-06T11:59:00Z',
      ...overrides,
    },
  })
}

function listaCajonesPrueba(cursor: string): RespuestaListaCajones {
  return {
    cursor_eventos: cursor,
    vision: {
      stale: false,
      last_heartbeat_at: null,
      last_observation_at: null,
      stale_after_seconds: 45,
    },
    cajones: [
      {
        id: 3,
        numero: 1,
        vision_zone_id: '00000000-0000-4000-8000-000000000003',
        activa: true,
        vision_desactualizada: false,
        estado_fisico: 'LIBRE',
        estado_operativo: 'DISPONIBLE',
        motivo_operativo: null,
        estado_fisico_actualizado_en: null,
        estado_operativo_actualizado_en: '2026-10-06T10:00:00Z',
        creado_en: '2026-10-01T10:00:00Z',
        estado_efectivo: 'LIBRE',
      },
      {
        id: 9,
        numero: 8,
        vision_zone_id: '00000000-0000-4000-8000-000000000009',
        activa: true,
        vision_desactualizada: true,
        estado_fisico: 'DESCONOCIDO',
        estado_operativo: 'DISPONIBLE',
        motivo_operativo: null,
        estado_fisico_actualizado_en: null,
        estado_operativo_actualizado_en: '2026-10-06T10:00:00Z',
        creado_en: '2026-10-01T10:00:00Z',
        estado_efectivo: 'DESCONOCIDO',
      },
    ],
  }
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

test('cajon.actualizado se entrega a su manejador y se reproduce desde el buffer', () => {
  const fuentes: FuenteEventosFalsa[] = []
  const actualizacionesOperador: number[] = []
  const actualizacionesCajon: Array<Record<string, unknown>> = []
  const controlador = crearControladorEventosTiempoReal({
    crearFuente: (url) => {
      const fuente = new FuenteEventosFalsa(url)
      fuentes.push(fuente)
      return fuente as unknown as EventSource
    },
    alPerderSesion: () => {},
  })
  const suscripcion = controlador.suscribir('10', {
    ...manejadores(actualizacionesOperador),
    alActualizarCajon: (datos) => actualizacionesCajon.push(datos),
  })
  controlador.iniciar()
  const fuente = fuentes[0]!
  fuente.abrir()
  fuente.emitir('cajon.actualizado', datosEventoCajon(), '11')
  fuente.emitir('cajon.actualizado', datosEventoCajon(), '11')

  assert.equal(actualizacionesCajon.length, 1)
  assert.equal(actualizacionesCajon[0]?.cajon_id, 3)
  assert.deepEqual(actualizacionesOperador, [])

  const replayCajones: Array<Record<string, unknown>> = []
  const replayOperadores: number[] = []
  const replay = controlador.suscribir('10', {
    ...manejadores(replayOperadores),
    alActualizarCajon: (datos) => replayCajones.push(datos),
  })
  assert.equal(replayCajones.length, 1)
  assert.deepEqual(replayOperadores, [])
  replay.detener()
  suscripcion.detener()
  controlador.detener()
})

test('event IDs older than the last accepted event cannot regress the snapshot', () => {
  const fuentes: FuenteEventosFalsa[] = []
  let respuesta = listaCajonesPrueba('10')
  const controlador = crearControladorEventosTiempoReal({
    crearFuente: (url) => {
      const fuente = new FuenteEventosFalsa(url)
      fuentes.push(fuente)
      return fuente as unknown as EventSource
    },
    alPerderSesion: () => {},
  })
  const suscripcion = controlador.suscribir('10', {
    ...manejadores(),
    alActualizarCajon: (evento) => {
      const resultado = aplicarInstantaneaCajon(respuesta, evento)
      if (resultado.tipo === 'aplicada') {
        respuesta = resultado.respuesta
      }
    },
  })
  controlador.iniciar()
  const fuente = fuentes[0]!
  fuente.abrir()
  fuente.emitir('cajon.actualizado', datosEventoCajon(), '12')
  fuente.emitir(
    'cajon.actualizado',
    datosEventoCajon({ estado_fisico: 'LIBRE', estado_efectivo: 'LIBRE' }),
    '11',
  )

  assert.equal(respuesta.cajones[0]?.estado_efectivo, 'OCUPADO')
  suscripcion.detener()
  controlador.detener()
})

test('operational snapshots allow optional reasons and preserve event ordering', () => {
  const fuentes: FuenteEventosFalsa[] = []
  const entregados: InstantaneaEventoCajon[] = []
  let respuesta = listaCajonesPrueba('10')
  const controlador = crearControladorEventosTiempoReal({
    crearFuente: (url) => {
      const fuente = new FuenteEventosFalsa(url)
      fuentes.push(fuente)
      return fuente as unknown as EventSource
    },
    alPerderSesion: () => {},
  })
  const suscripcion = controlador.suscribir('10', {
    ...manejadores(),
    alActualizarCajon: (evento) => {
      entregados.push(evento)
      const resultado = aplicarInstantaneaCajon(respuesta, evento)
      if (resultado.tipo === 'aplicada') {
        respuesta = resultado.respuesta
      }
    },
  })
  controlador.iniciar()
  const fuente = fuentes[0]!
  fuente.abrir()
  fuente.emitir(
    'cajon.actualizado',
    datosEventoCajon({
      estado_operativo: 'MANTENIMIENTO',
      motivo_operativo: null,
      estado_efectivo: 'NO_DISPONIBLE',
    }),
    '11',
  )
  fuente.emitir(
    'cajon.actualizado',
    datosEventoCajon({
      estado_operativo: 'FUERA_DE_SERVICIO',
      motivo_operativo: null,
      estado_efectivo: 'NO_DISPONIBLE',
    }),
    '12',
  )
  fuente.emitir(
    'cajon.actualizado',
    datosEventoCajon({
      estado_operativo: 'DISPONIBLE',
      motivo_operativo: null,
      estado_efectivo: 'OCUPADO',
    }),
    '13',
  )
  fuente.emitir(
    'cajon.actualizado',
    datosEventoCajon({
      estado_operativo: 'DISPONIBLE',
      motivo_operativo: null,
      estado_efectivo: 'OCUPADO',
    }),
    '13',
  )
  fuente.emitir(
    'cajon.actualizado',
    datosEventoCajon({
      estado_operativo: 'MANTENIMIENTO',
      motivo_operativo: null,
      estado_efectivo: 'NO_DISPONIBLE',
    }),
    '11',
  )

  assert.deepEqual(
    entregados.map(({ estado_operativo, motivo_operativo }) => [
      estado_operativo,
      motivo_operativo,
    ]),
    [
      ['MANTENIMIENTO', null],
      ['FUERA_DE_SERVICIO', null],
      ['DISPONIBLE', null],
    ],
  )
  assert.equal(respuesta.cajones[0]?.estado_operativo, 'DISPONIBLE')
  assert.equal(respuesta.cajones[0]?.estado_efectivo, 'OCUPADO')
  suscripcion.detener()
  controlador.detener()
})

test('an event received while the initial GET is pending is replayed after its list cursor is installed', async () => {
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
  const fuente = fuentes[0]!
  fuente.abrir()

  let resolverGET!: (respuesta: RespuestaListaCajones) => void
  const getPendiente = new Promise<RespuestaListaCajones>((resolver) => {
    resolverGET = resolver
  })
  fuente.emitir('cajon.actualizado', datosEventoCajon(), '11')
  resolverGET(listaCajonesPrueba('10'))

  let respuesta = await getPendiente
  const suscripcion = controlador.suscribir(respuesta.cursor_eventos, {
    ...manejadores(),
    alActualizarCajon: (evento) => {
      const resultado = aplicarInstantaneaCajon(respuesta, evento)
      if (resultado.tipo === 'aplicada') {
        respuesta = resultado.respuesta
      }
    },
  })

  assert.equal(respuesta.cajones[0]?.estado_efectivo, 'OCUPADO')
  assert.equal(respuesta.cajones[1]?.estado_efectivo, 'DESCONOCIDO')
  assert.equal(respuesta.cursor_eventos, '10')
  suscripcion.detener()
  controlador.detener()
})

test('a newer event during manual refresh replays after the stale GET response', async () => {
  const fuentes: FuenteEventosFalsa[] = []
  const controlador = crearControladorEventosTiempoReal({
    crearFuente: (url) => {
      const fuente = new FuenteEventosFalsa(url)
      fuentes.push(fuente)
      return fuente as unknown as EventSource
    },
    alPerderSesion: () => {},
  })
  let respuesta = listaCajonesPrueba('10')
  const crearManejadoresCajones = () => ({
    ...manejadores(),
    alActualizarCajon: (evento: InstantaneaEventoCajon) => {
      const resultado = aplicarInstantaneaCajon(respuesta, evento)
      if (resultado.tipo === 'aplicada') {
        respuesta = resultado.respuesta
      }
    },
  })
  const suscripcionInicial = controlador.suscribir('10', crearManejadoresCajones())
  controlador.iniciar()
  const fuente = fuentes[0]!
  fuente.abrir()

  let resolverGET!: (nuevaRespuesta: RespuestaListaCajones) => void
  const getPendiente = new Promise<RespuestaListaCajones>((resolver) => {
    resolverGET = resolver
  })
  suscripcionInicial.detener()
  fuente.emitir('cajon.actualizado', datosEventoCajon(), '11')
  resolverGET(listaCajonesPrueba('10'))
  respuesta = await getPendiente
  const suscripcionReanudada = controlador.suscribir(
    respuesta.cursor_eventos,
    crearManejadoresCajones(),
  )

  assert.equal(respuesta.cajones[0]?.estado_efectivo, 'OCUPADO')
  assert.equal(respuesta.cajones[1]?.estado_efectivo, 'DESCONOCIDO')
  suscripcionReanudada.detener()
  controlador.detener()
})

test('cajon.actualizado descarta payloads invalidos y recursos incongruentes', () => {
  const fuentes: FuenteEventosFalsa[] = []
  const cajones: number[] = []
  const operadores: number[] = []
  const controlador = crearControladorEventosTiempoReal({
    crearFuente: (url) => {
      const fuente = new FuenteEventosFalsa(url)
      fuentes.push(fuente)
      return fuente as unknown as EventSource
    },
    alPerderSesion: () => {},
  })
  controlador.suscribir('10', {
    ...manejadores(operadores),
    alActualizarCajon: (datos) => cajones.push(datos.cajon_id),
  })
  controlador.iniciar()
  const fuente = fuentes[0]!
  fuente.abrir()
  fuente.emitir(
    'cajon.actualizado',
    JSON.stringify({
      recurso_tipo: 'operador',
      recurso_id: 3,
      ocurrido_en: '2026-10-06T12:00:00Z',
      datos: JSON.parse(datosEventoCajon()).datos,
    }),
    '11',
  )
  fuente.emitir('cajon.actualizado', datosEventoCajon({ cajon_id: 4 }), '11')
  fuente.emitir(
    'cajon.actualizado',
    datosEventoCajon({ estado_efectivo: 'LIBRE' }),
    '11',
  )
  fuente.emitir(
    'cajon.actualizado',
    datosEventoCajon({
      estado_operativo: 'DISPONIBLE',
      motivo_operativo: 'Cierre solicitado',
    }),
    '11',
  )
  fuente.emitir(
    'cajon.actualizado',
    datosEventoCajon({
      estado_operativo: 'MANTENIMIENTO',
      motivo_operativo: '   ',
      estado_efectivo: 'NO_DISPONIBLE',
    }),
    '11',
  )
  fuente.emitir(
    'cajon.actualizado',
    datosEventoCajon({
      estado_operativo: 'FUERA_DE_SERVICIO',
      motivo_operativo: 'x'.repeat(251),
      estado_efectivo: 'NO_DISPONIBLE',
    }),
    '11',
  )
  fuente.emitir(
    'cajon.actualizado',
    datosEventoCajon({
      estado_operativo: 'MANTENIMIENTO',
      motivo_operativo: 17,
      estado_efectivo: 'NO_DISPONIBLE',
    }),
    '11',
  )
  fuente.emitir(
    'cajon.actualizado',
    datosEventoCajon({ filtrado: 'dato inesperado' }),
    '11',
  )
  assert.deepEqual(cajones, [])
  assert.deepEqual(operadores, [])

  fuente.emitir('cajon.actualizado', datosEventoCajon(), '11')
  assert.deepEqual(cajones, [3])
  assert.deepEqual(operadores, [])
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
