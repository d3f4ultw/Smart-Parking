import { appendResponseHeader, getRequestHeader, setResponseHeader } from 'h3'
import type { CajonVision } from '~/types/vision'

interface ErrorApiRespuesta {
  codigo?: string
}

type FetchVision = <T>(ruta: string, opciones: Record<string, unknown>) => Promise<T>

/** Ocupación recibida, marca desde la que pueden buscarse cambios nuevos
 * y tiempo durante el que estos datos siguen vigentes.
 */
export interface LecturaVision {
  cajones: CajonVision[]
  cursor: string | null
  vigenciaRestanteMs: number | null
}

/** Guarda el código de respuesta y un mensaje que la pantalla puede mostrar
 * sin exponer detalles internos del servicio de Vision.
 */
export class ErrorVisionApi extends Error {
  constructor(
    public readonly estado: number,
    public readonly codigo: string | null,
    mensaje: string,
  ) {
    super(mensaje)
  }
}

function mensajeSeguro(estado: number) {
  if (estado === 401) return 'Tu acceso venció. Inicia sesión de nuevo.'
  if (estado === 403) return 'No tienes acceso para consultar la ocupación.'
  return 'No pudimos actualizar la ocupación. Revisa tu conexión e inténtalo de nuevo.'
}

function esCajonVision(valor: unknown): valor is CajonVision {
  if (!valor || typeof valor !== 'object') return false
  const cajon = valor as Record<string, unknown>
  return (
    typeof cajon.cajonId === 'string' &&
    typeof cajon.etiqueta === 'string' &&
    (cajon.displayName === undefined ||
      cajon.displayName === null ||
      typeof cajon.displayName === 'string') &&
    (cajon.estado === 'LIBRE' || cajon.estado === 'OCUPADO' || cajon.estado === 'NO_VERIFICABLE') &&
    (cajon.ultimoEstadoConfirmado === null ||
      cajon.ultimoEstadoConfirmado === 'LIBRE' ||
      cajon.ultimoEstadoConfirmado === 'OCUPADO') &&
    (cajon.observadoEn === null || typeof cajon.observadoEn === 'string')
  )
}

/** Consulta la ocupación y permite cambiar las etiquetas de los espacios. Al preparar
 * la página en el servidor, usa los datos de sesión de esta solicitud y pide que la respuesta
 * no se guarde ni se reutilice después.
 */
export function useClienteVision() {
  const fetchApi = useRequestFetch() as unknown as FetchVision
  const csrf = useCsrf()
  const evento = import.meta.server ? useRequestEvent() : undefined
  const cookie = evento ? getRequestHeader(evento, 'cookie') : undefined

  if (evento) {
    setResponseHeader(evento, 'cache-control', 'no-store, private')
    setResponseHeader(evento, 'vary', 'Cookie')
  }

  async function listar(signal?: AbortSignal): Promise<LecturaVision> {
    let respuesta: unknown
    let cursor: string | null = null
    let vigenciaRestanteMs: number | null = null
    try {
      respuesta = await fetchApi<unknown>('/api/v1/vision/cajones', {
        method: 'GET',
        retry: 0,
        headers: { accept: 'application/json', ...(cookie ? { cookie } : {}) },
        signal,
        onResponse({ response }: { response: Response }) {
          cursor = response.headers.get('x-eventos-cursor')
          const vigencia = response.headers.get('x-vision-vigencia-restante-ms')
          if (vigencia && /^\d+$/.test(vigencia)) {
            const milisegundos = Number(vigencia)
            if (Number.isSafeInteger(milisegundos)) vigenciaRestanteMs = milisegundos
          }
          if (!evento) return
          for (const valor of response.headers.getSetCookie()) {
            appendResponseHeader(evento, 'set-cookie', valor)
          }
        },
      })
    } catch (fallo) {
      if (signal?.aborted) throw fallo
      const error = fallo as {
        statusCode?: number
        status?: number
        response?: { status?: number }
        data?: ErrorApiRespuesta
      }
      const estado = error.response?.status ?? error.statusCode ?? error.status ?? 503
      throw new ErrorVisionApi(estado, error.data?.codigo ?? null, mensajeSeguro(estado))
    }

    if (!Array.isArray(respuesta) || !respuesta.every(esCajonVision)) {
      throw new ErrorVisionApi(503, 'VISION_RESPUESTA_INVALIDA', mensajeSeguro(503))
    }
    return { cajones: respuesta, cursor, vigenciaRestanteMs }
  }

  async function actualizarNombre(cajonId: string, displayName: string | null): Promise<void> {
    if (import.meta.server) throw new Error('El nombre se guarda desde el navegador.')
    try {
      const token = await csrf.obtener()
      await fetchApi<void>(`/api/v1/vision/cajones/${encodeURIComponent(cajonId)}/display-name`, {
        method: 'PUT',
        retry: 0,
        headers: { accept: 'application/json', 'X-CSRF-TOKEN': token },
        body: { displayName },
      })
    } catch (fallo) {
      const error = fallo as {
        statusCode?: number
        status?: number
        response?: { status?: number }
        data?: ErrorApiRespuesta
      }
      const estado = error.response?.status ?? error.statusCode ?? error.status ?? 503
      const mensaje =
        estado === 401
          ? 'Tu acceso venció. Inicia sesión de nuevo.'
          : estado === 403
            ? 'Tu acceso no permite guardar este nombre.'
            : estado === 409
              ? 'El cajón ya no está activo. Actualiza la pantalla.'
              : 'No pudimos confirmar el guardado. Actualiza antes de intentarlo de nuevo.'
      throw new ErrorVisionApi(estado, error.data?.codigo ?? null, mensaje)
    }
  }

  return { listar, actualizarNombre }
}
