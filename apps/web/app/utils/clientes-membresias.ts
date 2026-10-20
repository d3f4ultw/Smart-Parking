export type EstadoMembresia =
  | 'activa'
  | 'cancelacion_programada'
  | 'pago_vencido'
  | 'cancelada'
  | 'inactiva'
  | 'pendiente'

export interface ClienteResumen {
  codigo_cliente: string
  nombre_completo: string
  estado_membresia: EstadoMembresia
}

export interface RespuestaListaClientes {
  clientes: ClienteResumen[]
  pagina: number
  tamano_pagina: number
  total: number
  total_paginas: number
}

export interface DetalleMembresiaCliente {
  codigo_cliente: string
  plan: string
  monto_centavos: number
  moneda: string
  fecha_inicio: string | null
  proxima_renovacion: string | null
  estado: EstadoMembresia
  cancelacion_programada: boolean
}

export interface PlanMembresia {
  plan_id: string
  nombre: string
  monto_centavos: number
  moneda: string
  intervalo: 'month'
  intervalo_cantidad: number
}

export interface RespuestaPlanesMembresia {
  planes: PlanMembresia[]
}

export interface RespuestaCheckout {
  checkout_url: string
}

export interface EstadoCheckout {
  estado: 'pendiente' | 'confirmado' | 'no_completado'
}

export function puedeLeerClientesMembresias(
  rol: string | null | undefined,
): boolean {
  return rol === 'OWNER'
}

export function obtenerPaginaSolicitadaClientes(valor: unknown): number {
  if (typeof valor !== 'string' || !/^[1-9]\d*$/.test(valor)) {
    return 1
  }
  const pagina = Number(valor)
  return Number.isSafeInteger(pagina) ? pagina : 1
}

export function etiquetaEstadoMembresia(estado: EstadoMembresia): string {
  const etiquetas: Record<EstadoMembresia, string> = {
    activa: 'Activa',
    cancelacion_programada: 'Cancelación programada',
    pago_vencido: 'Pago vencido',
    cancelada: 'Cancelada',
    inactiva: 'Inactiva',
    pendiente: 'Pendiente',
  }
  return etiquetas[estado]
}

export function formatearPrecioMembresia(
  montoCentavos: number,
  moneda: string,
): string {
  return new Intl.NumberFormat('es-MX', {
    style: 'currency',
    currency: moneda.toUpperCase(),
    maximumFractionDigits: 2,
  }).format(montoCentavos / 100)
}

export function formatearFechaMembresia(fecha: string | null): string {
  if (fecha === null) {
    return 'Sin fecha programada'
  }
  const instante = new Date(fecha)
  if (Number.isNaN(instante.getTime())) {
    return 'Sin fecha programada'
  }
  return new Intl.DateTimeFormat('es-MX', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'America/Mexico_City',
  }).format(instante)
}

export function mapearErrorClientes(
  estado: number | undefined,
  accion: 'leer' | 'detalle' | 'compra',
): string {
  if (estado === 401) {
    return 'Tu sesión terminó. Inicia sesión nuevamente.'
  }
  if (estado === 403) {
    return 'No tienes permiso para consultar clientes y membresías.'
  }
  if (estado === 404 && accion === 'detalle') {
    return 'El detalle solicitado ya no está disponible.'
  }
  if (estado === 409 && accion === 'compra') {
    return 'La compra de membresías no está disponible para esta modalidad.'
  }
  if (estado === 503 && accion === 'compra') {
    return 'El servicio de pago no está disponible. Inténtalo más tarde.'
  }
  return accion === 'leer'
    ? 'No fue posible cargar los clientes. Intenta nuevamente.'
    : accion === 'detalle'
      ? 'No fue posible cargar el detalle. Intenta nuevamente.'
      : 'No fue posible iniciar el pago. Intenta nuevamente.'
}

export function obtenerEstadoErrorClientes(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null) {
    return undefined
  }
  const valor = error as { status?: unknown; statusCode?: unknown }
  if (typeof valor.statusCode === 'number') {
    return valor.statusCode
  }
  return typeof valor.status === 'number' ? valor.status : undefined
}
