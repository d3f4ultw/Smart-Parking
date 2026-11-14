export type EstadoEmpleado = 'ACTIVO' | 'INACTIVO'

export type EstadoCuentaOperador = 'PENDIENTE' | 'ACTIVA' | 'INACTIVA'

export interface ResumenOperadorEmpleado {
  id: string
  estado: EstadoCuentaOperador
}

/** Datos de un empleado y el número de revisión, que permite saber si alguien
 * cambió la información después de abrir el detalle.
 */
export interface Empleado {
  id: number
  idTexto: string
  codigo: string
  nombres: string
  primerApellido: string
  segundoApellido: string | null
  estado: EstadoEmpleado
  revision: number
  revisionTexto: string
  correo: string | null
  operador: ResumenOperadorEmpleado | null
}

/** Una página de empleados y la marca desde la que buscar los cambios más recientes. */
export interface PaginaEmpleados {
  items: Empleado[]
  pagina: number
  tamanoPagina: number
  totalRegistros: number
  totalPaginas: number
  cursorEventos: string
}

export interface RegistroEmpleado {
  nombres: string
  primerApellido: string
  segundoApellido: string | null
  correo?: string | null
}

export interface ReciboRegistroEmpleado {
  id: number
  codigo: string
}

export interface RespuestaAccionEmpleadoOperador {
  empleadoId: string
  operadorId: string | null
  estadoOperador: EstadoCuentaOperador | null
  revisionEmpleado: string
  estadoInvitacion: string | null
}

export interface RespuestaCambioCorreoEmpleadoOperador {
  empleadoId: string
  correo: string | null
  estadoOperador: EstadoCuentaOperador | null
  revisionEmpleado: string
  estadoInvitacion: string | null
}
