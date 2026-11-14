export type TipoEntidadRfid1 = 'CLIENTE' | 'EMPLEADO'
export type FiltroTipoEntidadRfid1 = TipoEntidadRfid1 | 'MIXTO'
export type TipoEstacionamientoRfid1 = 'PUBLICO' | 'PRIVADO' | 'MIXTO'
export type EstadoConexionRfid1 = 'CONECTADO' | 'DESCONECTADO' | 'DESCONOCIDO'

export interface RespuestaModalidadRfid1 {
  tipoEstacionamiento: TipoEstacionamientoRfid1
}

export interface RespuestaEstadoConexionRfid1 {
  estado: EstadoConexionRfid1
  actualizadoEn: string | null
}

/** Situaciones de la lectura de una tarjeta: desde que se inicia hasta que se
 * confirma, cancela, vence o se rechaza.
 */
export type EstadoCapturaRfid1 =
  | 'PENDIENTE'
  | 'ESCANEANDO'
  | 'VISTA_PREVIA'
  | 'COMPLETADA'
  | 'CANCELADA'
  | 'EXPIRADA'
  | 'RECHAZADA'

export type EstadoTarjetaRfid1 = 'ACTIVA' | 'CANCELADA'

export interface PersonaRfid1 {
  tipoEntidad: TipoEntidadRfid1
  codigo: string
  nombreCompleto: string
}

/** Persona encontrada; los candidatos no elegibles siguen visibles, pero no se pueden seleccionar. */
export interface CandidatoPersonaRfid1 {
  tipoEntidad: TipoEntidadRfid1
  codigoPersona: string
  nombreCompleto: string
  estadoAdministrativo: string
  /** Indica si se puede seleccionar para asociar una tarjeta. */
  elegible: boolean
  /** Motivo de API que se explica junto a la opción visible cuando no es elegible. */
  motivoNoElegible: string | null
}

export interface TarjetaRfid1 {
  asociacionId: number
  uid: string | null
  tipoEntidad: TipoEntidadRfid1
  codigoPersona: string
  nombreCompleto: string
  estado: EstadoTarjetaRfid1
  asociadaEn: string
  canceladaEn: string | null
}

/** Tarjetas de una página y total de páginas, para mostrar los controles de navegación. */
export interface PaginaTarjetasRfid1 {
  items: TarjetaRfid1[]
  pagina: number
  tamano: number
  total: number
  totalPaginas: number
}

/** Número leído de la tarjeta y tiempo límite para revisarlo antes de confirmar la asociación. */
export interface VistaPreviaRfid1 {
  uid: string
  previsualizadaEn: string
  confirmacionVenceEn: string
}

export interface ConfirmacionRfid1 {
  capturaId: string
  asociacionId: number
  estado: string
  resultado: string
}

export interface CancelacionTarjetaRfid1 {
  asociacionId: number
  estado: EstadoTarjetaRfid1
}

export interface SolicitudCapturaRfid1 {
  tipoEntidad: TipoEntidadRfid1
  codigoPersona: string
}

export interface RespuestaInicioCapturaRfid1 {
  capturaId: string
  estado: EstadoCapturaRfid1
  expiraEn: string
}

/** Datos de una lectura que permiten consultar su resultado aunque el último aviso
 * no haya llegado o la pantalla se haya vuelto a abrir.
 */
export interface CapturaRfid1 extends RespuestaInicioCapturaRfid1 {
  tipoEntidad: TipoEntidadRfid1
  codigoPersona: string
  resultado: string | null
  codigoError: string | null
}
