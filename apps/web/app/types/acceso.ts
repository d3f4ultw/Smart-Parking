export type LectorAccesos = 'RFID2' | 'RFID3' | 'MANUAL'
export type FiltroLectorAccesos = 'TODOS' | LectorAccesos
export type ResultadoAcceso = 'AUTORIZADA' | 'DENEGADA'
export type FiltroResultadoAccesos = 'TODOS' | ResultadoAcceso
export type PeriodoHistorialAccesos =
  | 'HOY'
  | 'ULTIMOS_7_DIAS'
  | 'ULTIMOS_30_DIAS'
  | 'TODO'
  | 'PERSONALIZADO'

export interface PersonaAcceso {
  tipo: 'CLIENTE' | 'EMPLEADO'
  nombre: string
}

export interface EventoAcceso {
  id: string | number
  ocurridoEn: string
  ocurridoEnLocal: string
  lector: LectorAccesos
  resultado: ResultadoAcceso
  motivo: string | null
  persona: PersonaAcceso | null
}

/** Una página del historial y la referencia tomada antes de leerla,
 * que sirve para pedir avisos de cambios posteriores sin saltarse novedades.
 */
export interface PaginaHistorialAccesos {
  items: EventoAcceso[]
  pagina: number
  tamano: number
  totalRegistros: number
  haySiguiente: boolean
  zonaHoraria: string
  cursorEventos: string | null
}

/** Capacidad total, vehículos dentro, lugares disponibles y marca desde la que
 * pueden buscarse cambios más recientes.
 */
export interface ResumenCapacidadRfid {
  capacidadTotal: number
  vehiculosDentro: number
  capacidadDisponible: number
  cursorEventos: string | null
}

/** Resultado conocido de una solicitud de salida; si queda incierto, la pantalla
 * debe consultar de nuevo antes de afirmar qué ocurrió.
 */
export type EstadoSalidaManual =
  | 'PENDIENTE'
  | 'EMITIDA'
  | 'CONFIRMADA'
  | 'NO_EJECUTADA'
  | 'INCIERTA'
  | 'ANULADA'

export interface SalidaManual {
  operacionId: string
  estado: EstadoSalidaManual
}

/** Registro de un vehículo que aún figura dentro, con el resultado de salida
 * si ya se solicitó una.
 */
export interface EntradaActiva {
  movimientoId: string
  persona: PersonaAcceso & { codigo: string }
  estadoTarjeta: 'ACTIVA' | 'CANCELADA'
  entradaEn: string
  entradaEnLocal: string
  salidaManual: SalidaManual | null
}

/** Una página de vehículos que siguen dentro y la marca desde la que buscar
 * los cambios más recientes.
 */
export interface PaginaEntradasActivas {
  items: EntradaActiva[]
  pagina: number
  tamano: number
  totalRegistros: number
  haySiguiente: boolean
  zonaHoraria: string
  cursorEventos: string | null
}
