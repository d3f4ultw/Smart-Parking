import assert from 'node:assert/strict'
import test from 'node:test'

import {
  construirSolicitudCrearOperador,
  mapearErrorOperador,
  obtenerEstadoErrorOperador,
  validarDatosOperador,
  type DatosFormularioOperador,
} from '../app/utils/operadores.ts'

const datosBase: DatosFormularioOperador = {
  nombre: 'Grace',
  apellido_paterno: 'Hopper',
  apellido_materno: 'Murray',
  correo: 'grace.hopper@example.com',
}

test('valida los cuatro campos requeridos y acepta datos correctos', () => {
  assert.deepEqual(validarDatosOperador(datosBase), {})
})

test('marca individualmente nombres y apellidos vacios o con espacios', () => {
  const campos = [
    ['nombre', 'El nombre es obligatorio.'],
    ['apellido_paterno', 'El apellido paterno es obligatorio.'],
    ['apellido_materno', 'El apellido materno es obligatorio.'],
  ] as const

  for (const [campo, mensaje] of campos) {
    const errores = validarDatosOperador({ ...datosBase, [campo]: '   ' })
    assert.equal(errores[campo], mensaje)
    assert.equal(errores.correo, undefined)
  }
})

test('marca correo vacio y con formato basico invalido', () => {
  assert.equal(
    validarDatosOperador({ ...datosBase, correo: '  ' }).correo,
    'Ingresa un correo electrónico.',
  )
  assert.equal(
    validarDatosOperador({ ...datosBase, correo: 'grace@' }).correo,
    'Ingresa un correo electrónico válido.',
  )
})

test('aplica los limites de longitud acordes con la API', () => {
  assert.equal(
    validarDatosOperador({ ...datosBase, nombre: 'N'.repeat(101) }).nombre,
    'El nombre no puede superar 100 caracteres.',
  )
  assert.equal(
    validarDatosOperador({ ...datosBase, correo: `${'a'.repeat(315)}@x.com` }).correo,
    'El correo no puede superar 320 caracteres.',
  )
})

test('conserva los valores validos al devolver errores por campo', () => {
  const datos = { ...datosBase, apellido_paterno: '  ' }
  const errores = validarDatosOperador(datos)

  assert.equal(errores.apellido_paterno, 'El apellido paterno es obligatorio.')
  assert.equal(datos.nombre, 'Grace')
  assert.equal(datos.apellido_materno, 'Murray')
  assert.equal(datos.correo, 'grace.hopper@example.com')
})

test('construye un payload nuevo con exactamente los cuatro campos', () => {
  const solicitud = construirSolicitudCrearOperador(datosBase)

  assert.deepEqual(Object.keys(solicitud), [
    'nombre',
    'apellido_paterno',
    'apellido_materno',
    'correo',
  ])
  assert.deepEqual(solicitud, datosBase)
  assert.notEqual(solicitud, datosBase)
})

test('mapea duplicados y errores inesperados con mensajes seguros', () => {
  assert.equal(mapearErrorOperador(409), 'Ese correo ya está registrado.')
  assert.equal(mapearErrorOperador(422), 'Revisa los datos ingresados.')
  assert.equal(
    mapearErrorOperador(500),
    'No fue posible crear el operador. Intenta nuevamente.',
  )
  assert.equal(
    mapearErrorOperador(undefined),
    'No fue posible crear el operador. Intenta nuevamente.',
  )
})

test('extrae estados de errores fetch habituales y descarta datos inesperados', () => {
  assert.equal(obtenerEstadoErrorOperador({ status: 409 }), 409)
  assert.equal(obtenerEstadoErrorOperador({ statusCode: 401 }), 401)
  assert.equal(obtenerEstadoErrorOperador({ response: { status: 422 } }), 422)
  assert.equal(obtenerEstadoErrorOperador({ status: '409' }), undefined)
  assert.equal(obtenerEstadoErrorOperador(new Error('fallo')), undefined)
  assert.equal(obtenerEstadoErrorOperador(null), undefined)
})

test('los mensajes publicos no incluyen correo ni detalles de credenciales', () => {
  const mensajes = [
    mapearErrorOperador(409),
    mapearErrorOperador(422),
    mapearErrorOperador(500),
  ]

  for (const mensaje of mensajes) {
    assert.equal(mensaje.includes(datosBase.correo), false)
    assert.equal(mensaje.includes('contraseña'), false)
    assert.equal(mensaje.includes('hash'), false)
    assert.equal(mensaje.includes('token'), false)
  }
})
