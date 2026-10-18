export const RETRASOS_RECONEXION_VISION_MS = [500, 1000, 2000, 4000, 8000] as const
export const RETRASOS_CAPACIDAD_VISION_MS = [1000, 2000, 4000, 8000, 15000] as const
export const LIMITE_SIN_AVANCE_VISION_MS = 6000

export type ProgresoStreamVision = {
  ahora: number
  ultimoFrameRecibido: number
  inicioStream: number
  limiteSinAvance: number
}

export type ClasificacionErrorHttpMjpeg = 'autorizacion' | 'capacidad' | 'transitorio'

export function clasificarErrorHttpMjpeg(statusCode: number): ClasificacionErrorHttpMjpeg {
  if (statusCode === 401 || statusCode === 403) return 'autorizacion'
  if (statusCode === 429) return 'capacidad'
  return 'transitorio'
}

export function retrasoReconexionVision(intentos: number, porCapacidad = false) {
  const retrasos = porCapacidad
    ? RETRASOS_CAPACIDAD_VISION_MS
    : RETRASOS_RECONEXION_VISION_MS
  const indice = Math.max(0, Math.min(Math.floor(intentos), retrasos.length - 1))
  return retrasos[indice]!
}

export function streamVisionSinProgreso(estado: ProgresoStreamVision) {
  const referenciaFrame = estado.ultimoFrameRecibido || estado.inicioStream
  return estado.ahora - referenciaFrame >= estado.limiteSinAvance
}
