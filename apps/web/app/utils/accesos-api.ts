import { appendResponseHeader, getRequestHeader, setResponseHeader } from 'h3'
import type {
  FiltroLectorAccesos,
  FiltroResultadoAccesos,
  PaginaHistorialAccesos,
  PeriodoHistorialAccesos,
} from '~/types/acceso'

interface ErrorApiRespuesta {
  codigo?: string
  error?: string
}

interface OpcionesSolicitud {
  query: Record<string, string>
  signal?: AbortSignal
}

type FetchHistorial = <T>(ruta: string, opciones: Record<string, unknown>) => Promise<T>

/** Conserva el código de respuesta y el motivo del fallo junto con un mensaje
 * que la pantalla puede mostrar sin revelar datos internos.
 */
export class ErrorHistorialAccesosApi extends Error {
  constructor(
    public readonly estado: number,
    public readonly codigo: string | null,
    mensaje: string,
  ) {
    super(mensaje)
  }
}

function mensajeSeguro(estado: number) {
  if (estado === 400) return 'Revisa los filtros e inténtalo de nuevo.'
  if (estado === 401) return 'Tu acceso venció. Inicia sesión de nuevo.'
  if (estado === 403) return 'No tienes acceso para consultar este historial.'
  return 'No pudimos cargar el historial. Revisa tu conexión e inténtalo de nuevo.'
}

/** Consulta el historial con sus filtros. Al preparar la primera página en el servidor,
 * envía los datos de acceso guardados en el navegador y devuelve cualquier dato de sesión actualizado.
 */
export function useClienteHistorialAccesos() {
  const fetchApi = useRequestFetch() as unknown as FetchHistorial
  const evento = import.meta.server ? useRequestEvent() : undefined
  const cookie = evento ? getRequestHeader(evento, 'cookie') : undefined

  if (evento) {
    setResponseHeader(evento, 'cache-control', 'no-store, private')
    setResponseHeader(evento, 'vary', 'Cookie')
  }

  async function solicitar<T>(ruta: string, opciones: OpcionesSolicitud): Promise<T> {
    const headers = { accept: 'application/json', ...(cookie ? { cookie } : {}) }
    try {
      return await fetchApi<T>(ruta, {
        ...opciones,
        method: 'GET',
        headers,
        onResponse({ response }: { response: Response }) {
          if (!evento) return
          for (const valor of response.headers.getSetCookie()) {
            appendResponseHeader(evento, 'set-cookie', valor)
          }
        },
      })
    } catch (fallo) {
      if (opciones.signal?.aborted) throw fallo
      const error = fallo as {
        statusCode?: number
        status?: number
        response?: { status?: number }
        data?: ErrorApiRespuesta
      }
      const estado = error.response?.status ?? error.statusCode ?? error.status ?? 503
      throw new ErrorHistorialAccesosApi(estado, error.data?.codigo ?? null, mensajeSeguro(estado))
    }
  }

  return {
    listar(
      pagina: string,
      lector: FiltroLectorAccesos,
      resultado: FiltroResultadoAccesos,
      periodo: PeriodoHistorialAccesos,
      desde?: string,
      hasta?: string,
      signal?: AbortSignal,
    ) {
      return solicitar<PaginaHistorialAccesos>('/api/v1/accesos/historial', {
        query: {
          pagina,
          lector,
          resultado,
          periodo,
          ...(periodo === 'PERSONALIZADO' ? { desde: desde ?? '', hasta: hasta ?? '' } : {}),
        },
        signal,
      })
    },
  }
}
