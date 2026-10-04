import {
  getQuery,
  getRequestHeader,
  proxyRequest,
  setResponseHeader,
  type H3Event,
} from 'h3'

function obtenerCursorInicial(event: H3Event): string | undefined {
  const valor = getQuery(event).cursor_eventos
  if (valor === undefined) {
    return undefined
  }
  if (typeof valor !== 'string' || !/^\d+$/.test(valor)) {
    throw createError({
      statusCode: 400,
      statusMessage: 'Cursor de eventos inválido',
    })
  }
  return valor
}

export default defineEventHandler((event) => {
  setResponseHeader(event, 'cache-control', 'no-store')
  setResponseHeader(event, 'x-accel-buffering', 'no')

  const cursorInicial = obtenerCursorInicial(event)
  const ultimoEvento = getRequestHeader(event, 'last-event-id') ?? cursorInicial
  const config = useRuntimeConfig(event)
  const apiBaseUrl = config.apiInternalBaseUrl.replace(/\/+$/, '')
  const controlador = new AbortController()
  const respuesta = event.node.res

  const limpiarEscuchas = () => {
    respuesta.removeListener('close', alCerrar)
    respuesta.removeListener('finish', limpiarEscuchas)
  }
  const alCerrar = () => {
    if (!respuesta.writableFinished) {
      controlador.abort()
    }
    limpiarEscuchas()
  }

  respuesta.once('close', alCerrar)
  respuesta.once('finish', limpiarEscuchas)

  return proxyRequest(
    event,
    `${apiBaseUrl}/api/admin/operadores/eventos`,
    {
      fetchOptions: {
        headers: {
          accept: 'text/event-stream',
          ...(ultimoEvento === undefined ? {} : { 'last-event-id': ultimoEvento }),
        },
        signal: controlador.signal,
      },
    },
  )
})
