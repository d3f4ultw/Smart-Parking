const SEPARADOR_CABECERAS = new Uint8Array([13, 10, 13, 10])
const CODIFICADOR = new TextEncoder()
const DECODIFICADOR = new TextDecoder()
export const MAXIMO_BYTES_FRAME_MJPEG = 1_048_576
const MAXIMO_BYTES_CABECERAS_MJPEG = 8192
const TAMANO_BLOQUE_LECTURA_MJPEG = 64 * 1024

function indiceDe(bytes: Uint8Array, patron: Uint8Array) {
  if (patron.length === 0) return 0
  for (let inicio = 0; inicio <= bytes.length - patron.length; inicio += 1) {
    let coincide = true
    for (let indice = 0; indice < patron.length; indice += 1) {
      if (bytes[inicio + indice] !== patron[indice]) {
        coincide = false
        break
      }
    }
    if (coincide) return inicio
  }
  return -1
}

function unirBytes(actuales: Uint8Array, nuevos: Uint8Array) {
  const unidos = new Uint8Array(actuales.length + nuevos.length)
  unidos.set(actuales)
  unidos.set(nuevos, actuales.length)
  return unidos
}

export function obtenerBoundaryMjpeg(contentType: string) {
  const coincidencia = /^multipart\/x-mixed-replace\s*;.*?\bboundary=(?:"([A-Za-z0-9._-]{1,70})"|([A-Za-z0-9._-]{1,70}))(?:;|$)/i.exec(contentType.trim())
  const boundary = coincidencia?.[1] ?? coincidencia?.[2]
  if (boundary === undefined) {
    throw new Error('El stream no entregó un boundary MJPEG válido.')
  }
  return boundary
}

export class DecodificadorMjpeg {
  private buffer = new Uint8Array(0)
  private esperandoCabeceras = false
  private readonly marcador: Uint8Array

  constructor(boundary: string) {
    if (!/^[A-Za-z0-9._-]{1,70}$/.test(boundary)) {
      throw new Error('El boundary MJPEG no es válido.')
    }
    this.marcador = CODIFICADOR.encode('--' + boundary + '\r\n')
  }

  agregar(chunk: Uint8Array) {
    let frameReciente: Uint8Array | null = null
    for (let inicio = 0; inicio < chunk.length; inicio += TAMANO_BLOQUE_LECTURA_MJPEG) {
      const segmento = chunk.subarray(inicio, inicio + TAMANO_BLOQUE_LECTURA_MJPEG)
      const limiteBuffer = MAXIMO_BYTES_FRAME_MJPEG
        + MAXIMO_BYTES_CABECERAS_MJPEG
        + TAMANO_BLOQUE_LECTURA_MJPEG
        + this.marcador.length
      if (this.buffer.length + segmento.length > limiteBuffer) {
        throw new Error('El buffer del frame MJPEG excede el límite.')
      }
      this.buffer = unirBytes(this.buffer, segmento)
      frameReciente = this.procesarBuffer() ?? frameReciente
    }
    return frameReciente === null ? [] : [frameReciente]
  }

  private procesarBuffer() {
    let frameReciente: Uint8Array | null = null
    while (true) {
      if (!this.esperandoCabeceras) {
        const inicio = indiceDe(this.buffer, this.marcador)
        if (inicio < 0) {
          const conservar = Math.min(this.buffer.length, this.marcador.length - 1)
          this.buffer = this.buffer.slice(this.buffer.length - conservar)
          return frameReciente
        }
        this.buffer = this.buffer.slice(inicio + this.marcador.length)
        this.esperandoCabeceras = true
      }

      const finCabeceras = indiceDe(this.buffer, SEPARADOR_CABECERAS)
      if (finCabeceras < 0) {
        if (this.buffer.length > MAXIMO_BYTES_CABECERAS_MJPEG) {
          throw new Error('Las cabeceras del frame MJPEG exceden el límite.')
        }
        return frameReciente
      }
      if (finCabeceras > MAXIMO_BYTES_CABECERAS_MJPEG) {
        throw new Error('Las cabeceras del frame MJPEG exceden el límite.')
      }

      const cabeceras = DECODIFICADOR.decode(this.buffer.subarray(0, finCabeceras))
      if (!/^content-type\s*:\s*image\/jpeg\s*$/im.test(cabeceras)) {
        throw new Error('El frame MJPEG no contiene una imagen JPEG.')
      }
      const coincidenciaLongitud = /^content-length\s*:\s*(\d+)\s*$/im.exec(cabeceras)
      const longitud = Number(coincidenciaLongitud?.[1])
      if (
        coincidenciaLongitud === null
        || !Number.isSafeInteger(longitud)
        || longitud <= 0
        || longitud > MAXIMO_BYTES_FRAME_MJPEG
      ) {
        throw new Error('El frame MJPEG no tiene una longitud válida.')
      }

      const inicioFrame = finCabeceras + SEPARADOR_CABECERAS.length
      const finFrame = inicioFrame + longitud
      if (this.buffer.length < finFrame) return frameReciente

      const frame = this.buffer.slice(inicioFrame, finFrame)
      if (
        frame.length < 4
        || frame[0] !== 0xff
        || frame[1] !== 0xd8
        || frame[frame.length - 2] !== 0xff
        || frame[frame.length - 1] !== 0xd9
      ) {
        throw new Error('El frame MJPEG no contiene un JPEG completo válido.')
      }
      frameReciente = frame
      this.buffer = this.buffer.slice(finFrame)
      this.esperandoCabeceras = false
    }
  }
}
