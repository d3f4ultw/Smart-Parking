import assert from 'node:assert/strict'
import test from 'node:test'

import {
  mapearErrorLogout,
  MENSAJE_ERROR_LOGOUT,
} from '../app/utils/logout.ts'

test('mapea cualquier fallo de logout a un mensaje seguro', () => {
  assert.equal(mapearErrorLogout({ status: 500 }), MENSAJE_ERROR_LOGOUT)
  assert.equal(mapearErrorLogout(new Error('fallo de PostgreSQL')), MENSAJE_ERROR_LOGOUT)
})

test('el mensaje de logout no expone detalles internos', () => {
  const mensaje = mapearErrorLogout({
    detail: 'token, hash, cookie y sesion 42',
  })

  assert.equal(mensaje, 'No fue posible cerrar la sesión. Intenta nuevamente.')
  assert.equal(mensaje.includes('token'), false)
  assert.equal(mensaje.includes('hash'), false)
  assert.equal(mensaje.includes('cookie'), false)
  assert.equal(mensaje.includes('PostgreSQL'), false)
})
