export const MODALIDADES_ESTACIONAMIENTO = [
  {
    valor: 'PRIVADO',
    etiqueta: 'Privado',
    descripcion: 'Privado empresarial',
  },
  {
    valor: 'PUBLICO',
    etiqueta: 'Público',
    descripcion: 'Público comercial',
  },
  {
    valor: 'MIXTO',
    etiqueta: 'Mixto',
    descripcion: 'Clasificación mixta',
  },
] as const

export type ModalidadEstacionamiento =
  typeof MODALIDADES_ESTACIONAMIENTO[number]['valor']

export interface RespuestaModalidadEstacionamiento {
  modalidad: ModalidadEstacionamiento | null
  revision: number
  acceso_suspendido: boolean
}

export interface SolicitudCambiarModalidadEstacionamiento {
  modalidad: ModalidadEstacionamiento
  revision_esperada: number
}

export interface SolicitudCambiarAccesoEstacionamiento {
  acceso_suspendido: boolean
  revision_esperada: number
}

export function obtenerCodigoErrorHttp(error: unknown): number | null {
  if (error === null || typeof error !== 'object') {
    return null
  }

  const errorHttp = error as { status?: unknown; statusCode?: unknown }
  if (typeof errorHttp.statusCode === 'number') {
    return errorHttp.statusCode
  }
  return typeof errorHttp.status === 'number' ? errorHttp.status : null
}

export function mapearErrorConfiguracion(error: unknown): string {
  const codigo = obtenerCodigoErrorHttp(error)
  if (codigo === 401 || codigo === 403) {
    return 'Tu sesión o tus permisos cambiaron. Vuelve a ingresar para continuar.'
  }
  if (codigo === 409) {
    return 'La configuración cambió en otra sesión. Actualiza la página antes de volver a guardar.'
  }
  if (codigo === 422) {
    return 'La modalidad solicitada no es válida.'
  }
  return 'No fue posible consultar o guardar la configuración. Inténtalo de nuevo.'
}

export function puedeGuardarModalidad(
  guardada: ModalidadEstacionamiento | null,
  seleccionada: ModalidadEstacionamiento | '',
  guardando: boolean,
  accesoSuspendido = false,
): boolean {
  return !guardando
    && !accesoSuspendido
    && seleccionada !== ''
    && seleccionada !== guardada
}
