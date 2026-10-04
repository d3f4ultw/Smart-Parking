import { proxyRequest } from 'h3'

export default defineEventHandler((event) => {
  const config = useRuntimeConfig(event)
  const apiBaseUrl = config.apiInternalBaseUrl.replace(/\/+$/, '')
  return proxyRequest(
    event,
    `${apiBaseUrl}/api/autenticacion/activacion/prevalidar`,
  )
})
