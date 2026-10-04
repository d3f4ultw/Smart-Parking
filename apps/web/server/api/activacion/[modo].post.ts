import { createError, getRouterParam, proxyRequest } from 'h3'

export default defineEventHandler((event) => {
  const modo = getRouterParam(event, 'modo')
  if (modo !== 'manual' && modo !== 'temporal') {
    throw createError({
      statusCode: 404,
      statusMessage: 'No encontrado',
    })
  }

  const config = useRuntimeConfig(event)
  const apiBaseUrl = config.apiInternalBaseUrl.replace(/\/+$/, '')
  return proxyRequest(
    event,
    `${apiBaseUrl}/api/autenticacion/activar/${modo}`,
  )
})
