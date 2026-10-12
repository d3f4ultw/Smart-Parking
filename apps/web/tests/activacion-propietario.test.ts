import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import test from 'node:test'

import {
  evaluarRequisitosContrasenaPropietario,
  extraerTokenInvitacionPropietario,
  normalizarCampoNombre,
  recuperarProgresoActivacionPropietario,
  rutaActivacionPropietarioSinToken,
  serializarProgresoActivacionPropietario,
  validarPasoPropietario,
  type CredencialesPropietario,
} from '../app/utils/activacion-propietario.ts'

const tokenValido = randomUUID().replaceAll('-', '') + 'ABCDEFGH'
const datos: CredencialesPropietario = {
  nombre: 'Ada',
  apellidoPaterno: 'Lovelace',
  apellidoMaterno: 'Byron',
  contrasenaAdmin: `Administracion ${randomUUID()}`,
  confirmarContrasenaAdmin: '',
  contrasenaLogin: `Acceso separado ${randomUUID()}`,
  confirmarContrasenaLogin: '',
}
datos.confirmarContrasenaAdmin = datos.contrasenaAdmin
datos.confirmarContrasenaLogin = datos.contrasenaLogin

test('evalúa los requisitos de contraseña mostrados en el wizard', () => {
  assert.deepEqual(evaluarRequisitosContrasenaPropietario('Password Segura 1'), {
    longitudValida: true,
    caracteresImprimibles: true,
    incluyeMayuscula: true,
  })
  assert.equal(evaluarRequisitosContrasenaPropietario('corta').longitudValida, false)
  assert.equal(
    evaluarRequisitosContrasenaPropietario('contrasena larga sin mayuscula').incluyeMayuscula,
    false,
  )
  assert.equal(
    evaluarRequisitosContrasenaPropietario('Password\nno imprimible').caracteresImprimibles,
    false,
  )
  assert.equal(evaluarRequisitosContrasenaPropietario(`${'😀'.repeat(8)}A`).longitudValida, false)
  assert.equal(evaluarRequisitosContrasenaPropietario('A'.repeat(129)).longitudValida, false)
})

test('acepta un unico token opaco y elimina el secreto de la ruta', () => {
  const url = new URL(`https://parking.example/activar-propietario?token=${tokenValido}`)
  assert.equal(extraerTokenInvitacionPropietario(url), tokenValido)
  assert.equal(rutaActivacionPropietarioSinToken(), '/activar-propietario')
})

test('rechaza tokens duplicados y valores fuera del alfabeto opaco', () => {
  assert.equal(
    extraerTokenInvitacionPropietario(
      new URL(`https://parking.example/activar-propietario?token=${tokenValido}&token=${tokenValido}`),
    ),
    null,
  )
  assert.equal(
    extraerTokenInvitacionPropietario(
      new URL('https://parking.example/activar-propietario?token=token%2Fcon%2Fbarra'),
    ),
    null,
  )
})

test('el alta nueva valida los tres pasos y mantiene distintas las contraseñas', () => {
  assert.deepEqual(validarPasoPropietario('nueva', 1, datos), {})
  assert.deepEqual(validarPasoPropietario('nueva', 2, datos), {})
  assert.deepEqual(validarPasoPropietario('nueva', 3, datos), {})

  const sinApellido = validarPasoPropietario('nueva', 1, {
    ...datos,
    apellidoPaterno: '  ',
  })
  assert.match(sinApellido.apellidoPaterno ?? '', /apellido paterno/)

  const sinConfirmar = validarPasoPropietario('nueva', 2, {
    ...datos,
    confirmarContrasenaLogin: 'diferente',
  })
  assert.match(sinConfirmar.confirmarContrasenaLogin ?? '', /no coinciden/)

  const iguales = validarPasoPropietario('nueva', 3, {
    ...datos,
    contrasenaAdmin: datos.contrasenaLogin,
    confirmarContrasenaAdmin: datos.contrasenaLogin,
  })
  assert.match(iguales.contrasenaAdmin ?? '', /distinta/)
})

test('el retorno usa dos pasos y no solicita la contraseña de acceso', () => {
  assert.deepEqual(validarPasoPropietario('retorno', 1, datos), {})
  assert.deepEqual(validarPasoPropietario('retorno', 2, datos), {})
  assert.deepEqual(
    validarPasoPropietario('retorno', 2, {
      ...datos,
      contrasenaLogin: '',
      confirmarContrasenaLogin: '',
    }),
    {},
  )
  assert.match(
    validarPasoPropietario('retorno', 2, {
      ...datos,
      confirmarContrasenaAdmin: 'diferente',
    }).confirmarContrasenaAdmin ?? '',
    /no coinciden/,
  )
})

test('normaliza nombres sin combinarlos en un campo de identidad nuevo', () => {
  assert.equal(normalizarCampoNombre('  Ada   Lovelace  '), 'Ada Lovelace')
})

test('el borrador conserva solo datos personales y progresa mientras el desafío vive', () => {
  const vence = '2026-10-12T10:15:00Z'
  const serializado = serializarProgresoActivacionPropietario(
    'nueva',
    vence,
    2,
    datos,
  )
  assert.equal(serializado.includes(datos.contrasenaLogin), false)
  assert.equal(serializado.includes(datos.contrasenaAdmin), false)
  assert.equal(serializado.includes('contrasena'), false)
  assert.deepEqual(
    recuperarProgresoActivacionPropietario(serializado, 'nueva', vence, 3),
    {
      tipoCuenta: 'nueva',
      expiraEn: vence,
      paso: 2,
      nombre: 'Ada',
      apellidoPaterno: 'Lovelace',
      apellidoMaterno: 'Byron',
    },
  )
  assert.equal(
    recuperarProgresoActivacionPropietario(serializado, 'retorno', vence, 2),
    null,
  )
  assert.equal(
    recuperarProgresoActivacionPropietario(serializado, 'nueva', '2026-10-12T10:16:00Z', 3),
    null,
  )
  assert.equal(
    recuperarProgresoActivacionPropietario(
      serializarProgresoActivacionPropietario('retorno', vence, 3, datos),
      'retorno',
      vence,
      2,
    ),
    null,
  )
})
