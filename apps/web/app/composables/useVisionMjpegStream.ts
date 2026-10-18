import { nextTick, ref, shallowRef } from 'vue'
import { DecodificadorMjpeg, obtenerBoundaryMjpeg } from '~/utils/vision-mjpeg'
import {
  clasificarErrorHttpMjpeg,
  LIMITE_SIN_AVANCE_VISION_MS,
  retrasoReconexionVision,
  streamVisionSinProgreso,
} from '~/utils/vision-stream-recovery'

export type EstadoStreamMjpeg =
  | 'detenido'
  | 'conectando'
  | 'en-vivo'
  | 'reconectando'
  | 'desconectado'

type OpcionesStreamMjpeg = {
  alFallarAutorizacion?: (fallo: { statusCode: number }) => void | Promise<void>
}

class ErrorHttpStreamMjpeg extends Error {
  constructor(readonly statusCode: number) {
    super('El stream MJPEG devolvió un estado HTTP no satisfactorio.')
  }
}

function esperar(retraso: number, signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    if (signal.aborted) {
      resolve()
      return
    }
    const finalizar = () => {
      clearTimeout(temporizador)
      signal.removeEventListener('abort', finalizar)
      resolve()
    }
    const temporizador = setTimeout(finalizar, retraso)
    signal.addEventListener('abort', finalizar, { once: true })
    if (signal.aborted) finalizar()
  })
}

function actualizarFps(momentos: number[], ahora: number) {
  momentos.push(ahora)
  while (momentos.length > 0 && ahora - momentos[0]! > 5000) momentos.shift()
  if (momentos.length > 128) momentos.splice(0, momentos.length - 128)
  if (momentos.length < 2) return 0
  const intervalo = momentos.at(-1)! - momentos[0]!
  return intervalo > 0 ? Math.round(((momentos.length - 1) * 1000 / intervalo) * 10) / 10 : 0
}

async function leerConLimite(
  lector: ReadableStreamDefaultReader<Uint8Array>,
  limiteMs: number,
  alVencer: () => void,
) {
  let temporizador: ReturnType<typeof setTimeout> | null = null
  try {
    return await Promise.race([
      lector.read(),
      new Promise<never>((_, rechazar) => {
        temporizador = setTimeout(() => {
          alVencer()
          rechazar(new Error('El stream MJPEG dejó de entregar frames.'))
        }, limiteMs)
      }),
    ])
  } finally {
    if (temporizador !== null) clearTimeout(temporizador)
  }
}

async function consumirStream(
  url: string,
  controlador: AbortController,
  alRecibirFrame: (frame: Uint8Array) => void,
) {
  const respuesta = await fetch(url, {
    credentials: 'same-origin',
    cache: 'no-store',
    headers: { accept: 'multipart/x-mixed-replace' },
    signal: controlador.signal,
  })
  if (!respuesta.ok) {
    await respuesta.body?.cancel().catch(() => undefined)
    throw new ErrorHttpStreamMjpeg(respuesta.status)
  }
  if (respuesta.body === null) {
    throw new Error('La respuesta MJPEG no contiene un stream.')
  }

  let boundary: string
  try {
    boundary = obtenerBoundaryMjpeg(respuesta.headers.get('content-type') ?? '')
  } catch (fallo: unknown) {
    await respuesta.body.cancel().catch(() => undefined)
    throw fallo
  }
  const lector = respuesta.body.getReader()
  const decodificador = new DecodificadorMjpeg(boundary)
  const inicio = performance.now()
  let ultimoFrame = inicio

  try {
    while (!controlador.signal.aborted) {
      const ahora = performance.now()
      const sinAvance = streamVisionSinProgreso({
        ahora,
        ultimoFrameRecibido: ultimoFrame,
        inicioStream: inicio,
        limiteSinAvance: LIMITE_SIN_AVANCE_VISION_MS,
      })
      if (sinAvance) {
        controlador.abort()
        throw new Error('El stream MJPEG dejó de entregar frames.')
      }
      const restante = LIMITE_SIN_AVANCE_VISION_MS - (ahora - ultimoFrame)
      const parte = await leerConLimite(lector, restante, () => controlador.abort())
      if (parte.done) {
        throw new Error('El stream MJPEG terminó.')
      }
      for (const frame of decodificador.agregar(parte.value)) {
        ultimoFrame = performance.now()
        alRecibirFrame(frame)
      }
    }
  } finally {
    await lector.cancel().catch(() => undefined)
    lector.releaseLock()
  }
}

