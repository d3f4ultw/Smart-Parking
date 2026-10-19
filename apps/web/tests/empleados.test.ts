import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  construirCapacidadesEmpleados,
  construirNombreCompletoEmpleado,
  construirSolicitudRegistrarEmpleado,
  mapearErrorEmpleados,
  obtenerEstadoErrorEmpleado,
  obtenerPaginaSolicitadaEmpleados,
  validarDatosEmpleado,
  type Empleado,
} from '../app/utils/empleados.ts'

const paginaEmpleados = readFileSync(
  new URL('../app/pages/admin/empleados/index.vue', import.meta.url),
  'utf8',
)

test('las capacidades muestran cada accion por separado y reservan el acceso inicial al Dueño', () => {
  assert.deepEqual(construirCapacidadesEmpleados('OWNER'), {
    leer: true,
    registrar: true,
    cambiar_estado: true,
  })
  assert.deepEqual(construirCapacidadesEmpleados('OPERADOR'), {
    leer: false,
    registrar: false,
    cambiar_estado: false,
  })
  assert.deepEqual(
    construirCapacidadesEmpleados('OPERADOR', ['leer', 'cambiar_estado']),
    { leer: true, registrar: false, cambiar_estado: true },
  )
  assert.deepEqual(construirCapacidadesEmpleados(undefined), {
    leer: false,
    registrar: false,
    cambiar_estado: false,
  })
})

test('la validacion admite apellido materno opcional y exige nombres y turno', () => {
  const errores = validarDatosEmpleado({
    nombres: '   ',
    apellido_paterno: '',
    apellido_materno: 'A'.repeat(101),
    turno_empleado_id: '0',
  })

  assert.equal(errores.nombres, 'Los nombres son obligatorios.')
  assert.equal(errores.apellido_paterno, 'El apellido paterno es obligatorio.')
  assert.equal(
    errores.apellido_materno,
    'El apellido materno no puede superar 100 caracteres.',
  )
  assert.equal(errores.turno_empleado_id, 'Selecciona un turno disponible.')

  assert.deepEqual(validarDatosEmpleado({
    nombres: ' Ana María ',
    apellido_paterno: ' López ',
    apellido_materno: ' ',
    turno_empleado_id: '4',
  }), {})
})

test('el contrato del formulario normaliza nombres y no agrega el estado inicial', () => {
  const solicitud = construirSolicitudRegistrarEmpleado({
    nombres: ' Ana María ',
    apellido_paterno: ' López ',
    apellido_materno: ' Pérez ',
    turno_empleado_id: '12',
  })

  assert.deepEqual(solicitud, {
    nombres: 'Ana María',
    apellido_paterno: 'López',
    apellido_materno: 'Pérez',
    turno_empleado_id: 12,
  })
  assert.equal('esta_activo' in solicitud, false)
  assert.deepEqual(
    construirSolicitudRegistrarEmpleado({
      nombres: 'Ana',
      apellido_paterno: 'López',
      apellido_materno: '   ',
      turno_empleado_id: '3',
    }).apellido_materno,
    null,
  )
})

test('el nombre completo omite el apellido materno ausente', () => {
  const empleado: Empleado = {
    id: '9007199254740993',
    codigo_empleado: 'E-0001',
    nombres: 'Ana María',
    apellido_paterno: 'López',
    apellido_materno: null,
    turno: { id: '1', codigo: 'MATUTINO', nombre: 'Matutino' },
    esta_activo: true,
    revision_estado: 1,
    creado_en: '2026-10-19T12:00:00Z',
    actualizado_en: '2026-10-19T12:00:00Z',
  }
  assert.equal(construirNombreCompletoEmpleado(empleado), 'Ana María López')
  assert.equal(empleado.id, '9007199254740993')
  assert.equal(empleado.codigo_empleado, 'E-0001')
})

test('la interfaz muestra el código del empleado y conserva el ID para operar', () => {
  assert.match(paginaEmpleados, /<th scope="col">Código<\/th>/)
  assert.match(
    paginaEmpleados,
    /<td class="employee-id">\{\{ empleado\.codigo_empleado \}\}<\/td>/,
  )
  assert.match(
    paginaEmpleados,
    /Empleado \$\{resultado\.empleado\.codigo_empleado\} registrado como Activo\./,
  )
  assert.match(
    paginaEmpleados,
    /El registro ya existía\. Código de empleado: \$\{resultado\.empleado\.codigo_empleado\}\./,
  )
  assert.match(paginaEmpleados, /Empleado \$\{actualizado\.codigo_empleado\}:/)
  assert.match(paginaEmpleados, /cambiarEstadoEmpleado\(empleado\.id, \{/)
})

test('la pagina solicitada rechaza entradas inválidas y enteros inseguros', () => {
  assert.equal(obtenerPaginaSolicitadaEmpleados('3'), 3)
  assert.equal(obtenerPaginaSolicitadaEmpleados('0'), 1)
  assert.equal(obtenerPaginaSolicitadaEmpleados('1e3'), 1)
  assert.equal(obtenerPaginaSolicitadaEmpleados('9007199254740992'), 1)
  assert.equal(obtenerPaginaSolicitadaEmpleados(['2']), 1)
})

test('los errores de autenticación, modalidad y concurrencia tienen mensajes claros', () => {
  assert.equal(
    mapearErrorEmpleados(409, 'leer'),
    'El módulo de empleados solo está disponible en modalidades Empresarial y Mixta.',
  )
  assert.match(mapearErrorEmpleados(409, 'cambiar_estado'), /otra sesión/)
  assert.match(mapearErrorEmpleados(401, 'registrar'), /Inicia sesión/)
  assert.equal(obtenerEstadoErrorEmpleado({ response: { status: 422 } }), 422)
  assert.equal(obtenerEstadoErrorEmpleado(new Error('fallo')), undefined)
})
