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
import { crearDebounceBusquedaOperadores } from '../app/utils/busqueda-operadores.ts'
import {
  compararCursoresEventos,
  crearRegistroCreacionesOperador,
  crearReconciliadorOperadores,
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

test('el debounce agrupa la escritura y confirma solo el texto más reciente', async () => {
  const consultas: string[] = []
  const debounce = crearDebounceBusquedaOperadores((consulta) => {
    consultas.push(consulta)
  }, 40)

  debounce.programar('fer')
  await new Promise((resolve) => setTimeout(resolve, 5))
  debounce.programar('ferna')
  await new Promise((resolve) => setTimeout(resolve, 60))
  assert.deepEqual(consultas, ['ferna'])

  debounce.programar('consulta cancelada')
  debounce.cancelar()
  await new Promise((resolve) => setTimeout(resolve, 50))
  assert.deepEqual(consultas, ['ferna'])
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
  assert.match(page, /eventosTiempoReal\.suscribir\(/)
  assert.match(page, /data\.value\.cursor_eventos/)
  assert.doesNotMatch(page, /new EventSource|crearStreamOperadores/)
  assert.doesNotMatch(page, /Actualizar lista/)
  assert.equal((page.match(/<th scope="col">/g) ?? []).length, 6)
  assert.match(page, /Creado por/)
  assert.match(page, /Fecha de creación/)
  assert.match(page, /fila\.operador\.creado_por/)
  assert.match(page, /fila\.operador\.creado_en/)
  assert.match(page, /COLUMNAS_SKELETON = \[1, 2, 3, 4, 5, 6\]/)
  assert.match(
    page,
    /busqueda\.value\.trim\(\)\.length === 0[\s\S]*buscarServidor\.value\.length === 0[\s\S]*filtroEstado\.value === 'todos'/,
  )
  assert.equal((page.match(/listarOperadores\(/g) ?? []).length, 1)
  assert.equal((page.match(/await refresh\(\)/g) ?? []).length, 1)
  assert.doesNotMatch(modal, /notificarActualizacion|emit\('updated'\)/)
  assert.match(modal, /emit\('operator-state-changed', operadorId\)/)
  assert.match(modal, /emit\('action-busy', operadorId, true\)/)
})

test('la busqueda global se carga desde el servidor y reinicia la pagina', () => {
  const page = readFileSync(
    join(WEB_ROOT, 'app', 'pages', 'admin', 'operadores', 'index.vue'),
    'utf8',
  )
  const composable = readFileSync(
    join(WEB_ROOT, 'app', 'composables', 'useOperadores.ts'),
    'utf8',
  )
  const bff = readFileSync(
    join(WEB_ROOT, 'server', 'api', 'admin', 'operadores.get.ts'),
    'utf8',
  )
  const proxy = readFileSync(
    join(WEB_ROOT, 'server', 'utils', 'proxy-admin-operadores.ts'),
    'utf8',
  )

  assert.match(page, /await useAsyncData<RespuestaListaOperadores>/)
  assert.match(page, /watch: \[paginaSolicitada, buscarServidor\]/)
  assert.match(page, /listarOperadores\(pagina, signal, buscar \|\| undefined\)/)
  assert.match(page, /function aplicarBusquedaEfectiva/)
  assert.match(page, /paginaForzadaBusqueda\.value = true/)
  assert.match(page, /debounceBusqueda\.cancelar\(\)[\s\S]*aplicarBusquedaEfectiva\(''\)/)
  assert.doesNotMatch(page, /toLocaleLowerCase\('es-MX'\)\.includes/)
  assert.match(composable, /signal/)
  assert.match(composable, /\.\.\.\(buscar \? \{ buscar \} : \{\}\)/)
  assert.match(bff, /parametros\.get\('buscar'\)/)
  assert.match(proxy, /parametros\.set\('buscar', buscar\)/)
  assert.match(page, /Página \{\{ paginaMostrada \}\} de \{\{ Math\.max\(data\.total_paginas, 1\) \}\}/)
  assert.match(page, /:disabled="pending \|\| paginaActual >= data\.total_paginas"/)
})
