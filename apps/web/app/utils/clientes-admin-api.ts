import { appendResponseHeader, getRequestHeader, setResponseHeader } from 'h3'
import type {
  DetalleClienteAdministracion,
  EstadoFiltroClientes,
  PaginaClientesAdministracion,
} from '~/types/cliente-admin'

interface ErrorApiRespuesta {
  codigo?: string
  mensaje?: string
  error?: string
}

interface OpcionesSolicitud {
  query?: Record<string, string | string[]>
  signal?: AbortSignal
}

type FetchAdministracionClientes = <T>(
  ruta: string,
  opciones: Record<string, unknown>,
) => Promise<T>

export class ErrorClientesAdministracionApi extends Error {
  constructor(
    public readonly estado: number,
    public readonly codigo: string | null,
    mensaje: string,
  ) {
    super(mensaje)
  }
}

function mensajeSeguro(estado: number, detalle: boolean) {
  if (estado === 400) return 'Revisa la página, la búsqueda y el filtro e inténtalo de nuevo.'
  if (estado === 401) return 'Tu acceso venció. Inicia sesión de nuevo.'
  if (estado === 403) return 'No tienes acceso para consultar esta información.'
  if (estado === 404 && detalle) return 'No encontramos la información de este cliente.'
  return detalle
    ? 'No pudimos cargar la información del cliente. Inténtalo de nuevo.'
    : 'No pudimos cargar la lista de clientes. Revisa tu conexión e inténtalo de nuevo.'
}

export function useClienteAdministracionClientes() {
  const fetchApi = useRequestFetch() as unknown as FetchAdministracionClientes
  const evento = import.meta.server ? useRequestEvent() : undefined
  const cookie = evento ? getRequestHeader(evento, 'cookie') : undefined

  if (evento) {
    setResponseHeader(evento, 'cache-control', 'no-store, private')
    setResponseHeader(evento, 'vary', 'Cookie')
  }

  async function solicitar<T>(
    ruta: string,
    opciones: OpcionesSolicitud,
    detalle: boolean,
  ): Promise<T> {
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
      throw new ErrorClientesAdministracionApi(
        estado,
        error.data?.codigo ?? null,
        mensajeSeguro(estado, detalle),
      )
    }
  }

  return {
    listar(pagina: string, estado: EstadoFiltroClientes, signal?: AbortSignal, busqueda?: string) {
      return solicitar<PaginaClientesAdministracion>(
        '/api/v1/clientes/administracion',
        { query: { pagina, estado, ...(busqueda ? { busqueda } : {}) }, signal },
        false,
      )
    },
    consultar(codigo: string, signal?: AbortSignal) {
      return solicitar<DetalleClienteAdministracion>(
        `/api/v1/clientes/administracion/${encodeURIComponent(codigo)}`,
        { signal },
        true,
      )
    },
  }
}
