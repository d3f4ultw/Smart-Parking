import {
  createError,
  getCookie,
  getRequestHeader,
  readBody,
  setResponseHeader,
  setResponseStatus,
  type H3Event,
} from 'h3'

type MetodoVision = 'GET' | 'POST' | 'DELETE' | 'PUT'
type TipoRespuestaVision = 'json' | 'image'

const MAXIMO_JSON_BYTES = 8 * 1024 * 1024
const MAXIMO_IMAGEN_BYTES = 4 * 1024 * 1024

function tieneControl(valor: string) {
  for (const caracter of valor) {
    const codigo = caracter.charCodeAt(0)
    if (codigo < 32 || codigo === 127) return true
  }
  return false
}

function exigirOrigen(event: H3Event, origenConfigurado: string) {
  let esperado: string
  try {
    esperado = new URL(origenConfigurado).origin
  } catch {
    throw createError({ statusCode: 500, statusMessage: 'Configuration unavailable' })
  }

  if (getRequestHeader(event, 'origin') !== esperado) {
    throw createError({ statusCode: 403, statusMessage: 'Origin not allowed' })
  }

  return esperado
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

function establecerNoCache(event: H3Event) {
  setResponseHeader(event, 'cache-control', 'no-store')
  setResponseHeader(event, 'pragma', 'no-cache')
  setResponseHeader(event, 'x-content-type-options', 'nosniff')
}

async function leerCuerpoLimitado(response: Response, limite: number) {
  const valorLength = response.headers.get('content-length')
  if (valorLength !== null) {
    const largo = Number(valorLength)
    if (!Number.isSafeInteger(largo) || largo < 0 || largo > limite) {
      await response.body?.cancel()
      throw createError({ statusCode: 502, statusMessage: 'Upstream response too large' })
    }
  }

  if (response.body === null) {
    return new Uint8Array()
  }

  const lector = response.body.getReader()
  const bloques: Uint8Array[] = []
  let total = 0
  try {
    while (true) {
      const bloque = await lector.read()
      if (bloque.done) {
        break
      }
      total += bloque.value.byteLength
      if (total > limite) {
        await lector.cancel()
        throw createError({ statusCode: 502, statusMessage: 'Upstream response too large' })
      }
      bloques.push(bloque.value)
    }
  } finally {
    lector.releaseLock()
  }

  const resultado = new Uint8Array(total)
  let posicion = 0
  for (const bloque of bloques) {
    resultado.set(bloque, posicion)
    posicion += bloque.byteLength
  }
  return resultado
}

async function respuestaErrorSegura(response: Response) {
  try {
    const bytes = await leerCuerpoLimitado(response, 4096)
    const texto = new TextDecoder().decode(bytes)
    const valor: unknown = JSON.parse(texto)
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
    // El BFF publica un error generico si el upstream no devuelve JSON seguro.
  }
  return {
    detail: response.status >= 500 ? 'Servicio no disponible' : 'Solicitud no valida',
  }
}

export async function proxyAdminVisionRequest(
  event: H3Event,
  ruta: string,
  metodo: MetodoVision = 'GET',
  tipoRespuesta: TipoRespuestaVision = 'json',
) {
  establecerNoCache(event)
  const config = useRuntimeConfig(event)
  const apiBaseUrl = config.apiInternalBaseUrl.replace(/\/+$/, '')
  const cookie = obtenerCookieSesion(event)
  const escritura = metodo === 'POST' || metodo === 'PUT' || metodo === 'DELETE'
  const headers = new Headers({
    accept: tipoRespuesta === 'image' ? 'image/jpeg, image/png' : 'application/json',
    cookie,
  })
  if (escritura) {
    headers.set('origin', exigirOrigen(event, config.public.managementOrigin))
  }

  let body: string | undefined
  if (metodo === 'POST' || metodo === 'PUT') {
    const tipoEntrada = getRequestHeader(event, 'content-type') ?? ''
    if (!/^application\/json(?:\s*;|$)/i.test(tipoEntrada)) {
      throw createError({ statusCode: 415, statusMessage: 'JSON required' })
    }
    body = JSON.stringify(await readBody<unknown>(event))
    headers.set('content-type', 'application/json')
  }

  const controlador = new AbortController()
  const respuestaNode = event.node.res
  const abortar = () => controlador.abort()
  const cerrar = () => {
    event.node.req.removeListener('aborted', abortar)
    respuestaNode.removeListener('close', cerrar)
  }
  event.node.req.once('aborted', abortar)
  respuestaNode.once('close', abortar)

  try {
    const upstream = await fetch(`${apiBaseUrl}/api/admin/vision/${ruta}`, {
      method: metodo,
      headers,
      body,
      cache: 'no-store',
      redirect: 'manual',
      signal: controlador.signal,
    })
    setResponseStatus(event, upstream.status)
    const retryAfter = upstream.headers.get('retry-after')
    if (retryAfter !== null && /^\d{1,5}$/.test(retryAfter)) {
      setResponseHeader(event, 'retry-after', Number(retryAfter))
    }

    if (upstream.status < 200 || upstream.status >= 300) {
      setResponseHeader(event, 'content-type', 'application/json; charset=utf-8')
      return await respuestaErrorSegura(upstream)
    }

    if (tipoRespuesta === 'json') {
      setResponseHeader(event, 'content-type', 'application/json; charset=utf-8')
      const bytes = await leerCuerpoLimitado(upstream, MAXIMO_JSON_BYTES)
      try {
        return JSON.parse(new TextDecoder().decode(bytes)) as unknown
      } catch {
        throw createError({ statusCode: 502, statusMessage: 'Invalid API response' })
      }
    }

    const tipoContenido = upstream.headers.get('content-type')?.split(';', 1)[0]?.trim().toLowerCase()
    if (tipoContenido !== 'image/jpeg' && tipoContenido !== 'image/png') {
      await upstream.body?.cancel()
      throw createError({ statusCode: 502, statusMessage: 'Invalid image response' })
    }
    setResponseHeader(event, 'content-type', tipoContenido)
    const origenImagen = upstream.headers.get('x-vision-snapshot-source')
    if (origenImagen === 'reference') {
      setResponseHeader(event, 'x-vision-snapshot-source', 'reference')
    }
    return await leerCuerpoLimitado(upstream, MAXIMO_IMAGEN_BYTES)
  } catch (error: unknown) {
    if (controlador.signal.aborted) {
      return undefined
    }
    if (error instanceof Error && 'statusCode' in error) {
      throw error
    }
    throw createError({ statusCode: 502, statusMessage: 'Vision API unavailable' })
  } finally {
    cerrar()
  }
}
