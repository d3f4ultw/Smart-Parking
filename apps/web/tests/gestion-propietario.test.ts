import assert from 'node:assert/strict'
import test from 'node:test'

import { mantenerSesionActivaAnteErrorTransitorio } from '../app/utils/gestion-propietario.ts'

test('conserva la sesión activa ante un fallo transitorio de consulta', () => {
  assert.equal(
    mantenerSesionActivaAnteErrorTransitorio(true, { statusCode: 503 }),
    true,
  )
  assert.equal(mantenerSesionActivaAnteErrorTransitorio(true, new Error('network')), true)
})

test('solo un 401 confirmado elimina la autorización local', () => {
  assert.equal(
    mantenerSesionActivaAnteErrorTransitorio(true, { status: 401 }),
    false,
  )
  assert.equal(
    mantenerSesionActivaAnteErrorTransitorio(false, { statusCode: 503 }),
    false,
  )
})
