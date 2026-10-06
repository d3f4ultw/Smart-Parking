import { proxyRequest, setResponseHeader, type H3Event } from 'h3'

export function proxyAdminOperadores(
  event: H3Event,
  suffix = '',
  pagina?: string | null,
  buscar?: string | null,
) {
  const config = useRuntimeConfig(event)
  const apiBaseUrl = config.apiInternalBaseUrl.replace(/\/+$/, '')
  const parametros = new URLSearchParams()
  if (pagina !== undefined && pagina !== null) {
    parametros.set('pagina', pagina)
  }
  if (buscar !== undefined && buscar !== null) {
    parametros.set('buscar', buscar)
  }
  const consulta = parametros.size > 0 ? '?' + parametros.toString() : ''
  setResponseHeader(event, 'cache-control', 'no-store')
  return proxyRequest(
    event,
    `${apiBaseUrl}/api/admin/operadores${suffix}${consulta}`,
  )
}
