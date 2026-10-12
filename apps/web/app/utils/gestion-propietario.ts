export type EstadoInscripcionGestion = {
  id: number
  correo: string
  estado: 'pendiente' | 'bloqueado' | 'expirado' | 'completado'
  correo_inicial_enviado: boolean
  expira_en: string
  proceso_expira_en: string
  enlace_vigente: boolean
  segundos_proceso: number
  reenviados_usados: number
  reenviados_restantes: number
  proximo_reenvio_en: string | null
  segundos_cooldown: number
  reenvio_bloqueado: boolean
  motivo_bloqueo: string | null
}

export type EstadoGestionPropietario = {
  owner_activo: boolean
  desvinculacion_segundos_restantes: number
  owner: {
    nombre: string
    correo: string
  } | null
  inscripciones: EstadoInscripcionGestion[]
}

export type PanelGestionProps = {
  estado: EstadoGestionPropietario | null
  cargando: boolean
  enviando: boolean
  reenviandoId: number | null
  consultadoEn: number
}

export type AccionGestionPropietario = 'registrar' | 'desvincular' | 'estado'

export const ACCIONES_GESTION_PROPIETARIO = [
  { id: 'registrar', nombre: 'Registrar dueño', disponible: true },
  { id: 'desvincular', nombre: 'Desvincular dueño', disponible: true },
  { id: 'estado', nombre: 'Historial', disponible: true },
] as const

export function segundosRestantes(
  valorInicial: number,
  consultadoEn: number,
  ahora: number,
) {
  const transcurrido = Math.max(0, Math.floor((ahora - consultadoEn) / 1000))
  return Math.max(0, valorInicial - transcurrido)
}

export function formatearDuracion(segundos: number) {
  const total = Math.max(0, Math.floor(segundos))
  const horas = Math.floor(total / 3600)
  const minutos = Math.floor((total % 3600) / 60)
  const segundosFinales = total % 60
  return [horas, minutos, segundosFinales]
    .map((parte) => String(parte).padStart(2, '0'))
    .join(':')
}

export function formatearFecha(fecha: string | null) {
  if (fecha === null) {
    return 'No disponible'
  }
  const valor = new Date(fecha)
  if (Number.isNaN(valor.valueOf())) {
    return 'No disponible'
  }
  return new Intl.DateTimeFormat('es-MX', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(valor)
}
