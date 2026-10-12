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

const COOKIE_GESTION = 'smart_parking_owner_management'
const API_GESTION = '/api/gestion-propietario/v1'

type AccionGestion =
  | 'claim'
  | 'sesion'
  | 'latido'
  | 'estado'
  | 'inscripciones'
  | 'reenviar'
  | 'desvinculacion'
  | 'confirmarDesvinculacion'

function prepararCabeceras(event: H3Event) {
  const config = useRuntimeConfig(event)
  setResponseHeader(event, 'cache-control', 'no-store')
  setResponseHeader(event, 'pragma', 'no-cache')
  setResponseHeader(event, 'referrer-policy', 'no-referrer')
  setResponseHeader(event, 'x-content-type-options', 'nosniff')
  setResponseHeader(event, 'x-robots-tag', 'noindex, nofollow, noarchive')
  return config
}

function validarOrigen(event: H3Event, origenEsperado: string) {
  const origen = getRequestHeader(event, 'origin')
  let origenConfigurado: string
  try {
    origenConfigurado = new URL(origenEsperado).origin
  } catch {
    throw createError({ statusCode: 500, statusMessage: 'Management origin unavailable' })
  }
  if (origen !== origenConfigurado) {
    throw createError({ statusCode: 403, statusMessage: 'Origin not allowed' })
  }
  return origen
}

function rutaUpstream(accion: AccionGestion, event: H3Event) {
  if (accion === 'reenviar') {
    const id = getRouterParam(event, 'id')
    if (id === undefined || !/^[1-9]\d{0,8}$/.test(id)) {
      throw createError({ statusCode: 400, statusMessage: 'Invalid enrollment ID' })
    }
    return `${API_GESTION}/inscripciones/${id}/reenviar`
  }

  const rutas: Record<Exclude<AccionGestion, 'reenviar'>, string> = {
    claim: '/claim',
    sesion: '/sesion',
    latido: '/latido',
    estado: '/estado',
    inscripciones: '/inscripciones',
      desvinculacion: '/desvinculacion',
      confirmarDesvinculacion: '/desvinculacion/confirmar',
  }
  return API_GESTION + rutas[accion]
}

export async function proxyGestionPropietario(
  event: H3Event,
  accion: AccionGestion,
) {
  const config = prepararCabeceras(event)
  const metodo = accion === 'sesion' || accion === 'estado' ? 'GET' : 'POST'
  const escrituraSegura = metodo === 'POST'
  const origen = escrituraSegura
    ? validarOrigen(event, config.public.managementOrigin)
    : undefined
  const cookie = accion === 'confirmarDesvinculacion'
    ? undefined
    : getCookie(event, COOKIE_GESTION)
  const headers: Record<string, string> = {}
  if (cookie !== undefined) {
    headers.cookie = `${COOKIE_GESTION}=${cookie}`
  }
  if (origen !== undefined) {
    headers.origin = origen
  }

  const fetchOptions: {
    method: string
    headers: Record<string, string>
    body?: string
  } = { method: metodo, headers }
  if (
    accion === 'claim'
    || accion === 'inscripciones'
    || accion === 'desvinculacion'
    || accion === 'confirmarDesvinculacion'
  ) {
    const contentType = getRequestHeader(event, 'content-type')
    if (contentType === undefined || !/^application\/json(?:\s*;|\s*$)/i.test(contentType)) {
      throw createError({ statusCode: 415, statusMessage: 'JSON request body required' })
    }
    headers['content-type'] = 'application/json'
    fetchOptions.body = JSON.stringify(await readBody<unknown>(event))
  }

  const apiBaseUrl = config.apiInternalBaseUrl.replace(/\/+$/, '')
  return sendProxy(event, apiBaseUrl + rutaUpstream(accion, event), { fetchOptions })
}
