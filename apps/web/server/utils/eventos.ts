import {
  getQuery,
  getRequestHeader,
  setResponseHeader,
  type H3Event,
} from 'h3'
import { once } from 'node:events'

const CABECERAS_SALTO = new Set([
  'connection',
  'content-encoding',
  'content-length',
  'keep-alive',
  'transfer-encoding',
  'upgrade',
])

function obtenerCursorInicial(event: H3Event): string | undefined {
  const valor = getQuery(event).cursor_eventos
  if (valor === undefined) {
    return undefined
  }
  if (
    typeof valor !== 'string'
    || valor.length === 0
    || valor.length > 19
    || !/^\d+$/.test(valor)
  ) {
    throw createError({
      statusCode: 400,
      statusMessage: 'Cursor de eventos inválido',
    })
  }
  return valor
}

export function proxyEventos(event: H3Event) {
  setResponseHeader(event, 'cache-control', 'no-store')
  setResponseHeader(event, 'x-accel-buffering', 'no')

  const cursorInicial = obtenerCursorInicial(event)
  const ultimoEvento = getRequestHeader(event, 'last-event-id')
  const cookie = getRequestHeader(event, 'cookie')
  const query = cursorInicial === undefined
    ? ''
    : `?cursor_eventos=${encodeURIComponent(cursorInicial)}`
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

  const headers = new Headers({ accept: 'text/event-stream' })
  if (cookie !== undefined) {
    headers.set('cookie', cookie)
  }
  if (ultimoEvento !== undefined) {
    headers.set('last-event-id', ultimoEvento)
  }

  return enviarProxyEventos(
    event,
    `${apiBaseUrl}/api/eventos${query}`,
    headers,
    controlador,
    limpiarEscuchas,
  )
}

async function enviarProxyEventos(
  event: H3Event,
  url: string,
  headers: Headers,
  controlador: AbortController,
  limpiarEscuchas: () => void,
): Promise<void> {
  const respuesta = event.node.res
  let upstream: Response
  try {
    upstream = await fetch(url, {
      headers,
      signal: controlador.signal,
    })
  } catch {
    limpiarEscuchas()
    if (controlador.signal.aborted) {
      return
    }
    throw createError({
      statusCode: 502,
      statusMessage: 'Bad Gateway',
    })
  }

  for (const [nombre, valor] of upstream.headers) {
    if (!CABECERAS_SALTO.has(nombre.toLowerCase())) {
      setResponseHeader(event, nombre, valor)
    }
  }
  respuesta.statusCode = upstream.status
  setResponseHeader(event, 'cache-control', 'no-store')
  setResponseHeader(event, 'x-accel-buffering', 'no')

  const tipoContenido = upstream.headers.get('content-type')?.toLowerCase()
  const esStreamSse = upstream.status >= 200
    && upstream.status < 300
    && tipoContenido?.startsWith('text/event-stream') === true

  try {
    if (!esStreamSse) {
      const cuerpo = new Uint8Array(await upstream.arrayBuffer())
      if (!respuesta.destroyed) {
        respuesta.end(cuerpo)
      }
      return
    }

    respuesta.writeHead(upstream.status)
    respuesta.flushHeaders()
    respuesta.write(':\n\n')
    const lector = upstream.body?.getReader()
    if (lector === undefined) {
      respuesta.end()
      return
    }

    try {
      while (!controlador.signal.aborted) {
        const bloque = await lector.read()
        if (bloque.done || respuesta.destroyed) {
          break
        }
        if (!respuesta.write(bloque.value)) {
          await once(respuesta, 'drain', { signal: controlador.signal })
        }
      }
    } finally {
      lector.releaseLock()
    }

    if (!respuesta.destroyed && !respuesta.writableEnded) {
      respuesta.end()
    }
  } catch {
    if (controlador.signal.aborted || respuesta.destroyed) {
      return
    }
    if (!respuesta.headersSent) {
      throw createError({
        statusCode: 502,
        statusMessage: 'Bad Gateway',
      })
    }
    respuesta.destroy()
  } finally {
    limpiarEscuchas()
  }
}
