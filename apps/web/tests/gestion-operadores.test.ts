import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import {
  etiquetaEstadoCuentaOperador,
  etiquetaCreadorOperador,
  formatearCreacionOperador,
  mapearErrorGestionOperador,
  normalizarPaginaOperadores,
  obtenerPaginaSolicitadaOperadores,
  puedeRegenerarContrasenaOperador,
  puedeReenviarInvitacionOperador,
  type Operador,
  type RespuestaAccionOperador,
  type RespuestaListaOperadores,
} from '../app/utils/gestion-operadores.ts'
import {
  compararCursoresEventos,
  crearRegistroCreacionesOperador,
  crearReconciliadorOperadores,
  crearStreamOperadores,
  puedeInsertarCreacionEnPagina,
} from '../app/utils/operadores-tiempo-real.ts'

const WEB_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')

test('mapea los estados de gestion a mensajes publicos especificos y seguros', () => {
  assert.equal(
    mapearErrorGestionOperador(404),
    'No se encontró el operador solicitado.',
  )
  assert.equal(
    mapearErrorGestionOperador(409),
    'El estado del operador cambió. Actualiza la información e intenta de nuevo.',
  )
  assert.equal(
    mapearErrorGestionOperador(503),
    'No fue posible entregar la nueva contraseña. La contraseña anterior se conserva.',
  )
  assert.equal(
    mapearErrorGestionOperador(422),
    'El identificador del operador no es válido.',
  )
  assert.equal(
    mapearErrorGestionOperador(500),
    'No fue posible confirmar la operación. Verifica el estado antes de reintentar.',
  )
})

test('el contrato de gestion solo permite los campos y estados publicos', () => {
  const operador: Operador = {
    id: 12,
    nombre: 'Grace',
    apellido_paterno: 'Hopper',
    apellido_materno: 'Murray',
    correo: 'grace@example.com',
    esta_activo: true,
    creado_en: '2026-10-04T12:30:00Z',
    creado_por: {
      id: 5,
      nombre: 'Ada',
      apellido_paterno: 'Lovelace',
      apellido_materno: 'Byron',
      correo: 'ada@example.com',
    },
    estado_cuenta: 'acceso_habilitado',
  }
  const lista: RespuestaListaOperadores = {
    operadores: [operador],
    pagina: 1,
    tamano_pagina: 10,
    total: 1,
    total_paginas: 1,
    cursor_eventos: '42',
  }
  const estados: RespuestaAccionOperador['estado'][] = [
    'operador_desactivado',
    'operador_reactivado',
    'contrasena_regenerada',
    'invitacion_enviada',
  ]

  assert.deepEqual(Object.keys(lista.operadores[0]), [
    'id',
    'nombre',
    'apellido_paterno',
    'apellido_materno',
    'correo',
    'esta_activo',
    'creado_en',
    'creado_por',
    'estado_cuenta',
  ])
  assert.deepEqual(Object.keys(lista), [
    'operadores',
    'pagina',
    'tamano_pagina',
    'total',
    'total_paginas',
    'cursor_eventos',
  ])
  assert.deepEqual(estados, [
    'operador_desactivado',
    'operador_reactivado',
    'contrasena_regenerada',
    'invitacion_enviada',
  ])
})

test('normaliza la pagina de la URL y limita el resultado al total disponible', () => {
  assert.equal(obtenerPaginaSolicitadaOperadores(undefined), 1)
  assert.equal(obtenerPaginaSolicitadaOperadores('2'), 2)
  assert.equal(obtenerPaginaSolicitadaOperadores('02'), 2)
  assert.equal(obtenerPaginaSolicitadaOperadores('0'), 1)
  assert.equal(obtenerPaginaSolicitadaOperadores('2.5'), 1)
  assert.equal(obtenerPaginaSolicitadaOperadores(['2']), 1)
  assert.equal(obtenerPaginaSolicitadaOperadores('999999999999999999999'), 1)
  assert.equal(normalizarPaginaOperadores(4, 3), 3)
  assert.equal(normalizarPaginaOperadores(2, 0), 1)
  assert.equal(normalizarPaginaOperadores(0, 5), 1)
})

