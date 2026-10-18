import assert from 'node:assert/strict'
import test from 'node:test'

import {
  clasificarErrorHttpMjpeg,
  LIMITE_SIN_AVANCE_VISION_MS,
  RETRASOS_CAPACIDAD_VISION_MS,
  RETRASOS_RECONEXION_VISION_MS,
  retrasoReconexionVision,
  streamVisionSinProgreso,
} from '../app/utils/vision-stream-recovery.ts'

test('uses complete JPEG parts received by fetch as stream progress', () => {
  assert.equal(streamVisionSinProgreso({
    ahora: 20_000,
    ultimoFrameRecibido: 19_000,
    inicioStream: 12_000,
    limiteSinAvance: LIMITE_SIN_AVANCE_VISION_MS,
  }), false)
})

test('reconnects when the browser has received no complete JPEG part for six seconds', () => {
  assert.equal(streamVisionSinProgreso({
    ahora: 20_000,
    ultimoFrameRecibido: 13_999,
    inicioStream: 12_000,
    limiteSinAvance: LIMITE_SIN_AVANCE_VISION_MS,
  }), true)
})

test('uses the stream start time until the first JPEG part arrives', () => {
  assert.equal(streamVisionSinProgreso({
    ahora: 17_999,
    ultimoFrameRecibido: 0,
    inicioStream: 12_000,
    limiteSinAvance: LIMITE_SIN_AVANCE_VISION_MS,
  }), false)
  assert.equal(streamVisionSinProgreso({
    ahora: 18_000,
    ultimoFrameRecibido: 0,
    inicioStream: 12_000,
    limiteSinAvance: LIMITE_SIN_AVANCE_VISION_MS,
  }), true)
})

test('caps reconnect backoff at the final configured delay', () => {
  assert.deepEqual(
    RETRASOS_RECONEXION_VISION_MS.map((_, intento) => retrasoReconexionVision(intento)),
    [500, 1000, 2000, 4000, 8000],
  )
  assert.equal(retrasoReconexionVision(100), 8000)
})

test('backs off more slowly when the shared viewer capacity returns HTTP 429', () => {
  assert.deepEqual(
    RETRASOS_CAPACIDAD_VISION_MS.map((_, intento) => retrasoReconexionVision(intento, true)),
    [1000, 2000, 4000, 8000, 15000],
  )
  assert.equal(retrasoReconexionVision(100, true), 15000)
  assert.equal(retrasoReconexionVision(0), 500)
})

test('stops protected retries for 401 and 403 and classifies 429 as capacity pressure', () => {
  assert.equal(clasificarErrorHttpMjpeg(401), 'autorizacion')
  assert.equal(clasificarErrorHttpMjpeg(403), 'autorizacion')
  assert.equal(clasificarErrorHttpMjpeg(429), 'capacidad')
  assert.equal(clasificarErrorHttpMjpeg(503), 'transitorio')
})
