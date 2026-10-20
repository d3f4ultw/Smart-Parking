import {
  createError,
  getRequestHeader,
  getRequestURL,
  getRouterParam,
  readBody,
  sendProxy,
  setResponseHeader,
  type H3Event,
} from 'h3'

const RUTA_API_MEMBRESIAS = '/api/membresias'
const CLAVE_IDEMPOTENCIA = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const SESSION_ID_TEST = /^cs_test_[A-Za-z0-9]+$/

function errorSolicitud(statusCode: number, statusMessage: string): never {
  throw createError({ statusCode, statusMessage })
}

function obtenerUrlApi(event: H3Event, ruta: string): string {
  const base = useRuntimeConfig(event).apiInternalBaseUrl.replace(/\/+$/, '')
  return base + ruta
}

function exigirOrigenMismoSitio(event: H3Event): void {
  const origin = getRequestHeader(event, 'origin')
  const esperado = useRuntimeConfig(event).public.managementOrigin
  if (origin === undefined || new URL(origin).origin !== new URL(esperado).origin) {
    errorSolicitud(403, 'La solicitud de compra no es válida')
  }
}

export function consultarPlanesMembresia(event: H3Event) {
  setResponseHeader(event, 'cache-control', 'no-store')
  if (getRequestURL(event).search) {
    errorSolicitud(422, 'La consulta de planes no es válida')
  }
  return sendProxy(event, obtenerUrlApi(event, `${RUTA_API_MEMBRESIAS}/planes`), {
    fetchOptions: { method: 'GET' },
  })
}

export async function iniciarCheckoutMembresia(event: H3Event) {
  setResponseHeader(event, 'cache-control', 'no-store')
  exigirOrigenMismoSitio(event)
  const contentType = getRequestHeader(event, 'content-type')
  if (contentType === undefined || !/^application\/json(?:\s*;|\s*$)/i.test(contentType)) {
    errorSolicitud(415, 'Se requiere una solicitud JSON')
  }
  const idempotencyKey = getRequestHeader(event, 'idempotency-key')
  if (idempotencyKey === undefined || !CLAVE_IDEMPOTENCIA.test(idempotencyKey)) {
    errorSolicitud(422, 'Se requiere una clave de compra válida')
  }
  const body: unknown = await readBody(event)
  if (
    body === null
    || typeof body !== 'object'
    || Array.isArray(body)
    || Object.keys(body).length !== 1
    || !Object.hasOwn(body, 'plan_id')
    || (body as Record<string, unknown>).plan_id !== 'mensual'
  ) {
    errorSolicitud(422, 'El plan solicitado no está disponible')
  }
  return sendProxy(event, obtenerUrlApi(event, `${RUTA_API_MEMBRESIAS}/checkout`), {
    fetchOptions: {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'idempotency-key': idempotencyKey.toLowerCase(),
      },
      body: JSON.stringify({ plan_id: 'mensual' }),
    },
  })
}

export function consultarEstadoCheckout(event: H3Event) {
  setResponseHeader(event, 'cache-control', 'no-store')
  const sessionId = getRouterParam(event, 'sessionId')
  if (sessionId === undefined || !SESSION_ID_TEST.test(sessionId)) {
    errorSolicitud(404, 'El estado de compra no está disponible')
  }
  if (getRequestURL(event).search) {
    errorSolicitud(422, 'La consulta de compra no es válida')
  }
  return sendProxy(
    event,
    obtenerUrlApi(
      event,
      `${RUTA_API_MEMBRESIAS}/checkout/${encodeURIComponent(sessionId)}/estado`,
    ),
    { fetchOptions: { method: 'GET' } },
  )
}