test('muestra estados de cuenta y controla acciones segun el estado', () => {
  const pendiente: Operador = {
    id: 13,
    nombre: 'Grace',
    apellido_paterno: 'Hopper',
    apellido_materno: 'Murray',
    correo: 'grace@example.com',
    esta_activo: true,
    creado_en: '2026-10-04T12:30:00Z',
    creado_por: null,
    estado_cuenta: 'pendiente_activacion',
  }
  const habilitado = { ...pendiente, estado_cuenta: 'acceso_habilitado' as const }
  const inactivo = { ...pendiente, esta_activo: false, estado_cuenta: 'inactivo' as const }

  assert.equal(etiquetaEstadoCuentaOperador('pendiente_activacion'), 'Pendiente de activación')
  assert.equal(etiquetaEstadoCuentaOperador('acceso_habilitado'), 'Acceso habilitado')
  assert.equal(etiquetaEstadoCuentaOperador('inactivo'), 'Inactivo')
  assert.equal(puedeReenviarInvitacionOperador(pendiente), true)
  assert.equal(puedeRegenerarContrasenaOperador(pendiente), false)
  assert.equal(puedeReenviarInvitacionOperador(habilitado), false)
  assert.equal(puedeRegenerarContrasenaOperador(habilitado), true)
  assert.equal(puedeReenviarInvitacionOperador(inactivo), false)
  assert.equal(puedeRegenerarContrasenaOperador(inactivo), false)
})

test('los mensajes no devuelven informacion de cuenta ni de credenciales', () => {
  for (const codigo of [404, 409, 422, 503, 500, undefined]) {
    const mensaje = mapearErrorGestionOperador(codigo).toLowerCase()
    assert.equal(mensaje.includes('grace@example.com'), false)
    assert.equal(mensaje.includes('hash'), false)
    assert.equal(mensaje.includes('token'), false)
    assert.equal(mensaje.includes('contrasena anterior'), false)
  }
})

function operadorDePrueba(id: number, correo = `operador-${id}@example.com`): Operador {
  return {
    id,
    nombre: `Operador ${id}`,
    apellido_paterno: 'Prueba',
    apellido_materno: '',
    correo,
    esta_activo: true,
    creado_en: '2026-10-04T12:30:00Z',
    creado_por: null,
    estado_cuenta: 'acceso_habilitado',
  }
}

test('la auditoria muestra atribucion segura, valor neutro y fecha local legible', () => {
  const creador = {
    id: 3,
    nombre: 'Ada',
    apellido_paterno: 'Lovelace',
    apellido_materno: 'Byron',
    correo: 'ada@example.com',
  }
  assert.equal(etiquetaCreadorOperador(creador), 'Ada Lovelace Byron')
  assert.equal(etiquetaCreadorOperador(null), '—')
  assert.equal(
    etiquetaCreadorOperador({ ...creador, nombre: null, apellido_paterno: null, apellido_materno: null }),
    'ada@example.com',
  )
  assert.match(formatearCreacionOperador('2026-10-04T12:30:00Z'), /2026/)
  assert.equal(formatearCreacionOperador('fecha invalida'), '—')
})

test('el alta solo entra en la pagina final si cabe y conserva su orden', () => {
  const fila = [{ id: 11 }, { id: 14 }, { id: 19 }]
  assert.equal(puedeInsertarCreacionEnPagina(20, 2, 2, 10, fila), true)
  assert.equal(puedeInsertarCreacionEnPagina(13, 2, 2, 10, fila), true)
  assert.equal(puedeInsertarCreacionEnPagina(10, 2, 2, 10, fila), false)
  assert.equal(puedeInsertarCreacionEnPagina(20, 1, 2, 10, fila), false)
  assert.equal(puedeInsertarCreacionEnPagina(20, 2, 2, 3, fila), false)
  assert.equal(puedeInsertarCreacionEnPagina(14, 2, 2, 10, fila), false)
  assert.equal(compararCursoresEventos('100000000000000000', '99999999999999999'), 1)
})

test('el registro de altas hace idempotente el eco SSE de la sesion creadora', () => {
  const registro = crearRegistroCreacionesOperador()
  assert.equal(registro.aceptar(42), true)
  assert.equal(registro.aceptar(42), false)
  assert.equal(registro.aceptar(43), true)
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolver) => {
    resolve = resolver
  })
  return { promise, resolve: (value: T) => resolve(value) }
}

