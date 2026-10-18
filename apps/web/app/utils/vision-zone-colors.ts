const ANGULO_DORADO = 137.508

export function matizVisionZona(numero: number): number {
  if (!Number.isSafeInteger(numero) || numero < 1) return 0
  return ((numero - 1) * ANGULO_DORADO) % 360
}

export function colorVisionZona(numero: number, opacidad?: number): string {
  const matiz = matizVisionZona(numero).toFixed(3).replace(/\.?0+$/, '')
  const alfa = opacidad === undefined ? '' : ` / ${Math.min(1, Math.max(0, opacidad))}`
  return `hsl(${matiz} 78% 56%${alfa})`
}

export function estiloVisionZona(numero: number): Record<string, string> {
  return {
    '--zone-color': colorVisionZona(numero),
    '--zone-fill': colorVisionZona(numero, 0.16),
  }
}
