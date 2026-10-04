import assert from 'node:assert/strict'
import test from 'node:test'

import {
  obtenerNombreCompleto,
  type UsuarioSesion,
} from '../app/utils/sesion.ts'

const usuarioBase: UsuarioSesion = {
  nombre: 'Ada',
  apellido_paterno: 'Lovelace',
  apellido_materno: 'Byron',
  correo: 'ada@example.com',
  rol: 'OPERADOR',
}

test('construye el nombre visible recortando cada campo', () => {
  assert.equal(
    obtenerNombreCompleto({
      ...usuarioBase,
      nombre: ' Ada ',
      apellido_paterno: ' Lovelace  ',
      apellido_materno: ' Byron ',
    }),
    'Ada Lovelace Byron',
  )
})

test('omite apellidos vacíos y usa un nombre seguro de respaldo', () => {
  assert.equal(
    obtenerNombreCompleto({
      ...usuarioBase,
      nombre: 'Ada',
      apellido_paterno: null,
      apellido_materno: '  ',
    }),
    'Ada',
  )
  assert.equal(
    obtenerNombreCompleto({
      ...usuarioBase,
      nombre: null,
      apellido_paterno: null,
      apellido_materno: null,
    }),
    'Operador',
  )
})
