import assert from 'node:assert/strict'
import test from 'node:test'

import {
  etiquetaEstadoCuentaOperador,
  mapearErrorGestionOperador,
  normalizarPaginaOperadores,
  obtenerPaginaSolicitadaOperadores,
  puedeRegenerarContrasenaOperador,
  puedeReenviarInvitacionOperador,
  type Operador,
  type RespuestaAccionOperador,
  type RespuestaListaOperadores,
} from '../app/utils/gestion-operadores.ts'

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
    estado_cuenta: 'acceso_habilitado',
  }
  const lista: RespuestaListaOperadores = {
    operadores: [operador],
    pagina: 1,
    tamano_pagina: 10,
    total: 1,
    total_paginas: 1,
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
    'estado_cuenta',
  ])
  assert.deepEqual(Object.keys(lista), [
    'operadores',
    'pagina',
    'tamano_pagina',
    'total',
    'total_paginas',
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
