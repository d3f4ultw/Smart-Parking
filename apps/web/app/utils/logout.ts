export const MENSAJE_ERROR_LOGOUT =
  'No fue posible cerrar la sesión. Intenta nuevamente.'

export interface RespuestaLogout {
  estado: 'sesion_cerrada'
}

export function mapearErrorLogout(_error: unknown): string {
  return MENSAJE_ERROR_LOGOUT
}
