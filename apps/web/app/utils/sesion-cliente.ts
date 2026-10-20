export interface ClienteIdentidad {
  nombre: string
  apellido_paterno: string
  apellido_materno: string | null
  correo: string
  correo_verificado: boolean
}

export interface RespuestaSesionCliente {
  autenticado: true
  cliente: ClienteIdentidad
}

export type EstadoSesionCliente = 'desconocida' | 'autenticada' | 'no_autenticada'

export interface RespuestaLogoutCliente {
  estado: 'sesion_cerrada'
}

export function obtenerEstadoErrorSesionCliente(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null) {
    return undefined
  }

  const valor = error as { status?: unknown; statusCode?: unknown }
  if (typeof valor.statusCode === 'number') {
    return valor.statusCode
  }
  return typeof valor.status === 'number' ? valor.status : undefined
}

export function mapearErrorLoginCliente(estado: number | undefined): string {
  if (estado === 429) {
    return 'Se alcanzó el límite de intentos. Espera un momento e inténtalo de nuevo.'
  }
  if (estado === 401) {
    return 'El correo o la contraseña no coinciden.'
  }
  if (estado === 422) {
    return 'Revisa el correo y la contraseña.'
  }
  return 'No fue posible iniciar sesión. Inténtalo más tarde.'
}
