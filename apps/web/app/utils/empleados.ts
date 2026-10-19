export type AccionEmpleado = 'leer' | 'registrar' | 'cambiar_estado'

export interface TurnoEmpleadoDisponible {
  id: string
  codigo: 'MATUTINO' | 'VESPERTINO' | 'NOCTURNO' | 'SIN_RESTRICCION'
  nombre: 'Matutino' | 'Vespertino' | 'Nocturno' | 'Sin restricción'
}

export interface Empleado {
  id: string
  codigo_empleado: string
  nombres: string
  apellido_paterno: string
  apellido_materno: string | null
  turno: TurnoEmpleadoDisponible
  esta_activo: boolean
  revision_estado: number
  creado_en: string
  actualizado_en: string
}

export interface RespuestaListaEmpleados {
  empleados: Empleado[]
  pagina: number
  tamano_pagina: number
  total: number
  total_paginas: number
  turnos_disponibles: TurnoEmpleadoDisponible[]
}

export interface DatosFormularioEmpleado {
  nombres: string
  apellido_paterno: string
  apellido_materno: string
  turno_empleado_id: string
}

export interface SolicitudRegistrarEmpleado {
  nombres: string
  apellido_paterno: string
  apellido_materno: string | null
  turno_empleado_id: number
}

export interface SolicitudCambiarEstadoEmpleado {
  esta_activo: boolean
  revision_esperada: number
}

export interface CapacidadesEmpleados {
  leer: boolean
  registrar: boolean
  cambiar_estado: boolean
}

export type CampoFormularioEmpleado = keyof DatosFormularioEmpleado
export type ErroresFormularioEmpleado = Partial<
  Record<CampoFormularioEmpleado, string>
>

/** Controla las acciones visibles; FastAPI vuelve a validar cada operación. */
export function puedeRealizarAccionEmpleado(
  rol: string | null | undefined,
  accion: AccionEmpleado,
  permisosAdicionales: readonly AccionEmpleado[] = [],
): boolean {
  if (rol === 'OWNER') {
    return true
  }

  return rol === 'OPERADOR' && permisosAdicionales.includes(accion)
}

/** Calcula las capacidades de navegación y controles por acción. */
export function construirCapacidadesEmpleados(
  rol: string | null | undefined,
  permisosAdicionales: readonly AccionEmpleado[] = [],
): CapacidadesEmpleados {
  return {
    leer: puedeRealizarAccionEmpleado(rol, 'leer', permisosAdicionales),
    registrar: puedeRealizarAccionEmpleado(rol, 'registrar', permisosAdicionales),
    cambiar_estado: puedeRealizarAccionEmpleado(
      rol,
      'cambiar_estado',
      permisosAdicionales,
    ),
  }
}

export function validarDatosEmpleado(
  datos: DatosFormularioEmpleado,
): ErroresFormularioEmpleado {
  const errores: ErroresFormularioEmpleado = {}
  const camposRequeridos: Array<keyof Pick<
    DatosFormularioEmpleado,
    'nombres' | 'apellido_paterno'
  >> = ['nombres', 'apellido_paterno']

  for (const campo of camposRequeridos) {
    const nombre = datos[campo].trim()
    if (nombre.length === 0) {
      errores[campo] = campo === 'nombres'
        ? 'Los nombres son obligatorios.'
        : 'El apellido paterno es obligatorio.'
    } else if (nombre.length > 100) {
      errores[campo] = campo === 'nombres'
        ? 'Los nombres no pueden superar 100 caracteres.'
        : 'El apellido paterno no puede superar 100 caracteres.'
    }
  }

  const apellidoMaterno = datos.apellido_materno.trim()
  if (apellidoMaterno.length > 100) {
    errores.apellido_materno = 'El apellido materno no puede superar 100 caracteres.'
  }

  const turnoId = Number(datos.turno_empleado_id)
  if (
    datos.turno_empleado_id.trim().length === 0
    || !Number.isSafeInteger(turnoId)
    || turnoId < 1
  ) {
    errores.turno_empleado_id = 'Selecciona un turno disponible.'
  }

  return errores
}

export function construirSolicitudRegistrarEmpleado(
  datos: DatosFormularioEmpleado,
): SolicitudRegistrarEmpleado {
  const apellidoMaterno = datos.apellido_materno.trim()
  return {
    nombres: datos.nombres.trim(),
    apellido_paterno: datos.apellido_paterno.trim(),
    apellido_materno: apellidoMaterno || null,
    turno_empleado_id: Number(datos.turno_empleado_id),
  }
}

export function construirNombreCompletoEmpleado(empleado: Empleado): string {
  return [
    empleado.nombres,
    empleado.apellido_paterno,
    empleado.apellido_materno,
  ]
    .filter((parte): parte is string => parte !== null && parte.length > 0)
    .join(' ')
}

export function obtenerPaginaSolicitadaEmpleados(valor: unknown): number {
  if (typeof valor !== 'string' || !/^[1-9]\d*$/.test(valor)) {
    return 1
  }

  const pagina = Number(valor)
  return Number.isSafeInteger(pagina) ? pagina : 1
}

export function obtenerEstadoErrorEmpleado(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null) {
    return undefined
  }

  const posibleError = error as {
    status?: unknown
    statusCode?: unknown
    response?: { status?: unknown }
  }
  if (typeof posibleError.status === 'number') {
    return posibleError.status
  }
  if (typeof posibleError.statusCode === 'number') {
    return posibleError.statusCode
  }
  if (typeof posibleError.response?.status === 'number') {
    return posibleError.response.status
  }
  return undefined
}

export function mapearErrorEmpleados(
  estado: number | undefined,
  accion: 'leer' | 'registrar' | 'cambiar_estado',
): string {
  if (estado === 401) {
    return 'Tu sesión terminó. Inicia sesión nuevamente.'
  }
  if (estado === 403) {
    return 'No tienes permiso para gestionar empleados.'
  }
  if (estado === 409 && accion === 'leer') {
    return 'El módulo de empleados solo está disponible en modalidades Empresarial y Mixta.'
  }
  if (estado === 409 && accion === 'cambiar_estado') {
    return 'El estado cambió en otra sesión. Se actualizará la lista.'
  }
  if (estado === 409) {
    return 'La solicitud de registro cambió o la modalidad ya no permite empleados.'
  }
  if (estado === 422 && accion === 'registrar') {
    return 'Revisa los datos del empleado y el turno seleccionado.'
  }
  if (estado === 404 && accion === 'cambiar_estado') {
    return 'El empleado ya no está disponible.'
  }
  return accion === 'leer'
    ? 'No fue posible cargar los empleados. Intenta nuevamente.'
    : accion === 'registrar'
      ? 'No fue posible registrar al empleado. Intenta nuevamente.'
      : 'No fue posible actualizar el estado. Intenta nuevamente.'
}
