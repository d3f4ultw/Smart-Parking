import assert from 'node:assert/strict'
import test from 'node:test'

import {
  construirSolicitudLogin,
  mapearErrorLogin,
  obtenerRutaDespuesLogin,
  obtenerEstadoErrorLogin,
  validarDatosLogin,
  type DatosFormularioLogin,
} from '../app/utils/login.ts'

const datosBase: DatosFormularioLogin = {
  correo: 'admin@example.com',
  contrasena: '  Contrasena con espacios  ',
}

test('construye el payload sin modificar correo ni contraseña', () => {
  const solicitud = construirSolicitudLogin(datosBase)

  assert.deepEqual(solicitud, {
    correo: 'admin@example.com',
    contrasena: '  Contrasena con espacios  ',
  })
})

test('construye un objeto nuevo para cada solicitud', () => {
  const solicitud = construirSolicitudLogin(datosBase)

  assert.notEqual(solicitud, datosBase)
  assert.equal(datosBase.contrasena, '  Contrasena con espacios  ')
})

test('acepta credenciales con espacios intencionales en la contraseña', () => {
  assert.equal(validarDatosLogin(datosBase), null)
  assert.equal(validarDatosLogin({
    correo: '  admin@example.com  ',
    contrasena: ' contraseña válida ',
  }), null)
})

test('rechaza un correo vacío', () => {
  assert.equal(
    validarDatosLogin({ ...datosBase, correo: '' }),
    'Ingresa tu correo electrónico.',
  )
})

test('rechaza un correo compuesto solamente por espacios', () => {
  assert.equal(
    validarDatosLogin({ ...datosBase, correo: '   ' }),
    'Ingresa tu correo electrónico.',
  )
})

test('rechaza un correo sin separador de identidad', () => {
  assert.equal(
    validarDatosLogin({ ...datosBase, correo: 'admin-smartparking.dev' }),
    'Ingresa un correo electrónico válido.',
  )
})

test('deja la sintaxis completa del correo a cargo del backend', () => {
  assert.equal(validarDatosLogin({ ...datosBase, correo: 'admin@' }), null)
})

test('rechaza una contraseña vacía sin imponer reglas adicionales', () => {
  assert.equal(
    validarDatosLogin({ ...datosBase, contrasena: '' }),
    'Ingresa tu contraseña.',
  )
  assert.equal(validarDatosLogin({ ...datosBase, contrasena: ' ' }), null)
})

test('mapea 401 a un error genérico de autenticación', () => {
  assert.equal(mapearErrorLogin(401), 'Correo o contraseña incorrectos.')
})

test('elige el área según el rol confirmado por el servidor', () => {
  assert.equal(obtenerRutaDespuesLogin('ADMIN'), '/admin')
  assert.equal(obtenerRutaDespuesLogin('OPERADOR'), '/operador')
})

test('mapea cualquier cuenta desconocida al mismo error 401', () => {
  assert.equal(mapearErrorLogin(401), mapearErrorLogin(401))
})

test('mapea 429 al mensaje de reintento', () => {
  assert.equal(
    mapearErrorLogin(429),
    'Demasiados intentos. Intenta nuevamente más tarde.',
  )
})

test('mapea 422 al mensaje de validación seguro', () => {
  assert.equal(mapearErrorLogin(422), 'Revisa los datos ingresados.')
})

test('mapea fallos inesperados al mensaje genérico', () => {
  assert.equal(
    mapearErrorLogin(500),
    'No fue posible iniciar sesión. Intenta nuevamente.',
  )
  assert.equal(
    mapearErrorLogin(undefined),
    'No fue posible iniciar sesión. Intenta nuevamente.',
  )
})

test('extrae el estado de los errores de fetch habituales', () => {
  assert.equal(obtenerEstadoErrorLogin({ status: 401 }), 401)
  assert.equal(obtenerEstadoErrorLogin({ statusCode: 429 }), 429)
  assert.equal(obtenerEstadoErrorLogin({ response: { status: 422 } }), 422)
})

test('ignora valores de estado no numéricos y errores primitivos', () => {
  assert.equal(obtenerEstadoErrorLogin({ status: '401' }), undefined)
  assert.equal(obtenerEstadoErrorLogin(new Error('fallo')), undefined)
  assert.equal(obtenerEstadoErrorLogin(null), undefined)
})

test('los mensajes públicos no incluyen credenciales ni detalles internos', () => {
  const mensajes = [
    mapearErrorLogin(401),
    mapearErrorLogin(422),
    mapearErrorLogin(429),
    mapearErrorLogin(500),
  ]

  for (const mensaje of mensajes) {
    assert.equal(mensaje.includes(datosBase.correo), false)
    assert.equal(mensaje.includes(datosBase.contrasena), false)
    assert.equal(mensaje.includes('token'), false)
    assert.equal(mensaje.includes('hash'), false)
  }
})
