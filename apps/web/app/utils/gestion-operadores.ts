export type EstadoCuentaOperador =
  | 'pendiente_activacion'
  | 'acceso_habilitado'
  | 'inactivo'

export interface Operador {
  id: number
  nombre: string
  apellido_paterno: string
  apellido_materno: string
  correo: string
  esta_activo: boolean
  estado_cuenta: EstadoCuentaOperador
}

export interface RespuestaListaOperadores {
  operadores: Operador[]
  pagina: number
  tamano_pagina: number
  total: number
  total_paginas: number
}

export interface RespuestaAccionOperador {
  estado:
    | 'operador_desactivado'
    | 'operador_reactivado'
    | 'contrasena_regenerada'
    | 'invitacion_enviada'
}

export function obtenerPaginaSolicitadaOperadores(valor: unknown): number {
  if (typeof valor !== 'string' || !/^\d+$/.test(valor)) {
    return 1
  }

  const pagina = Number(valor)
  return Number.isSafeInteger(pagina) && pagina > 0 ? pagina : 1
}

export function normalizarPaginaOperadores(
  paginaSolicitada: number,
  totalPaginas: number,
): number {
  if (!Number.isSafeInteger(paginaSolicitada) || paginaSolicitada < 1) {
    return 1
  }
  if (!Number.isSafeInteger(totalPaginas) || totalPaginas < 1) {
    return 1
  }
  return Math.min(paginaSolicitada, totalPaginas)
}

export function etiquetaEstadoCuentaOperador(
  estado: EstadoCuentaOperador,
): string {
  if (estado === 'acceso_habilitado') {
    return 'Acceso habilitado'
  }
  if (estado === 'inactivo') {
    return 'Inactivo'
  }
  return 'Pendiente de activación'
}

export function puedeReenviarInvitacionOperador(
  operador: Pick<Operador, 'esta_activo' | 'estado_cuenta'>,
): boolean {
  return operador.esta_activo && operador.estado_cuenta === 'pendiente_activacion'
}

export function puedeRegenerarContrasenaOperador(
  operador: Pick<Operador, 'esta_activo' | 'estado_cuenta'>,
): boolean {
  return operador.esta_activo && operador.estado_cuenta === 'acceso_habilitado'
}

export function mapearErrorGestionOperador(status: number | undefined): string {
  if (status === 404) {
    return 'No se encontró el operador solicitado.'
  }
  if (status === 409) {
    return 'El estado del operador cambió. Actualiza la información e intenta de nuevo.'
  }
  if (status === 503) {
    return 'No fue posible entregar la nueva contraseña. La contraseña anterior se conserva.'
  }
  if (status === 429) {
    return 'Espera antes de volver a enviar la invitación.'
  }
  if (status === 422) {
    return 'El identificador del operador no es válido.'
  }
  return 'No fue posible confirmar la operación. Verifica el estado antes de reintentar.'
}
