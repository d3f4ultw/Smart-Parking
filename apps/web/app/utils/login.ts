import type { RolUsuario } from './sesion'

export interface DatosFormularioLogin {
  correo: string
  contrasena: string
}

export interface SolicitudLogin {
  correo: string
  contrasena: string
}

export interface RespuestaLogin {
  estado: 'credenciales_validas'
  rol: RolUsuario
}

export type RutaDespuesLogin = '/admin' | '/operador'

export function obtenerRutaDespuesLogin(rol: RolUsuario): RutaDespuesLogin {
  return rol === 'ADMIN' ? '/admin' : '/operador'
}

export function validarDatosLogin(
  datos: DatosFormularioLogin,
): string | null {
  const correoParaValidar = datos.correo.trim()

  if (correoParaValidar.length === 0) {
    return 'Ingresa tu correo electrónico.'
  }

  if (!correoParaValidar.includes('@')) {
    return 'Ingresa un correo electrónico válido.'
  }

  if (datos.contrasena.length === 0) {
    return 'Ingresa tu contraseña.'
  }

  return null
}

export function construirSolicitudLogin(
  datos: DatosFormularioLogin,
): SolicitudLogin {
  return {
    correo: datos.correo,
    contrasena: datos.contrasena,
  }
}

export function obtenerEstadoErrorLogin(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null) {
    return undefined
  }

  const posibleError = error as {
    status?: unknown
    statusCode?: unknown
    response?: { status?: unknown }
  }

  if (typeof posibleError.status === 'number') {
    return posibleError.status
  }
  if (typeof posibleError.statusCode === 'number') {
    return posibleError.statusCode
  }
  if (typeof posibleError.response?.status === 'number') {
    return posibleError.response.status
  }

  return undefined
}

export function mapearErrorLogin(status: number | undefined): string {
  if (status === 401) {
    return 'Correo o contraseña incorrectos.'
  }
  if (status === 429) {
    return 'Demasiados intentos. Intenta nuevamente más tarde.'
  }
  if (status === 422) {
    return 'Revisa los datos ingresados.'
  }
  return 'No fue posible iniciar sesión. Intenta nuevamente.'
}
