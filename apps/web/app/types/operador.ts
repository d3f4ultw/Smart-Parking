export type EstadoCuentaOperador = 'PENDIENTE' | 'ACTIVA' | 'INACTIVA'
export type FiltroEstadoOperador = 'TODOS' | EstadoCuentaOperador
export type AccionAdministracionOperador =
  | 'REEMITIR_INVITACION'
  | 'DESACTIVAR'
  | 'REACTIVAR'
  | 'SOLICITAR_RECUPERACION'

/** Estados de la invitación y de su intento de envío; indican lo que se conoce,
 * pero ni «ENVIADO» confirma que el correo haya llegado a su destinatario.
 */
export type EstadoInvitacionOperador =
  | 'ENVIANDO'
  | 'ENVIADO'
  | 'FALLIDO'
  | 'DESCONOCIDO'
  | 'DESHABILITADO'
  | 'EXPIRADA'
  | 'CONSUMIDA'

/** Indica si la cuenta está ligada a un empleado o si es una cuenta antigua sin empleado asociado. */
export type EstadoConciliacionOperador = 'VINCULADO' | 'LEGADO_SIN_VINCULO'

/** Datos básicos de una cuenta de operador y acciones que el dueño puede realizar desde la lista. */
export interface Operador {
  id: string
  nombres: string
  primerApellido: string
  segundoApellido: string | null
  correo: string
  estado: EstadoCuentaOperador
  estadoInvitacion: EstadoInvitacionOperador
  puedeReemitirInvitacion: boolean
  empleadoIdTexto: string | null
  estadoConciliacion: EstadoConciliacionOperador
}

/** Información completa de la cuenta, con fechas y límites de intentos
 * que determinan si se puede renovar la invitación, desactivar o recuperar el acceso.
 */
export interface DetalleOperador extends Operador {
  invitacionGeneradaEn: string | null
  invitacionVenceEn: string | null
  invitacionConsumidaEn: string | null
  creadaEn: string
  reenvioDisponibleEn: string | null
  reemisionesRestantes: number
  recuperacionDisponibleEn: string | null
  recuperacionesRestantes: number
  puedeDesactivar: boolean
  puedeReactivar: boolean
  puedeSolicitarRecuperacion: boolean
}

/** Una página de cuentas de operador y la marca que permite buscar cambios posteriores. */
export interface PaginaOperadores {
  items: Operador[]
  pagina: number
  tamanoPagina: 10
  totalRegistros: number
  totalPaginas: number
  cursorEventos: string
}

export interface RespuestaReemisionInvitacion {
  estadoInvitacion: EstadoInvitacionOperador
  puedeReemitirInvitacion: boolean
  reenvioDisponibleEn: string | null
}

export interface RespuestaSolicitudRecuperacion {
  estadoEnvio: EstadoInvitacionOperador
  venceEn: string
}

export interface RespuestaValidacionRecuperacion {
  valida: true
}
