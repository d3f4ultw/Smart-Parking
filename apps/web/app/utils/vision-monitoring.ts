export type EstadoFuenteMonitoreoVision = {
  mode: 'simulation' | 'camera'
  source_connected: boolean
  processing: boolean
  configuration_revision: number
  applied_revision: number | null
  frame_fresh: boolean
  annotated_frame_fresh: boolean
}

export function puedeMantenerStreamVision(
  actual: EstadoFuenteMonitoreoVision | null,
): boolean {
  return actual?.mode === 'camera'
}

export function puedeMostrarFrameAnotadoVision(
  actual: EstadoFuenteMonitoreoVision | null,
): boolean {
  return Boolean(
    actual
    && puedeMantenerStreamVision(actual)
    && actual.source_connected
    && actual.processing
    && actual.frame_fresh
    && actual.annotated_frame_fresh
    && actual.applied_revision === actual.configuration_revision,
  )
}
