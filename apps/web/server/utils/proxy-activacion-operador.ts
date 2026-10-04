import { proxyRequest, setResponseHeader, type H3Event } from 'h3'

export function proxyActivacionOperador(event: H3Event, suffix: string) {
  const config = useRuntimeConfig(event)
  const apiBaseUrl = config.apiInternalBaseUrl.replace(/\/+$/, '')
  setResponseHeader(event, 'cache-control', 'no-store')
  setResponseHeader(event, 'referrer-policy', 'no-referrer')
  return proxyRequest(
    event,
    `${apiBaseUrl}/api/autenticacion/activacion-operador/${suffix}`,
  )
}
