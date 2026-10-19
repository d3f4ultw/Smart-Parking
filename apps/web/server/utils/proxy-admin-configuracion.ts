import {
  createError,
  getCookie,
  getRequestHeader,
  readBody,
  sendProxy,
  setResponseHeader,
  type H3Event,
} from 'h3'

const NOMBRE_COOKIE_SESION = 'smart_parking_session'
const RUTA_API_MODALIDAD = '/api/admin/configuracion/modalidad'
const RUTA_API_ACCESO = '/api/admin/configuracion/acceso'
const RUTA_API_HORARIOS_EMPLEADOS = '/api/admin/configuracion/horarios-empleados'
const MODALIDADES_VALIDAS = ['PRIVADO', 'PUBLICO', 'MIXTO']
const CODIGOS_TURNOS_CONFIGURABLES = ['MATUTINO', 'VESPERTINO', 'NOCTURNO'] as const
const PATRON_HORA = /^(?:[01]\d|2[0-3]):[0-5]\d$/

interface SolicitudModalidad {
  modalidad: 'PRIVADO' | 'PUBLICO' | 'MIXTO'
  revision_esperada: number
}

interface SolicitudAcceso {
  acceso_suspendido: boolean
  revision_esperada: number
}

interface IntervaloHorario {
  hora_inicio: string | null
  hora_fin: string | null
}

interface SolicitudHorariosEmpleados {
  revision_esperada: number
  turnos: Record<(typeof CODIGOS_TURNOS_CONFIGURABLES)[number], IntervaloHorario>
}

function validarSolicitudModalidad(valor: unknown): SolicitudModalidad | null {
  if (valor === null || typeof valor !== 'object' || Array.isArray(valor)) {
    return null
  }

  const entrada = valor as Record<string, unknown>
  if (Object.keys(entrada).some((clave) =>
    clave !== 'modalidad' && clave !== 'revision_esperada')) {
    return null
  }
  if (
    typeof entrada.modalidad !== 'string'
    || !MODALIDADES_VALIDAS.includes(entrada.modalidad)
    || typeof entrada.revision_esperada !== 'number'
    || !Number.isSafeInteger(entrada.revision_esperada)
    || entrada.revision_esperada < 0
  ) {
    return null
  }

  return {
    modalidad: entrada.modalidad as SolicitudModalidad['modalidad'],
    revision_esperada: entrada.revision_esperada,
  }
}

function validarSolicitudAcceso(valor: unknown): SolicitudAcceso | null {
  if (valor === null || typeof valor !== 'object' || Array.isArray(valor)) {
    return null
  }

  const entrada = valor as Record<string, unknown>
  if (Object.keys(entrada).some((clave) =>
    clave !== 'acceso_suspendido' && clave !== 'revision_esperada')) {
    return null
  }
  if (
    typeof entrada.acceso_suspendido !== 'boolean'
    || typeof entrada.revision_esperada !== 'number'
    || !Number.isSafeInteger(entrada.revision_esperada)
    || entrada.revision_esperada < 0
  ) {
    return null
  }

  return {
    acceso_suspendido: entrada.acceso_suspendido,
    revision_esperada: entrada.revision_esperada,
  }
}

function validarIntervaloHorario(valor: unknown): valor is IntervaloHorario {
  if (valor === null || typeof valor !== 'object' || Array.isArray(valor)) {
    return false
  }

  const entrada = valor as Record<string, unknown>
  if (
    Object.keys(entrada).length !== 2
    || !Object.hasOwn(entrada, 'hora_inicio')
    || !Object.hasOwn(entrada, 'hora_fin')
  ) {
    return false
  }

  const inicio = entrada.hora_inicio
  const fin = entrada.hora_fin
  if (
    (inicio !== null && (typeof inicio !== 'string' || !PATRON_HORA.test(inicio)))
    || (fin !== null && (typeof fin !== 'string' || !PATRON_HORA.test(fin)))
    || (inicio === null) !== (fin === null)
  ) {
    return false
  }

  return inicio === null || inicio !== fin
}

function validarSolicitudHorariosEmpleados(
  valor: unknown,
): SolicitudHorariosEmpleados | null {
  if (valor === null || typeof valor !== 'object' || Array.isArray(valor)) {
    return null
  }

  const entrada = valor as Record<string, unknown>
  if (
    Object.keys(entrada).length !== 2
    || typeof entrada.revision_esperada !== 'number'
    || !Number.isSafeInteger(entrada.revision_esperada)
    || entrada.revision_esperada < 1
    || entrada.turnos === null
    || typeof entrada.turnos !== 'object'
    || Array.isArray(entrada.turnos)
  ) {
    return null
  }

  const turnos = entrada.turnos as Record<string, unknown>
  if (
    Object.keys(turnos).length !== CODIGOS_TURNOS_CONFIGURABLES.length
    || CODIGOS_TURNOS_CONFIGURABLES.some((codigo) =>
      !Object.hasOwn(turnos, codigo) || !validarIntervaloHorario(turnos[codigo]))
  ) {
    return null
  }

  return {
    revision_esperada: entrada.revision_esperada,
    turnos: turnos as SolicitudHorariosEmpleados['turnos'],
  }
}

