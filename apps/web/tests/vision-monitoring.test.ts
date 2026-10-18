import assert from 'node:assert/strict'
import test from 'node:test'
import {
  puedeMantenerStreamVision,
  puedeMostrarFrameAnotadoVision,
  type EstadoFuenteMonitoreoVision,
} from '../app/utils/vision-monitoring.ts'

function estadoFuente(
  cambios: Partial<EstadoFuenteMonitoreoVision> = {},
): EstadoFuenteMonitoreoVision {
  return {
    mode: 'camera',
    source_connected: true,
    processing: true,
    configuration_revision: 8,
    applied_revision: 8,
    frame_fresh: true,
    annotated_frame_fresh: true,
    ...cambios,
  }
}

test('keeps the annotated subscription while camera health and a zone revision catch up', () => {
  const pendingRevision = estadoFuente({
    configuration_revision: 9,
    applied_revision: 8,
    source_connected: false,
    processing: false,
    frame_fresh: false,
    annotated_frame_fresh: false,
  })

  assert.equal(puedeMantenerStreamVision(pendingRevision), true)
  assert.equal(puedeMostrarFrameAnotadoVision(pendingRevision), false)
})

test('shows annotated frames only after Vision applies the current revision', () => {
  assert.equal(puedeMostrarFrameAnotadoVision(estadoFuente()), true)
  assert.equal(
    puedeMostrarFrameAnotadoVision(estadoFuente({ frame_fresh: false })),
    false,
  )
  assert.equal(
    puedeMostrarFrameAnotadoVision(estadoFuente({ annotated_frame_fresh: false })),
    false,
  )
  assert.equal(
    puedeMostrarFrameAnotadoVision(estadoFuente({ applied_revision: 7 })),
    false,
  )
})

test('stops camera streams only outside camera mode', () => {
  assert.equal(puedeMantenerStreamVision(null), false)
  assert.equal(puedeMantenerStreamVision(estadoFuente({ mode: 'simulation' })), false)
  assert.equal(puedeMantenerStreamVision(estadoFuente({ source_connected: false })), true)
  assert.equal(puedeMantenerStreamVision(estadoFuente({ processing: false })), true)
})
