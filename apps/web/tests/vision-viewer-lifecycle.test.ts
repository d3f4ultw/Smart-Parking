import assert from 'node:assert/strict'
import test from 'node:test'
import { crearCicloVidaVisor } from '../app/utils/vision-viewer-lifecycle.ts'

function crearEventoPageshow(persisted: boolean) {
  const evento = new Event('pageshow')
  Object.defineProperty(evento, 'persisted', { value: persisted })
  return evento
}

test('suspends on pagehide and resumes once only for a BFCache pageshow', () => {
  const objetivo = new EventTarget()
  let suspensiones = 0
  let restauraciones = 0
  const ciclo = crearCicloVidaVisor(
    objetivo,
    () => { suspensiones += 1 },
    () => { restauraciones += 1 },
  )

  ciclo.registrar()
  ciclo.registrar()
  objetivo.dispatchEvent(new Event('pagehide'))
  objetivo.dispatchEvent(crearEventoPageshow(false))
  objetivo.dispatchEvent(crearEventoPageshow(true))

  assert.equal(suspensiones, 1)
  assert.equal(restauraciones, 1)

  ciclo.liberar()
  ciclo.liberar()
  objetivo.dispatchEvent(new Event('pagehide'))
  objetivo.dispatchEvent(crearEventoPageshow(true))

  assert.equal(suspensiones, 1)
  assert.equal(restauraciones, 1)
})