function encabezadosSesion(event: H3Event): Record<string, string> | undefined {
  const cookieSesion = getCookie(event, NOMBRE_COOKIE_SESION)
  return cookieSesion === undefined
    ? undefined
    : { cookie: NOMBRE_COOKIE_SESION + '=' + cookieSesion }
}

function obtenerUrlApi(event: H3Event, rutaApi: string): string {
  const apiBaseUrl = useRuntimeConfig(event).apiInternalBaseUrl.replace(/\/+$/, '')
  return apiBaseUrl + rutaApi
}

export function consultarConfiguracionEstacionamiento(event: H3Event) {
  setResponseHeader(event, 'cache-control', 'no-store')
  return sendProxy(event, obtenerUrlApi(event, RUTA_API_MODALIDAD), {
    fetchOptions: {
      method: 'GET',
      headers: encabezadosSesion(event),
    },
  })
}

export async function cambiarConfiguracionEstacionamiento(event: H3Event) {
  setResponseHeader(event, 'cache-control', 'no-store')

  const contentType = getRequestHeader(event, 'content-type')
  if (
    contentType === undefined
    || !/^application\/json(?:\s*;|\s*$)/i.test(contentType)
  ) {
    throw createError({
      statusCode: 415,
      statusMessage: 'Se requiere una solicitud JSON',
    })
  }

  const solicitud = validarSolicitudModalidad(await readBody<unknown>(event))
  if (solicitud === null) {
    throw createError({
      statusCode: 422,
      statusMessage: 'La solicitud de modalidad no es válida',
    })
  }

  return sendProxy(event, obtenerUrlApi(event, RUTA_API_MODALIDAD), {
    fetchOptions: {
      method: 'PUT',
      headers: {
        'content-type': 'application/json',
        ...encabezadosSesion(event),
      },
      body: JSON.stringify(solicitud),
    },
  })
}

export async function cambiarAccesoEstacionamiento(event: H3Event) {
  setResponseHeader(event, 'cache-control', 'no-store')

  const contentType = getRequestHeader(event, 'content-type')
  if (
    contentType === undefined
    || !/^application\/json(?:\s*;|\s*$)/i.test(contentType)
  ) {
    throw createError({
      statusCode: 415,
      statusMessage: 'Se requiere una solicitud JSON',
    })
  }

  const solicitud = validarSolicitudAcceso(await readBody<unknown>(event))
  if (solicitud === null) {
    throw createError({
      statusCode: 422,
      statusMessage: 'La solicitud de acceso no es válida',
    })
  }

  return sendProxy(event, obtenerUrlApi(event, RUTA_API_ACCESO), {
    fetchOptions: {
      method: 'PUT',
      headers: {
        'content-type': 'application/json',
        ...encabezadosSesion(event),
      },
      body: JSON.stringify(solicitud),
    },
  })
}

export function consultarHorariosEmpleados(event: H3Event) {
  setResponseHeader(event, 'cache-control', 'no-store')
  return sendProxy(event, obtenerUrlApi(event, RUTA_API_HORARIOS_EMPLEADOS), {
    fetchOptions: {
      method: 'GET',
      headers: encabezadosSesion(event),
    },
  })
}

export async function cambiarHorariosEmpleados(event: H3Event) {
  setResponseHeader(event, 'cache-control', 'no-store')

  const contentType = getRequestHeader(event, 'content-type')
  if (
    contentType === undefined
    || !/^application\/json(?:\s*;|\s*$)/i.test(contentType)
  ) {
    throw createError({
      statusCode: 415,
      statusMessage: 'Se requiere una solicitud JSON',
    })
  }

  const solicitud = validarSolicitudHorariosEmpleados(await readBody<unknown>(event))
  if (solicitud === null) {
    throw createError({
      statusCode: 422,
      statusMessage: 'La solicitud de horarios no es válida',
    })
  }

  return sendProxy(event, obtenerUrlApi(event, RUTA_API_HORARIOS_EMPLEADOS), {
    fetchOptions: {
      method: 'PUT',
      headers: {
        'content-type': 'application/json',
        ...encabezadosSesion(event),
      },
      body: JSON.stringify(solicitud),
    },
  })
}
