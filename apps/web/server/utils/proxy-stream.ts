import { once } from 'node:events'

import {
  createError,
  getCookie,
  getQuery,
  setResponseHeader,
  type H3Event,
} from 'h3'

const MAXIMO_ERROR_BYTES = 4096
const CABECERAS_STREAM_SEGURAS = {
  'cache-control': 'no-store',
  pragma: 'no-cache',
  'x-content-type-options': 'nosniff',
  'x-accel-buffering': 'no',
}

function tieneControl(valor: string) {
  for (const caracter of valor) {
    const codigo = caracter.charCodeAt(0)
    if (codigo < 32 || codigo === 127) return true
  }
  return false
}

function obtenerCookieSesion(event: H3Event) {
  const config = useRuntimeConfig(event)
  const nombre = config.sessionCookieName
  const token = getCookie(event, nombre)
  if (
    typeof nombre !== 'string'
    || !/^[A-Za-z0-9_-]{1,64}$/.test(nombre)
    || token === undefined
    || !/^[A-Za-z0-9_-]{40,128}$/.test(token)
  ) {
    throw createError({ statusCode: 401, statusMessage: 'Not authenticated' })
  }
  return `${nombre}=${token}`
}

function detalleSeguro(cuerpo: string, statusCode: number) {
  try {
    const valor: unknown = JSON.parse(cuerpo)
    if (
      typeof valor === 'object'
      && valor !== null
      && 'detail' in valor
      && typeof valor.detail === 'string'
      && valor.detail.length <= 256
      && !tieneControl(valor.detail)
    ) {
      return { detail: valor.detail }
    }
  } catch {
    // Devuelve el mensaje fijo de abajo ante un cuerpo upstream no esperado.
  }
  return {
    detail: statusCode >= 500 ? 'Servicio no disponible' : 'Solicitud no valida',
  }
}

async function enviarErrorUpstream(
  event: H3Event,
  statusCode: number,
  body: ReadableStream<Uint8Array> | null,
) {
  const respuesta = event.node.res
  let texto = ''
  if (body !== null) {
    const lector = body.getReader()
    const bloques: Uint8Array[] = []
    let total = 0
    try {
      while (total < MAXIMO_ERROR_BYTES) {
        const parte = await lector.read()
        if (parte.done) {
          break
        }
        const restante = MAXIMO_ERROR_BYTES - total
        const bloque = parte.value.subarray(0, restante)
        bloques.push(bloque)
        total += bloque.byteLength
        if (bloque.byteLength !== parte.value.byteLength) {
          await lector.cancel()
          break
        }
      }
    } finally {
      lector.releaseLock()
    }
    const bytes = new Uint8Array(total)
    let posicion = 0
    for (const bloque of bloques) {
      bytes.set(bloque, posicion)
      posicion += bloque.byteLength
    }
    texto = new TextDecoder().decode(bytes)
  }

  respuesta.statusCode = statusCode
  respuesta.setHeader('content-type', 'application/json; charset=utf-8')
  respuesta.end(JSON.stringify(detalleSeguro(texto, statusCode)))
}

export async function proxyStreamVision(event: H3Event): Promise<void> {
  const config = useRuntimeConfig(event)
  const apiBaseUrl = config.apiInternalBaseUrl.replace(/\/+$/, '')
  const cookie = obtenerCookieSesion(event)
  const tipo = getQuery(event).tipo
  if (tipo !== undefined && tipo !== 'raw' && tipo !== 'annotated') {
    throw createError({ statusCode: 400, statusMessage: 'Invalid frame type' })
  }
  const tipoFrame = tipo === 'raw' ? 'raw' : 'annotated'
  const selectorFrame = tipo === undefined ? '' : `?tipo=${tipoFrame}`
  const controlador = new AbortController()
  const solicitud = event.node.req
  const respuesta = event.node.res

  const abortar = () => controlador.abort()
  const cerrar = () => {
    solicitud.removeListener('aborted', abortar)
    respuesta.removeListener('close', alCerrarRespuesta)
    respuesta.removeListener('finish', cerrar)
  }
  const alCerrarRespuesta = () => {
    if (!respuesta.writableFinished) {
      abortar()
    }
    cerrar()
  }
  solicitud.once('aborted', abortar)
  respuesta.once('close', alCerrarRespuesta)
  respuesta.once('finish', cerrar)

  for (const [nombre, valor] of Object.entries(CABECERAS_STREAM_SEGURAS)) {
    setResponseHeader(event, nombre, valor)
  }

  try {
    const upstream = await fetch(`${apiBaseUrl}/api/admin/vision/monitor/stream${selectorFrame}`, {
      headers: new Headers({
        accept: 'multipart/x-mixed-replace',
        cookie,
      }),
      cache: 'no-store',
      redirect: 'manual',
      signal: controlador.signal,
    })
    if (controlador.signal.aborted || respuesta.destroyed) {
      await upstream.body?.cancel()
      return
    }

    if (upstream.status < 200 || upstream.status >= 300) {
      await enviarErrorUpstream(event, upstream.status, upstream.body)
      return
    }

    const tipoContenido = upstream.headers.get('content-type') ?? ''
    const coincidencia = /^multipart\/x-mixed-replace\s*;\s*boundary=(?:"([A-Za-z0-9._-]{1,70})"|([A-Za-z0-9._-]{1,70}))$/i.exec(
      tipoContenido,
    )
    if (coincidencia === null || upstream.body === null) {
      await upstream.body?.cancel()
      await enviarErrorUpstream(event, 502, null)
      return
    }

    const boundary = coincidencia[1] ?? coincidencia[2]
    respuesta.statusCode = upstream.status
    respuesta.setHeader(
      'content-type',
      `multipart/x-mixed-replace; boundary=${boundary}`,
    )
    respuesta.setHeader('cache-control', 'no-store')
    respuesta.setHeader('pragma', 'no-cache')
    respuesta.setHeader('x-content-type-options', 'nosniff')
    respuesta.setHeader('x-accel-buffering', 'no')
    respuesta.flushHeaders()
    // El preambulo MIME fuerza el envio inmediato de cabeceras antes del primer frame.
    respuesta.write('\r\n')

    const lector = upstream.body.getReader()
    try {
      while (!controlador.signal.aborted && !respuesta.destroyed) {
        const bloque = await lector.read()
        if (bloque.done) {
          break
        }
        if (!respuesta.write(bloque.value)) {
          await once(respuesta, 'drain', { signal: controlador.signal })
        }
      }
    } finally {
      if (controlador.signal.aborted || respuesta.destroyed) {
        await lector.cancel().catch(() => undefined)
      }
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
      await enviarErrorUpstream(event, 502, null)
      return
    }
    respuesta.destroy()
  } finally {
    cerrar()
  }
}
