import assert from 'node:assert/strict'
import test from 'node:test'

import {
  DecodificadorMjpeg,
  MAXIMO_BYTES_FRAME_MJPEG,
  obtenerBoundaryMjpeg,
} from '../app/utils/vision-mjpeg.ts'

const encoder = new TextEncoder()

function parte(boundary: string, frame: Uint8Array) {
  const cabeceras = encoder.encode(
    '--' + boundary
    + '\r\nContent-Type: image/jpeg\r\nContent-Length: '
    + frame.length
    + '\r\n\r\n',
  )
  const cierre = encoder.encode('\r\n')
  const completa = new Uint8Array(cabeceras.length + frame.length + cierre.length)
  completa.set(cabeceras)
  completa.set(frame, cabeceras.length)
  completa.set(cierre, cabeceras.length + frame.length)
  return completa
}

function unir(partes: Uint8Array[]) {
  const longitud = partes.reduce((total, item) => total + item.length, 0)
  const completa = new Uint8Array(longitud)
  let posicion = 0
  for (const item of partes) {
    completa.set(item, posicion)
    posicion += item.length
  }
  return completa
}

test('reads JPEG parts when boundaries and payloads split across chunks', () => {
  const boundary = 'vision-test-boundary'
  const frameUno = new Uint8Array([255, 216, 1, 2, 3, 255, 217])
  const frameDos = new Uint8Array([255, 216, 4, 5, 6, 7, 255, 217])
  const stream = unir([
    encoder.encode('\r\n'),
    parte(boundary, frameUno),
    parte(boundary, frameDos),
  ])
  const decodificador = new DecodificadorMjpeg(boundary)
  const frames: Uint8Array[] = []

  for (let posicion = 0; posicion < stream.length; posicion += 3) {
    frames.push(...decodificador.agregar(stream.subarray(posicion, posicion + 3)))
  }

  assert.deepEqual(frames.map(frame => Array.from(frame)), [
    Array.from(frameUno),
    Array.from(frameDos),
  ])
})

test('keeps only the latest complete JPEG from a coalesced network chunk', () => {
  const boundary = 'vision-test-boundary'
  const frames = Array.from({ length: 80 }, (_, indice) => new Uint8Array([
    255, 216, indice, ...new Array(2040).fill(indice), 255, 217,
  ]))
  const decodificador = new DecodificadorMjpeg(boundary)
  const recientes = decodificador.agregar(unir(frames.map(frame => parte(boundary, frame))))

  assert.equal(recientes.length, 1)
  assert.deepEqual(Array.from(recientes[0]!), Array.from(frames.at(-1)!))
})

test('reads a 720p-sized raw JPEG through ReadableStream within the current limit', async () => {
  const boundary = 'vision-720p-boundary'
  const frame = new Uint8Array(768 * 1024)
  frame[0] = 255
  frame[1] = 216
  frame[frame.length - 2] = 255
  frame[frame.length - 1] = 217
  const multipart = parte(boundary, frame)
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (let inicio = 0; inicio < multipart.length; inicio += 64 * 1024) {
        controller.enqueue(multipart.subarray(inicio, inicio + 64 * 1024))
      }
      controller.close()
    },
  })
  const lector = stream.getReader()
  const decodificador = new DecodificadorMjpeg(boundary)
  const frames: Uint8Array[] = []

  while (true) {
    const siguiente = await lector.read()
    if (siguiente.done) break
    frames.push(...decodificador.agregar(siguiente.value))
  }

  assert.equal(frame.length, 768 * 1024)
  assert.equal(frame.length <= MAXIMO_BYTES_FRAME_MJPEG, true)
  assert.equal(frames.length, 1)
  assert.equal(frames[0]?.length, frame.length)
  assert.equal(frames[0]?.[0], 255)
  assert.equal(frames[0]?.[1], 216)
})

test('accepts quoted multipart boundaries from the BFF content type', () => {
  assert.equal(
    obtenerBoundaryMjpeg('multipart/x-mixed-replace; boundary="vision-123"'),
    'vision-123',
  )
})

test('rejects oversized, empty, or non-JPEG multipart parts', () => {
  const boundary = 'vision-test-boundary'
  const decoder = new DecodificadorMjpeg(boundary)
  assert.throws(
    () => decoder.agregar(encoder.encode(
      '--' + boundary
      + '\r\nContent-Type: image/jpeg\r\nContent-Length: '
      + (MAXIMO_BYTES_FRAME_MJPEG + 1)
      + '\r\n\r\n',
    )),
    /longitud válida/,
  )

  const decoderNoJpeg = new DecodificadorMjpeg(boundary)
  assert.throws(
    () => decoderNoJpeg.agregar(encoder.encode(
      '--' + boundary
      + '\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nok',
    )),
    /imagen JPEG/,
  )

  const decoderJpegInvalido = new DecodificadorMjpeg(boundary)
  assert.throws(
    () => decoderJpegInvalido.agregar(encoder.encode(
      '--' + boundary
      + '\r\nContent-Type: image/jpeg\r\nContent-Length: 4\r\n\r\nnope',
    )),
    /JPEG completo válido/,
  )

  const decoderCabeceras = new DecodificadorMjpeg(boundary)
  assert.throws(
    () => decoderCabeceras.agregar(encoder.encode(
      '--' + boundary + '\r\n' + 'X'.repeat(8193),
    )),
    /cabeceras.*límite/,
  )
})
