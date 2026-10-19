export const TURNOS_CONFIGURABLES = [
  { codigo: 'MATUTINO', etiqueta: 'Matutino' },
  { codigo: 'VESPERTINO', etiqueta: 'Vespertino' },
  { codigo: 'NOCTURNO', etiqueta: 'Nocturno' },
] as const

export const TURNO_SIN_RESTRICCION = {
  codigo: 'SIN_RESTRICCION',
  etiqueta: 'Sin restricción',
} as const

export type CodigoTurnoConfigurable = typeof TURNOS_CONFIGURABLES[number]['codigo']

export interface IntervaloHorarioEmpleado {
  hora_inicio: string | null
  hora_fin: string | null
}

export interface TurnoEmpleadoRespuesta {
  id: number
  codigo: CodigoTurnoConfigurable | 'SIN_RESTRICCION'
  nombre: string
  hora_inicio: string | null
  hora_fin: string | null
}

export interface RespuestaHorariosEmpleados {
  revision: number
  zona_horaria: string
  turnos: TurnoEmpleadoRespuesta[]
}

export type HorariosConfigurables = Record<CodigoTurnoConfigurable, IntervaloHorarioEmpleado>
export type ErroresHorarios = Partial<Record<CodigoTurnoConfigurable, string>>

const PATRON_HORA = /^(?:[01]\d|2[0-3]):[0-5]\d$/

export function modalidadAdmiteHorarios(modalidad: string | null): boolean {
  return modalidad === 'PRIVADO' || modalidad === 'MIXTO'
}

export function crearHorariosConfigurables(
  respuesta: RespuestaHorariosEmpleados,
): HorariosConfigurables {
  const turnos = new Map(respuesta.turnos.map((turno) => [turno.codigo, turno]))
  return Object.fromEntries(TURNOS_CONFIGURABLES.map(({ codigo }) => {
    const turno = turnos.get(codigo)
    return [codigo, {
      hora_inicio: turno?.hora_inicio ?? null,
      hora_fin: turno?.hora_fin ?? null,
    }]
  })) as HorariosConfigurables
}

export function validarHorariosConfigurables(
  horarios: HorariosConfigurables,
): ErroresHorarios {
  const errores: ErroresHorarios = {}

  for (const { codigo } of TURNOS_CONFIGURABLES) {
    const intervalo = horarios[codigo]
    const { hora_inicio: inicio, hora_fin: fin } = intervalo
    if ((inicio === null) !== (fin === null)) {
      errores[codigo] = 'Indica ambas horas o deja el turno sin configurar.'
    } else if (
      (inicio !== null && !PATRON_HORA.test(inicio))
      || (fin !== null && !PATRON_HORA.test(fin))
    ) {
      errores[codigo] = 'Usa horas válidas en formato de 24 horas.'
    } else if (inicio !== null && inicio === fin) {
      errores[codigo] = 'La hora de inicio y fin deben ser distintas.'
    }
  }

  return errores
}
