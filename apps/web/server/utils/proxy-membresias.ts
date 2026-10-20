import {
  createError,
  getRequestHeader,
  getRouterParam,
  setResponseHeader,
  type H3Event,
} from 'h3'

import {
  exigirSinParametros,
  leerObjetoJsonCliente,
  solicitarApiCliente,
} from './proxy-clientes'

const RUTA_API_MEMBRESIAS = '/api/membresias'
const CLAVE_IDEMPOTENCIA = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const SESSION_ID_TEST = /^cs_test_[A-Za-z0-9]+$/

function errorSolicitud(statusCode: number, statusMessage: string): never {
  throw createError({ statusCode, statusMessage })
}

export function consultarPlanesMembresia(event: H3Event) {
  exigirSinParametros(event, 'La consulta de planes no es válida')
  return solicitarApiCliente(event, {
    ruta: `${RUTA_API_MEMBRESIAS}/planes`,
    metodo: 'GET',
  })
}

export async function iniciarCheckoutMembresia(event: H3Event) {
  setResponseHeader(event, 'cache-control', 'no-store')
  exigirSinParametros(event)
  const body = await leerObjetoJsonCliente(event, ['plan_id'])
  const idempotencyKey = getRequestHeader(event, 'idempotency-key')
  if (idempotencyKey === undefined || !CLAVE_IDEMPOTENCIA.test(idempotencyKey)) {
    errorSolicitud(422, 'Se requiere una clave de compra válida')
  }
  if (body.plan_id !== 'mensual') {
    errorSolicitud(422, 'El plan solicitado no está disponible')
  }
  return solicitarApiCliente(event, {
    ruta: `${RUTA_API_MEMBRESIAS}/checkout`,
    metodo: 'POST',
    incluirSesion: true,
    exigirOrigen: true,
    idempotencyKey: idempotencyKey.toLowerCase(),
    cuerpo: { plan_id: 'mensual' },
  })
}

export function consultarEstadoCheckout(event: H3Event) {
  setResponseHeader(event, 'cache-control', 'no-store')
  const sessionId = getRouterParam(event, 'sessionId')
  if (sessionId === undefined || !SESSION_ID_TEST.test(sessionId)) {
    errorSolicitud(404, 'El estado de compra no está disponible')
  }
  exigirSinParametros(event, 'La consulta de compra no es válida')
  return solicitarApiCliente(event, {
    ruta: `${RUTA_API_MEMBRESIAS}/checkout/${encodeURIComponent(sessionId)}/estado`,
    metodo: 'GET',
    incluirSesion: true,
  })
}
