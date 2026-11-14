export type EstadoConfirmadoVision = 'LIBRE' | 'OCUPADO'

/** Si no hay una observación reciente, el espacio queda como no verificable;
 * no debe mostrarse como libre ni ocupado.
 */
export type EstadoVision = EstadoConfirmadoVision | 'NO_VERIFICABLE'

/** Resultado que la pantalla muestra para un espacio, junto con el último estado
 * confirmado y la hora en que se observó.
 */
export interface CajonVision {
  cajonId: string
  etiqueta: string
  displayName?: string | null
  estado: EstadoVision
  ultimoEstadoConfirmado: EstadoConfirmadoVision | null
  observadoEn: string | null
}
