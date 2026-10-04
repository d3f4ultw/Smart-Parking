import assert from 'node:assert/strict'
import test from 'node:test'

import {
  evaluarRequisitosNuevaContrasenaOperador,
  extraerTokenInvitacionOperador,
  rutaActivacionSinToken,
  validarNuevaContrasenaOperador,
} from '../app/utils/activacion-operador.ts'

const tokenValido = 'abcdefghijklmnopqrstuvwxzy0123456789_-'

test('extrae el token solo en la ruta de activacion y acepta formato opaco', () => {
  assert.equal(
    extraerTokenInvitacionOperador(
      new URL(`/activar-cuenta?token=${tokenValido}`, 'https://parking.example'),
    ),
    tokenValido,
  )
  assert.equal(
    extraerTokenInvitacionOperador(
      new URL(`/otra-ruta?token=${tokenValido}`, 'https://parking.example'),
    ),
    null,
  )
  assert.equal(
    extraerTokenInvitacionOperador(
      new URL('/activar-cuenta?token=corto', 'https://parking.example'),
    ),
    null,
  )
  assert.equal(
    extraerTokenInvitacionOperador(
      new URL(`/activar-cuenta?token=${tokenValido}%2F`, 'https://parking.example'),
    ),
    null,
  )
})

test('valida longitud, caracteres imprimibles, mayuscula y coincidencia exacta', () => {
  assert.equal(validarNuevaContrasenaOperador('Nueva clave 123', 'Nueva clave 123'), null)
  assert.match(
    validarNuevaContrasenaOperador('corta', 'corta') ?? '',
    /al menos 10/,
  )
  assert.match(
    validarNuevaContrasenaOperador('solo minusculas 123', 'solo minusculas 123') ?? '',
    /may.scula/,
  )
  assert.match(
    validarNuevaContrasenaOperador('Nueva\nclave 123', 'Nueva\nclave 123') ?? '',
    /no válidos/,
  )
  assert.match(
    validarNuevaContrasenaOperador('Nueva clave 123', 'Nueva clave 124') ?? '',
    /no coinciden/,
  )
})

test('indica en vivo longitud, caracteres imprimibles y mayuscula pendientes', () => {
  assert.deepEqual(evaluarRequisitosNuevaContrasenaOperador(''), {
    longitudMinima: false,
    longitudMaxima: true,
    caracteresImprimibles: true,
    mayuscula: false,
  })
  assert.deepEqual(evaluarRequisitosNuevaContrasenaOperador('solo minusculas'), {
    longitudMinima: true,
    longitudMaxima: true,
    caracteresImprimibles: true,
    mayuscula: false,
  })
  assert.deepEqual(evaluarRequisitosNuevaContrasenaOperador(`A${'b'.repeat(128)}`), {
    longitudMinima: true,
    longitudMaxima: false,
    caracteresImprimibles: true,
    mayuscula: true,
  })
  assert.equal(
    evaluarRequisitosNuevaContrasenaOperador('Nueva\nclave').caracteresImprimibles,
    false,
  )
})

test('reemplaza la URL del enlace por la ruta estable sin query', () => {
  assert.equal(rutaActivacionSinToken(), '/activar-cuenta')
})
