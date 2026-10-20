import {
  appendResponseHeader,
  createError,
  getRequestHeader,
  getRequestURL,
  readBody,
  setResponseHeader,
  setResponseStatus,
  type H3Event,
} from 'h3'

const NOMBRE_COOKIE_CLIENTE = 'smart_parking_customer_session'
const TAMANO_MAXIMO_CUERPO = 8 * 1024
const VALOR_COOKIE_SESION = /^[A-Za-z0-9._~-]{1,512}$/

type MetodoApiCliente = 'GET' | 'POST'

interface OpcionesPeticionApiCliente {
  ruta: string
  metodo: MetodoApiCliente
  incluirSesion?: boolean
  exigirOrigen?: boolean
  cuerpo?: unknown
  idempotencyKey?: string
}

function errorSolicitud(statusCode: number, statusMessage: string): never {
  throw createError({ statusCode, statusMessage })
}

function mensajeErrorUpstream(statusCode: number): string {
  if (statusCode === 401) return 'Se requiere iniciar sesión.'
  if (statusCode === 403) return 'La solicitud no está autorizada.'
  if (statusCode === 404) return 'El recurso solicitado no está disponible.'
  if (statusCode === 409) return 'La solicitud no se puede completar en este momento.'
  if (statusCode === 415) return 'Se requiere una solicitud JSON.'
  if (statusCode === 422) return 'Revisa los datos enviados.'
  if (statusCode === 429) return 'Se alcanzó el límite de solicitudes. Inténtalo más tarde.'
  if (statusCode >= 500) return 'El servicio de cuenta no está disponible temporalmente.'
  return 'No fue posible completar la solicitud.'
}

function exigirOrigenMismoSitio(event: H3Event): string {
  const origen = getRequestHeader(event, 'origin')
  const origenEsperado = useRuntimeConfig(event).public.managementOrigin
  try {
    if (
      origen === undefined
      || new URL(origen).origin !== new URL(origenEsperado).origin
    ) {
      errorSolicitud(403, 'La solicitud no está autorizada.')
    }
  } catch {
    errorSolicitud(403, 'La solicitud no está autorizada.')
  }
  return origen
}

function obtenerCookieCliente(event: H3Event): string | undefined {
  const cookieHeader = getRequestHeader(event, 'cookie')
  if (cookieHeader === undefined) {
    return undefined
  }

  const pares = cookieHeader.split(';').map((parte) => parte.trim())
  const cookiesCliente = pares.filter((parte) =>
    parte.startsWith(`${NOMBRE_COOKIE_CLIENTE}=`),
  )
  if (cookiesCliente.length > 1) {
    errorSolicitud(400, 'La sesión de cliente no es válida.')
  }
  const par = cookiesCliente[0]
  if (par === undefined) {
    return undefined
  }

  const valor = par.slice(NOMBRE_COOKIE_CLIENTE.length + 1)
  if (!VALOR_COOKIE_SESION.test(valor)) {
    errorSolicitud(400, 'La sesión de cliente no es válida.')
  }
  return `${NOMBRE_COOKIE_CLIENTE}=${valor}`
}

export function exigirSinParametros(event: H3Event, mensaje = 'La solicitud no es válida'): void {
  setResponseHeader(event, 'cache-control', 'no-store')
  if (getRequestURL(event).search) {
    errorSolicitud(422, mensaje)
  }
}

export async function leerObjetoJsonCliente(
  event: H3Event,
  camposRequeridos: readonly string[],
  camposPermitidos: readonly string[] = camposRequeridos,
): Promise<Record<string, string>> {
  setResponseHeader(event, 'cache-control', 'no-store')
  const contentType = getRequestHeader(event, 'content-type')
  if (contentType === undefined || !/^application\/json(?:\s*;|\s*$)/i.test(contentType)) {
    errorSolicitud(415, 'Se requiere una solicitud JSON.')
  }

  const longitudDeclarada = getRequestHeader(event, 'content-length')
  if (longitudDeclarada !== undefined) {
    if (!/^\d+$/.test(longitudDeclarada)) {
      errorSolicitud(400, 'La solicitud no es válida.')
    }
    if (Number(longitudDeclarada) > TAMANO_MAXIMO_CUERPO) {
      errorSolicitud(413, 'La solicitud supera el tamaño permitido.')
    }
  }

  let valor: unknown
  try {
    valor = await readBody(event)
  } catch {
    errorSolicitud(422, 'Revisa los datos enviados.')
  }
  if (valor === null || typeof valor !== 'object' || Array.isArray(valor)) {
    errorSolicitud(422, 'Revisa los datos enviados.')
  }

  const cuerpo = valor as Record<string, unknown>
  const claves = Object.keys(cuerpo)
  if (
    claves.some((clave) => !camposPermitidos.includes(clave))
    || camposRequeridos.some((clave) => !Object.hasOwn(cuerpo, clave))
    || claves.some((clave) => typeof cuerpo[clave] !== 'string')
    || Buffer.byteLength(JSON.stringify(cuerpo), 'utf8') > TAMANO_MAXIMO_CUERPO
  ) {
    errorSolicitud(422, 'Revisa los datos enviados.')
  }

  return cuerpo as Record<string, string>
}

function agregarSetCookie(event: H3Event, respuesta: Response): void {
  const headers = respuesta.headers as Headers & { getSetCookie?: () => string[] }
  const cookies = typeof headers.getSetCookie === 'function'
    ? headers.getSetCookie()
    : respuesta.headers.get('set-cookie')
      ? [respuesta.headers.get('set-cookie')!]
      : []
  for (const cookie of cookies) {
    appendResponseHeader(event, 'set-cookie', cookie)
  }
}

export async function solicitarApiCliente(
  event: H3Event,
  opciones: OpcionesPeticionApiCliente,
): Promise<unknown> {
  setResponseHeader(event, 'cache-control', 'no-store')
  const config = useRuntimeConfig(event)
  const encabezados = new Headers({ accept: 'application/json' })

  if (opciones.exigirOrigen) {
    encabezados.set('origin', exigirOrigenMismoSitio(event))
  }
  if (opciones.cuerpo !== undefined) {
    encabezados.set('content-type', 'application/json')
  }
  if (opciones.idempotencyKey !== undefined) {
    encabezados.set('idempotency-key', opciones.idempotencyKey)
  }
  if (opciones.incluirSesion) {
    const cookieCliente = obtenerCookieCliente(event)
    if (cookieCliente !== undefined) {
      encabezados.set('cookie', cookieCliente)
    }
  }

  let respuesta: Response
  try {
    respuesta = await fetch(
      `${config.apiInternalBaseUrl.replace(/\/+$/, '')}${opciones.ruta}`,
      {
        method: opciones.metodo,
        headers: encabezados,
        ...(opciones.cuerpo === undefined
          ? {}
          : { body: JSON.stringify(opciones.cuerpo) }),
        cache: 'no-store',
        redirect: 'error',
      },
    )
  } catch {
    errorSolicitud(503, 'El servicio de cuenta no está disponible temporalmente.')
  }

  agregarSetCookie(event, respuesta)
  setResponseStatus(event, respuesta.status)
  const texto = await respuesta.text()

  if (!respuesta.ok) {
    const estado = respuesta.status >= 400 && respuesta.status < 600
      ? respuesta.status
      : 502
    errorSolicitud(estado, mensajeErrorUpstream(estado))
  }
  if (texto.length === 0) {
    return null
  }

  try {
    return JSON.parse(texto) as unknown
  } catch {
    errorSolicitud(502, 'El servicio de cuenta devolvió una respuesta no válida.')
  }
}
