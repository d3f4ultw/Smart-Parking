export const RETRASOS_RECONEXION_RAW_VISION_MS = [500, 1000, 2000, 4000, 8000] as const
export const LIMITE_SIN_AVANCE_RAW_VISION_MS = 6000

export type EstadoGuardadoCalibracion =
  | 'editando'
  | 'guardando'
  | 'eliminando'
  | 'aplicando'
  | 'recuperando'
  | 'actualizando'
  | 'listo'
  | 'error'

export type ProgresoStreamRawVision = {
  ahora: number
  ultimoFrameMostrado: number
  inicioStream: number
  streamSolicitado: boolean
  limiteSinAvance: number
}

export function puedeMantenerStreamCrudoVision(actual: {
  mode: 'simulation' | 'camera'
  source_connected: boolean
  frame_fresh: boolean
} | null) {
  return actual?.mode === 'camera'
}

export function puedeNavegarDuranteGuardado(estado: EstadoGuardadoCalibracion) {
  return estado !== 'guardando' && estado !== 'eliminando'
}

export function estadoTrasConfirmarGuardado(
  revisionEsperada: number,
  revisionAplicada: number | null,
  fuenteVigente: boolean,
): EstadoGuardadoCalibracion {
  if (revisionAplicada === null || revisionAplicada < revisionEsperada) return 'aplicando'
  return fuenteVigente ? 'listo' : 'recuperando'
}

export function sincronizacionTrasGuardadoResuelta(
  estado: EstadoGuardadoCalibracion,
  revisionEsperada: number,
  revisionAplicada: number | null,
  fuenteConectada: boolean,
  frameFresco: boolean,
) {
  return (
    (estado === 'aplicando' || estado === 'recuperando')
    && revisionAplicada !== null
    && revisionAplicada >= revisionEsperada
    && fuenteConectada
    && frameFresco
  )
}

export function retrasoReconexionRawVision(intentos: number) {
  const indice = Math.max(
    0,
    Math.min(Math.floor(intentos), RETRASOS_RECONEXION_RAW_VISION_MS.length - 1),
  )
  return RETRASOS_RECONEXION_RAW_VISION_MS[indice]!
}

export function streamRawVisionSinProgreso(estado: ProgresoStreamRawVision) {
  if (!estado.streamSolicitado) return false
  const referenciaFrame = estado.ultimoFrameMostrado || estado.inicioStream
  return estado.ahora - referenciaFrame >= estado.limiteSinAvance
}
