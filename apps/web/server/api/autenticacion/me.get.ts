import { proxyRequest, setResponseHeader } from 'h3'

export default defineEventHandler((event) => {
  const config = useRuntimeConfig(event)
  const apiBaseUrl = config.apiInternalBaseUrl.replace(/\/+$/, '')
  setResponseHeader(event, 'cache-control', 'no-store')
  return proxyRequest(event, `${apiBaseUrl}/api/autenticacion/me`)
})
