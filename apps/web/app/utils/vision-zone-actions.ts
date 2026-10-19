export type ModoEditorVision = 'nuevo' | 'editar'
export type AbrirEditorVision = (url: string, destino: string, opciones: string) => unknown

export function urlEditorVision(modo: ModoEditorVision, zoneId?: string): string {
  const parametros = new URLSearchParams({ mode: modo === 'nuevo' ? 'create' : 'edit' })
  if (modo === 'editar' && zoneId) parametros.set('zoneId', zoneId)
  return `/admin/vision/calibracion/editor?${parametros.toString()}`
}

export function abrirEditorVision(
  abrir: AbrirEditorVision,
  modo: ModoEditorVision,
  zoneId?: string,
): void {
  abrir(urlEditorVision(modo, zoneId), '_blank', 'noopener,noreferrer')
}