export function useVisionMjpegStream(url: string, opciones: OpcionesStreamMjpeg = {}) {
  const frameUrl = shallowRef('')
  const estado = ref<EstadoStreamMjpeg>('detenido')
  const framesRecibidos = ref(0)
  const framesMostrados = ref(0)
  const fpsRecepcion = ref(0)
  const fpsRenderizado = ref(0)
  const ultimoFrameRecibido = ref(0)
  const ultimoFrameMostrado = ref(0)
  const LIMITE_RENDER_MS = 66
  let activo = false
  let generacion = 0
  let fallosConsecutivos = 0
  let ultimaPublicacion = 0
  let controladorCiclo: AbortController | null = null
  let controladorPeticion: AbortController | null = null
  let ejecucion: Promise<void> | null = null
  let urlMostrada = ''
  let ultimoFrameRecibidoMonotono = 0
  const momentosRecepcion: number[] = []
  const momentosRenderizado: number[] = []
  const urlsImagen = new Set<string>()

  function liberarUrls(excepto: string[] = []) {
    for (const urlImagen of urlsImagen) {
      if (excepto.includes(urlImagen)) continue
      URL.revokeObjectURL(urlImagen)
      urlsImagen.delete(urlImagen)
    }
  }

  function publicarFrame(frame: Uint8Array, token: number) {
    if (!activo || token !== generacion) return
    framesRecibidos.value += 1
    ultimoFrameRecibido.value = Date.now()
    ultimoFrameRecibidoMonotono = performance.now()
    fpsRecepcion.value = actualizarFps(momentosRecepcion, ultimoFrameRecibidoMonotono)
    fallosConsecutivos = 0

    const ahora = performance.now()
    if (frameUrl.value !== '' && ahora - ultimaPublicacion < LIMITE_RENDER_MS) return
    const urlNueva = URL.createObjectURL(
      new Blob([frame.slice().buffer], { type: 'image/jpeg' }),
    )
    ultimaPublicacion = ahora
    urlsImagen.add(urlNueva)
    frameUrl.value = urlNueva
    if (estado.value === 'desconectado') estado.value = 'reconectando'
    liberarUrls([urlNueva, urlMostrada])
  }

  async function ejecutar(token: number, signal: AbortSignal) {
    while (activo && token === generacion && !signal.aborted) {
      const controlador = new AbortController()
      controladorPeticion = controlador
      const abortarPeticion = () => controlador.abort()
      signal.addEventListener('abort', abortarPeticion, { once: true })
      estado.value = fallosConsecutivos === 0 ? 'conectando' : 'reconectando'
      let porCapacidad = false

      try {
        await consumirStream(url, controlador, (frame) => publicarFrame(frame, token))
        if (!signal.aborted) throw new Error('El stream MJPEG terminó.')
      } catch (fallo: unknown) {
        if (signal.aborted || token !== generacion || !activo) return
        const clasificacionHttp = fallo instanceof ErrorHttpStreamMjpeg
          ? clasificarErrorHttpMjpeg(fallo.statusCode)
          : null
        if (clasificacionHttp === 'autorizacion') {
          activo = false
          estado.value = 'desconectado'
          if (fallo instanceof ErrorHttpStreamMjpeg) {
            await opciones.alFallarAutorizacion?.({ statusCode: fallo.statusCode })
          }
          return
        }
        porCapacidad = clasificacionHttp === 'capacidad'
        fallosConsecutivos += 1
        estado.value = fallosConsecutivos >= 5 ? 'desconectado' : 'reconectando'
      } finally {
        signal.removeEventListener('abort', abortarPeticion)
        if (controladorPeticion === controlador) controladorPeticion = null
        controlador.abort()
      }

      if (signal.aborted || token !== generacion || !activo) return
      const indiceReintento = Math.max(0, fallosConsecutivos - 1)
      await esperar(retrasoReconexionVision(indiceReintento, porCapacidad), signal)
    }
  }

  function asegurarEjecucion() {
    if (!import.meta.client || !activo || ejecucion !== null) return
    const token = generacion
    const ciclo = new AbortController()
    controladorCiclo = ciclo
    const actual = ejecutar(token, ciclo.signal).finally(() => {
      if (ejecucion === actual) ejecucion = null
      if (controladorCiclo === ciclo) controladorCiclo = null
      if (activo) asegurarEjecucion()
    })
    ejecucion = actual
  }

  function iniciar() {
    if (!activo) {
      activo = true
      generacion += 1
      fallosConsecutivos = 0
      ultimaPublicacion = 0
      estado.value = frameUrl.value === '' ? 'conectando' : 'reconectando'
    }
    asegurarEjecucion()
  }

  async function detener() {
    activo = false
    const token = ++generacion
    controladorCiclo?.abort()
    controladorPeticion?.abort()
    const pendiente = ejecucion
    await pendiente
    if (activo || token !== generacion) return
    estado.value = 'detenido'
    frameUrl.value = ''
    framesRecibidos.value = 0
    framesMostrados.value = 0
    fpsRecepcion.value = 0
    fpsRenderizado.value = 0
    ultimoFrameRecibido.value = 0
    ultimoFrameMostrado.value = 0
    urlMostrada = ''
    ultimoFrameRecibidoMonotono = 0
    momentosRecepcion.length = 0
    momentosRenderizado.length = 0
    await nextTick()
    liberarUrls()
  }

  async function reintentar() {
    await detener()
    fallosConsecutivos = 0
    ultimaPublicacion = 0
    iniciar()
  }

  function registrarFrameMostrado(url: string) {
    if (url === '' || url !== frameUrl.value) return false
    const ahora = performance.now()
    if (
      !activo
      || ultimoFrameRecibidoMonotono === 0
      || ahora - ultimoFrameRecibidoMonotono >= LIMITE_SIN_AVANCE_VISION_MS
    ) {
      if (activo && estado.value !== 'desconectado') estado.value = 'reconectando'
      return false
    }
    urlMostrada = url
    framesMostrados.value += 1
    ultimoFrameMostrado.value = Date.now()
    fpsRenderizado.value = actualizarFps(momentosRenderizado, ahora)
    fallosConsecutivos = 0
    estado.value = 'en-vivo'
    liberarUrls([url])
    return true
  }

  function notificarErrorRender(url: string) {
    if (url === '' || url !== frameUrl.value) return false
    controladorPeticion?.abort()
    return true
  }

  return {
    frameUrl,
    estado,
    framesRecibidos,
    framesMostrados,
    fpsRecepcion,
    fpsRenderizado,
    ultimoFrameRecibido,
    ultimoFrameMostrado,
    iniciar,
    detener,
    reintentar,
    registrarFrameMostrado,
    notificarErrorRender,
  }
}