test('coalesce eventos del mismo operador y conserva intacta la fila hermana', async () => {
  const solicitudes: Array<{
    id: number
    respuesta: ReturnType<typeof deferred<Operador>>
  }> = []
  const filas = new Map<number, Operador>([
    [1, operadorDePrueba(1)],
    [2, operadorDePrueba(2)],
  ])
  const filaHermana = filas.get(2)
  const idsSkeleton: number[] = []
  let reconciliaciones = 0
  const reconciliador = crearReconciliadorOperadores({
    obtenerOperador: (id) => {
      const respuesta = deferred<Operador>()
      solicitudes.push({ id, respuesta })
      return respuesta.promise
    },
    alCambiarCarga: (id, cargando) => {
      if (cargando) {
        idsSkeleton.push(id)
      } else {
        idsSkeleton.splice(idsSkeleton.lastIndexOf(id), 1)
      }
    },
    alRecibirOperador: (operador) => {
      reconciliaciones += 1
      filas.set(operador.id, operador)
    },
    alFallar: (_id, errorActual) => {
      throw errorActual
    },
  })

  const primera = reconciliador.reconciliar(1)
  const sucia = reconciliador.reconciliar(1)
  assert.deepEqual(idsSkeleton, [1])
  assert.equal(solicitudes.length, 1)
  assert.equal(filas.get(2), filaHermana)

  solicitudes[0]!.respuesta.resolve(operadorDePrueba(1, 'primera@example.com'))
  await new Promise((resolver) => setTimeout(resolver, 0))
  assert.equal(solicitudes.filter((solicitud) => solicitud.id === 1).length, 2)
  assert.deepEqual(idsSkeleton, [1])
  assert.equal(filas.get(2), filaHermana)

  solicitudes[1]!.respuesta.resolve(operadorDePrueba(1, 'final@example.com'))
  await Promise.all([primera, sucia])
  assert.equal(reconciliaciones, 2)
  assert.equal(filas.get(1)?.correo, 'final@example.com')
  assert.equal(filas.get(2), filaHermana)
  assert.deepEqual(idsSkeleton, [])
  reconciliador.detener()
})

test('reconciliaciones de ids distintos avanzan independientemente', async () => {
  const solicitudes: Array<{ id: number; respuesta: ReturnType<typeof deferred<Operador>> }> = []
  const reconciliador = crearReconciliadorOperadores({
    obtenerOperador: (id) => {
      const respuesta = deferred<Operador>()
      solicitudes.push({ id, respuesta })
      return respuesta.promise
    },
    alCambiarCarga: () => {},
    alRecibirOperador: () => {},
    alFallar: (_id, errorActual) => {
      throw errorActual
    },
  })
  const operadorUno = reconciliador.reconciliar(1)
  const operadorDos = reconciliador.reconciliar(2)
  assert.deepEqual(solicitudes.map((solicitud) => solicitud.id), [1, 2])
  solicitudes[1]!.respuesta.resolve(operadorDePrueba(2))
  solicitudes[0]!.respuesta.resolve(operadorDePrueba(1))
  await Promise.all([operadorUno, operadorDos])
  reconciliador.detener()
})

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

test('un stream por pagina, cursor inicial, reconexion nativa y 401 terminal', async () => {
  const fuentes: FuenteEventosFalsa[] = []
  const temporizadores: TemporizadorPrueba[] = []
  const actualizaciones: number[] = []
  const creaciones: number[] = []
  const estados: string[] = []
  let resyncs = 0
  let comprobaciones = 0
  const sesiones: number[] = [200, 401]
  let sesionesPerdidas = 0
  const stream = crearStreamOperadores({
    cursorInicial: '0',
    crearFuente: (url) => {
      const fuente = new FuenteEventosFalsa(url)
      fuentes.push(fuente)
      return fuente as unknown as EventSource
    },
    comprobarSesion: async () => {
      comprobaciones += 1
      return sesiones.shift() ?? 200
    },
    alRecibirActualizacion: (id) => actualizaciones.push(id),
    alRecibirCreacion: (id) => creaciones.push(id),
    alRecibirResync: () => {
      resyncs += 1
    },
    alCambiarEstado: (estado) => estados.push(estado),
    alPerderSesion: () => {
      sesionesPerdidas += 1
    },
    programar: (callback, demora) => {
      const temporizador = { callback, demora, cancelado: false }
      temporizadores.push(temporizador)
      return temporizador as unknown as ReturnType<typeof setTimeout>
    },
    cancelar: (id) => {
      const temporizador = id as unknown as TemporizadorPrueba
      temporizador.cancelado = true
    },
  })

  stream.iniciar()
  stream.iniciar()
  assert.equal(fuentes.length, 1)
  assert.equal(fuentes[0]?.url, '/api/admin/operadores/eventos?cursor_eventos=0')
  fuentes[0]!.abrir()
  fuentes[0]!.emitir('operador.actualizado', '{"operador_id":7}', '1')
  fuentes[0]!.emitir('operador.creado', '{"operador_id":8}', '2')
  fuentes[0]!.emitir('resync', '{}', '3')
  fuentes[0]!.emitir('operador.creado', '{"operador_id":8}', '2')
  assert.deepEqual(actualizaciones, [7])
  assert.deepEqual(creaciones, [8])
  assert.equal(resyncs, 1)

  fuentes[0]!.fallar(0)
  await new Promise((resolver) => setTimeout(resolver, 0))
  assert.equal(comprobaciones, 0)
  assert.equal(fuentes.length, 1)

  fuentes[0]!.fallar(2)
  await new Promise((resolver) => setTimeout(resolver, 0))
  assert.equal(comprobaciones, 1)
  assert.equal(temporizadores[0]?.demora, 1000)
  assert.equal(sesionesPerdidas, 0)
  temporizadores[0]!.callback()
  assert.equal(fuentes.length, 2)
  assert.equal(fuentes[1]?.url, '/api/admin/operadores/eventos?cursor_eventos=3')

  fuentes[1]!.fallar(2)
  await new Promise((resolver) => setTimeout(resolver, 0))
  fuentes[1]!.fallar(2)
  await new Promise((resolver) => setTimeout(resolver, 0))
  assert.equal(comprobaciones, 2)
  assert.equal(sesionesPerdidas, 1)
  assert.equal(estados.at(-1), 'sesion-perdida')
  assert.equal(temporizadores.length, 1)
})

