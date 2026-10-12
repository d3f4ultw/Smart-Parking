import {
  createError,
  getCookie,
  getRequestHeader,
  getRouterParam,
  readBody,
  sendProxy,
  setResponseHeader,
  type H3Event,
} from 'h3'

const NOMBRE_COOKIE_SESION = 'smart_parking_session'

export function proxyAdminCajones(event: H3Event) {
  const config = useRuntimeConfig(event)
  const apiBaseUrl = config.apiInternalBaseUrl.replace(/\/+$/, '')
  const cookieSesion = getCookie(event, NOMBRE_COOKIE_SESION)

  setResponseHeader(event, 'cache-control', 'no-store')

  return sendProxy(event, apiBaseUrl + '/api/cajones', {
    fetchOptions: {
      method: 'GET',
      headers: cookieSesion === undefined
        ? undefined
        : { cookie: NOMBRE_COOKIE_SESION + '=' + cookieSesion },
    },
  })
}

type SolicitudOperativaValidada = {
  estado: 'DISPONIBLE' | 'MANTENIMIENTO' | 'FUERA_DE_SERVICIO'
  motivo?: string
}

function validarIdCajon(valor: string | undefined): valor is string {
  if (valor === undefined || !/^[1-9]\d*$/.test(valor)) {
    return false
  }

  return Number.isSafeInteger(Number(valor))
}

function validarSolicitudOperativa(valor: unknown): SolicitudOperativaValidada | null {
  if (typeof valor !== 'object' || valor === null || Array.isArray(valor)) {
    return null
  }

  const entrada = valor as Record<string, unknown>
  if (Object.keys(entrada).some((clave) => !['estado', 'motivo'].includes(clave))) {
    return null
  }

  if (!['DISPONIBLE', 'MANTENIMIENTO', 'FUERA_DE_SERVICIO'].includes(String(entrada.estado))) {
    return null
  }

  let motivo: string | null = null
  if (entrada.motivo !== undefined && entrada.motivo !== null) {
    if (typeof entrada.motivo !== 'string') {
      return null
    }

    motivo = entrada.motivo.trim() || null
    if (motivo !== null && motivo.length > 250) {
      return null
    }
  }

  if (entrada.estado === 'DISPONIBLE') {
    return motivo === null ? { estado: 'DISPONIBLE' } : null
  }

  return motivo === null
    ? { estado: entrada.estado as SolicitudOperativaValidada['estado'] }
    : { estado: entrada.estado as SolicitudOperativaValidada['estado'], motivo }
}

export async function proxyCambiarEstadoOperativoCajon(event: H3Event) {
  const config = useRuntimeConfig(event)
  const apiBaseUrl = config.apiInternalBaseUrl.replace(/\/+$/, '')
  const cookieSesion = getCookie(event, NOMBRE_COOKIE_SESION)

  setResponseHeader(event, 'cache-control', 'no-store')

  const cajonId = getRouterParam(event, 'cajonId')
  if (!validarIdCajon(cajonId)) {
    throw createError({ statusCode: 400, statusMessage: 'Invalid parking slot ID' })
  }

  const contentType = getRequestHeader(event, 'content-type')
  if (contentType === undefined || !/^application\/json(?:\s*;|\s*$)/i.test(contentType)) {
    throw createError({ statusCode: 415, statusMessage: 'JSON request body required' })
  }

  const solicitud = validarSolicitudOperativa(await readBody<unknown>(event))
  if (solicitud === null) {
    throw createError({ statusCode: 422, statusMessage: 'Invalid operational-state request' })
  }

  const headers: Record<string, string> = {
    'content-type': 'application/json',
  }
  if (cookieSesion !== undefined) {
    headers.cookie = NOMBRE_COOKIE_SESION + '=' + cookieSesion
  }

  return sendProxy(
    event,
    `${apiBaseUrl}/api/cajones/${cajonId}/estado-operativo`,
    {
      fetchOptions: {
        method: 'PATCH',
        headers,
        body: JSON.stringify(solicitud),
      },
    },
  )
}
