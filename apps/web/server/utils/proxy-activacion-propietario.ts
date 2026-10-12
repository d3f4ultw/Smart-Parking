import {
  createError,
  getCookie,
  getRequestHeader,
  readBody,
  sendProxy,
  setResponseHeader,
  type H3Event,
} from 'h3'

const COOKIE_DESAFIO = 'smart_parking_owner_activation_challenge'

export async function proxyActivacionPropietario(
  event: H3Event,
  suffix: 'enlace' | 'desafio' | 'completar',
) {
  const config = useRuntimeConfig(event)
  const apiBaseUrl = config.apiInternalBaseUrl.replace(/\/+$/, '')
  const url = `${apiBaseUrl}/api/autenticacion/activacion-propietario/${suffix}`
  setResponseHeader(event, 'cache-control', 'no-store')
  setResponseHeader(event, 'referrer-policy', 'no-referrer')

  const headers: Record<string, string> = {}
  const metodo = suffix === 'desafio' ? 'GET' : 'POST'
  if (suffix !== 'enlace') {
    const tokenDesafio = getCookie(event, COOKIE_DESAFIO)
    if (tokenDesafio !== undefined) {
      headers.cookie = `${COOKIE_DESAFIO}=${tokenDesafio}`
    }
  }

  const fetchOptions: { method: string; headers: Record<string, string>; body?: string } = {
    method: metodo,
    headers,
  }
  if (suffix !== 'desafio') {
    const contentType = getRequestHeader(event, 'content-type')
    if (contentType === undefined || !/^application\/json(?:\s*;|\s*$)/i.test(contentType)) {
      throw createError({ statusCode: 415, statusMessage: 'JSON request body required' })
    }
    headers['content-type'] = 'application/json'
    fetchOptions.body = JSON.stringify(await readBody<unknown>(event))
  }

  return sendProxy(event, url, { fetchOptions })
}