test('429, 5xx y fallo de red en /me no cierran sesion y reintentan con limite', async () => {
  for (const estadoSesion of [0, 429, 503]) {
    const fuentes: FuenteEventosFalsa[] = []
    const temporizadores: TemporizadorPrueba[] = []
    let sesionesPerdidas = 0
    const stream = crearStreamOperadores({
      cursorInicial: '41',
      crearFuente: (url) => {
        const fuente = new FuenteEventosFalsa(url)
        fuentes.push(fuente)
        return fuente as unknown as EventSource
      },
      comprobarSesion: async () => estadoSesion,
      alRecibirActualizacion: () => {},
      alRecibirCreacion: () => {},
      alRecibirResync: () => {},
      alCambiarEstado: () => {},
      alPerderSesion: () => {
        sesionesPerdidas += 1
      },
      programar: (callback, demora) => {
        const temporizador = { callback, demora, cancelado: false }
        temporizadores.push(temporizador)
        return temporizador as unknown as ReturnType<typeof setTimeout>
      },
      cancelar: () => {},
    })
    stream.iniciar()
    fuentes[0]!.fallar(2)
    await new Promise((resolver) => setTimeout(resolver, 0))
    assert.equal(sesionesPerdidas, 0, `HTTP ${estadoSesion} must not sign out ADMIN`)
    assert.equal(temporizadores.length, 1, `HTTP ${estadoSesion} schedules one retry`)
    assert.equal(temporizadores[0]?.demora, 1000)
    stream.detener()
  }
})

test('la pagina conserva SSR, seis columnas, reconcilia por fila y reserva refresh para resync', () => {
  const page = readFileSync(
    join(WEB_ROOT, 'app', 'pages', 'admin', 'operadores', 'index.vue'),
    'utf8',
  )
  const modal = readFileSync(
    join(WEB_ROOT, 'app', 'components', 'admin', 'GestionarOperadorModal.vue'),
    'utf8',
  )
  assert.match(page, /await useAsyncData<RespuestaListaOperadores>/)
  assert.match(page, /onMounted\(\(\) => stream\.iniciar\(\)\)/)
  assert.match(page, /cursorInicial: data\.value\.cursor_eventos/)
  assert.doesNotMatch(page, /Actualizar lista/)
  assert.equal((page.match(/<th scope="col">/g) ?? []).length, 6)
  assert.match(page, /Creado por/)
  assert.match(page, /Fecha de creación/)
  assert.match(page, /fila\.operador\.creado_por/)
  assert.match(page, /fila\.operador\.creado_en/)
  assert.match(page, /COLUMNAS_SKELETON = \[1, 2, 3, 4, 5, 6\]/)
  assert.match(page, /busqueda\.value\.trim\(\)\.length === 0 && filtroEstado\.value === 'todos'/)
  assert.equal((page.match(/listarOperadores\(/g) ?? []).length, 1)
  assert.equal((page.match(/await refresh\(\)/g) ?? []).length, 1)
  assert.doesNotMatch(modal, /notificarActualizacion|emit\('updated'\)/)
  assert.match(modal, /emit\('operator-state-changed', operadorId\)/)
  assert.match(modal, /emit\('action-busy', operadorId, true\)/)
})
