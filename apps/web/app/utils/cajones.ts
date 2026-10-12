import type { InstantaneaEventoCajon } from './eventos-tiempo-real'

export type EstadoFisicoCajon = 'DESCONOCIDO' | 'LIBRE' | 'OCUPADO'

export type EstadoOperativoCajon =
  | 'DISPONIBLE'
  | 'MANTENIMIENTO'
  | 'FUERA_DE_SERVICIO'

export type EstadoEfectivoCajon =
  | 'DESCONOCIDO'
  | 'LIBRE'
  | 'OCUPADO'
  | 'NO_DISPONIBLE'

export type CursorEventos = string

export interface Cajon {
  id: number
  numero: number
  estado_fisico: EstadoFisicoCajon
  estado_operativo: EstadoOperativoCajon
  motivo_operativo: string | null
  estado_fisico_actualizado_en: string | null
  estado_operativo_actualizado_en: string
  creado_en: string
  estado_efectivo: EstadoEfectivoCajon
}

export interface SolicitudEstadoOperativoCajon {
  estado: EstadoOperativoCajon
  motivo?: string
}

export interface RespuestaMutacionCajon extends Cajon {
  cambio_aplicado: boolean
}

export type ResultadoSolicitudEstadoOperativo =
  | { tipo: 'valida'; solicitud: SolicitudEstadoOperativoCajon }
  | { tipo: 'invalida'; mensaje: string }

export interface RespuestaListaCajones {
  cajones: Cajon[]
  cursor_eventos: CursorEventos
}

export type ResultadoAplicacionInstantaneaCajon =
  | { tipo: 'aplicada'; respuesta: RespuestaListaCajones }
  | { tipo: 'cajon-desconocido'; respuesta: RespuestaListaCajones }

export interface ConteoEstadosCajones {
  total: number
  libres: number
  ocupados: number
  noDisponibles: number
  desconocidos: number
}

export const ETIQUETAS_ESTADO_EFECTIVO: Record<EstadoEfectivoCajon, string> = {
  LIBRE: 'Libre',
  OCUPADO: 'Ocupado',
  NO_DISPONIBLE: 'No disponible',
  DESCONOCIDO: 'Desconocido',
}

export const ETIQUETAS_ESTADO_FISICO: Record<EstadoFisicoCajon, string> = {
  DESCONOCIDO: 'Desconocido',
  LIBRE: 'Libre',
  OCUPADO: 'Ocupado',
}

export const ETIQUETAS_ESTADO_OPERATIVO: Record<EstadoOperativoCajon, string> = {
  DISPONIBLE: 'Disponible',
  MANTENIMIENTO: 'Mantenimiento',
  FUERA_DE_SERVICIO: 'Fuera de servicio',
}

export function contarCajones(
  cajones: readonly Pick<Cajon, 'estado_efectivo'>[],
): ConteoEstadosCajones {
  const conteo: ConteoEstadosCajones = {
    total: cajones.length,
    libres: 0,
    ocupados: 0,
    noDisponibles: 0,
    desconocidos: 0,
  }

  for (const cajon of cajones) {
    switch (cajon.estado_efectivo) {
      case 'LIBRE':
        conteo.libres += 1
        break
      case 'OCUPADO':
        conteo.ocupados += 1
        break
      case 'NO_DISPONIBLE':
        conteo.noDisponibles += 1
        break
      case 'DESCONOCIDO':
        conteo.desconocidos += 1
        break
    }
  }

  return conteo
}

export function ordenarCajones(cajones: readonly Cajon[]): Cajon[] {
  return [...cajones].sort((cajonA, cajonB) => {
    return cajonA.numero - cajonB.numero || cajonA.id - cajonB.id
  })
}

export function crearSolicitudEstadoOperativo(
  estado: EstadoOperativoCajon,
  motivo: string,
): ResultadoSolicitudEstadoOperativo {
  if (estado === 'DISPONIBLE') {
    return { tipo: 'valida', solicitud: { estado } }
  }

  const motivoNormalizado = motivo.trim()
  if (motivoNormalizado.length > 250) {
    return { tipo: 'invalida', mensaje: 'El motivo no puede superar 250 caracteres.' }
  }

  return {
    tipo: 'valida',
    solicitud: motivoNormalizado.length === 0
      ? { estado }
      : { estado, motivo: motivoNormalizado },
  }
}

export function estadoOperativoSinCambios(
  cajon: Pick<Cajon, 'estado_operativo' | 'motivo_operativo'>,
  solicitud: SolicitudEstadoOperativoCajon,
): boolean {
  const motivoActual = cajon.motivo_operativo?.trim() || null
  return cajon.estado_operativo === solicitud.estado
    && motivoActual === (solicitud.motivo ?? null)
}

export function esRespuestaMutacionCajon(
  valor: unknown,
  cajonId: number,
): valor is RespuestaMutacionCajon {
  if (typeof valor !== 'object' || valor === null || Array.isArray(valor)) {
    return false
  }

  const respuesta = valor as Record<string, unknown>
  return respuesta.id === cajonId
    && typeof respuesta.numero === 'number'
    && ['DESCONOCIDO', 'LIBRE', 'OCUPADO'].includes(String(respuesta.estado_fisico))
    && ['DISPONIBLE', 'MANTENIMIENTO', 'FUERA_DE_SERVICIO'].includes(String(respuesta.estado_operativo))
    && (respuesta.motivo_operativo === null || typeof respuesta.motivo_operativo === 'string')
    && (respuesta.estado_fisico_actualizado_en === null || typeof respuesta.estado_fisico_actualizado_en === 'string')
    && typeof respuesta.estado_operativo_actualizado_en === 'string'
    && typeof respuesta.creado_en === 'string'
    && ['DESCONOCIDO', 'LIBRE', 'OCUPADO', 'NO_DISPONIBLE'].includes(String(respuesta.estado_efectivo))
    && typeof respuesta.cambio_aplicado === 'boolean'
}

export function aplicarInstantaneaCajon(
  respuesta: RespuestaListaCajones,
  instantanea: InstantaneaEventoCajon,
): ResultadoAplicacionInstantaneaCajon {
  const existeCajon = respuesta.cajones.some(
    (cajon) => cajon.id === instantanea.cajon_id,
  )
  if (!existeCajon) {
    return { tipo: 'cajon-desconocido', respuesta }
  }

  return {
    tipo: 'aplicada',
    respuesta: {
      ...respuesta,
      cajones: respuesta.cajones.map((cajon) => cajon.id === instantanea.cajon_id
        ? {
            ...cajon,
            numero: instantanea.numero,
            estado_fisico: instantanea.estado_fisico,
            estado_operativo: instantanea.estado_operativo,
            motivo_operativo: instantanea.motivo_operativo,
            estado_efectivo: instantanea.estado_efectivo,
            estado_fisico_actualizado_en: instantanea.estado_fisico_actualizado_en,
            estado_operativo_actualizado_en: instantanea.estado_operativo_actualizado_en,
          }
        : cajon),
    },
  }
}
