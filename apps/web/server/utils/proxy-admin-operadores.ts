import { proxyRequest, setResponseHeader, type H3Event } from 'h3'

export function proxyAdminOperadores(
  event: H3Event,
  suffix = '',
  pagina?: string | null,
) {
  const config = useRuntimeConfig(event)
  const apiBaseUrl = config.apiInternalBaseUrl.replace(/\/+$/, '')
  const consulta = pagina === undefined || pagina === null
    ? ''
    : `?pagina=${encodeURIComponent(pagina)}`
  setResponseHeader(event, 'cache-control', 'no-store')
  return proxyRequest(
    event,
    `${apiBaseUrl}/api/admin/operadores${suffix}${consulta}`,
  )
}
