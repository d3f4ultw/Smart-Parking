export type EstadoCuentaOperador =
  | 'pendiente_activacion'
  | 'acceso_habilitado'
  | 'inactivo'

export interface CreadorOperador {
  id: number
  nombre: string | null
  apellido_paterno: string | null
  apellido_materno: string | null
  correo: string
}

export interface Operador {
  id: number
  nombre: string
  apellido_paterno: string
  apellido_materno: string
  correo: string
  esta_activo: boolean
  creado_en: string
  creado_por: CreadorOperador | null
  estado_cuenta: EstadoCuentaOperador
}

export interface DetalleOperadorConCooldown {
  operador: Operador
  cooldown_reenvio_segundos: number
}

export interface RespuestaListaOperadores {
  operadores: Operador[]
  pagina: number
  tamano_pagina: number
  total: number
  total_paginas: number
  cursor_eventos: string
}

const FORMATO_FECHA_CREACION = new Intl.DateTimeFormat('es-MX', {
  dateStyle: 'medium',
  timeStyle: 'short',
  timeZone: 'America/Mexico_City',
})

export function etiquetaCreadorOperador(
  creador: CreadorOperador | null,
): string {
  if (creador === null) {
    return '—'
  }

  const nombre = [
    creador.nombre,
    creador.apellido_paterno,
    creador.apellido_materno,
  ].filter(Boolean).join(' ')
  return nombre || creador.correo
}

export function formatearCreacionOperador(valor: string): string {
  const fecha = new Date(valor)
  return Number.isNaN(fecha.getTime())
    ? '—'
    : FORMATO_FECHA_CREACION.format(fecha)
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

export function obtenerSegundosRetryAfter(valor: string | null): number | null {
  if (valor === null || !/^\d+$/.test(valor)) {
    return null
  }

  const segundos = Number(valor)
  return Number.isSafeInteger(segundos) && segundos > 0 && segundos <= 86_400
    ? segundos
    : null
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
