import type { EstadoMembresiaCliente } from '~/types/cliente'

export type EstadoFiltroClientes = 'todos' | 'sin-membresia' | 'activa' | 'cancelada'

export interface ClienteResumenAdministracion {
  codigo: string
  nombreCompleto: string
  estadoMembresia: EstadoMembresiaCliente
}

/** Una página de clientes y la marca desde la que buscar cambios que ocurran después. */
export interface PaginaClientesAdministracion {
  items: ClienteResumenAdministracion[]
  pagina: number
  tamanoPagina: number
  totalClientes: number
  totalRegistros: number
  totalPaginas: number
  cursorEventos: string | null
}

export interface MembresiaDetalleAdministracion {
  plan: {
    nombre: string
    importeMenorUnidad: number
    moneda: string
    intervalo: string
    intervaloCantidad: number
  }
  periodoInicio: string | null
  periodoFin: string | null
  siguienteCobroEn: string | null
  cancelacionAlFinal: boolean
}

/** Fechas, plan y cobros que el dueño o un operador autorizado puede consultar
 * al abrir el detalle de un cliente.
 */
export interface DetalleClienteAdministracion extends ClienteResumenAdministracion {
  membresia: MembresiaDetalleAdministracion | null
}
