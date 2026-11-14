import { appendResponseHeader, getRequestHeader, setResponseHeader } from 'h3'
import type {
  DetalleOperador,
  EstadoCuentaOperador,
  FiltroEstadoOperador,
  PaginaOperadores,
  RespuestaReemisionInvitacion,
  RespuestaSolicitudRecuperacion,
} from '~/types/operador'

interface ErrorApiRespuesta {
  codigo?: string
}

interface OpcionesSolicitud {
  method?: 'GET' | 'POST' | 'PATCH'
  query?: Record<string, string | string[]>
  headers?: Record<string, string>
  body?: object
  signal?: AbortSignal
}

type FetchOperadores = <T>(ruta: string, opciones: Record<string, unknown>) => Promise<T>
interface MetadatosRespuesta {
  etag: string | null
}

/** Conserva el código de respuesta, el motivo del fallo y el tiempo de espera
 * que debe respetarse cuando el servidor limita los intentos.
 */
export class ErrorOperadoresApi extends Error {
  constructor(
    public readonly estado: number,
    public readonly codigo: string | null,
    mensaje: string,
    public readonly retryAfter: string | null = null,
  ) {
    super(mensaje)
  }
}

function mensajeSeguro(estado: number, metodo?: string, codigo?: string | null) {
  if (codigo === 'EMPLEADO_REQUERIDO') {
    return 'Vincula esta cuenta con un empleado antes de reactivarla.'
  }
  if (estado === 401) return 'Tu acceso venció. Inicia sesión de nuevo.'
  if (estado === 403) return 'No pudimos hacer el cambio. Inténtalo de nuevo.'
  if (estado === 404) return 'No encontramos esta cuenta. Actualiza la lista e inténtalo de nuevo.'
  if (estado === 412) return 'La cuenta cambió. Actualiza la información y vuelve a intentarlo.'
  if (estado === 428) return 'La cuenta cambió. Actualiza la información y vuelve a intentarlo.'
  if (estado === 409)
    return 'Esta acción ya no está disponible. Actualiza la lista e inténtalo de nuevo.'
  if (estado === 429) return 'Lo intentaste varias veces. Espera un momento y vuelve a intentarlo.'
  if (estado >= 500 || estado === 0) {
    return metodo === 'POST' || metodo === 'PATCH'
      ? 'No sabemos si se guardó el cambio. Revisa la lista antes de intentarlo de nuevo.'
      : 'No pudimos conectar con Smart Parking. Revisa tu conexión e inténtalo de nuevo.'
  }
  return 'No pudimos completar el cambio. Revisa la información e inténtalo de nuevo.'
}

/** Reúne las consultas y cambios de cuentas de operador; envía el número de revisión
 * leído y respeta el tiempo de espera si el servidor limita una acción.
 */
export function useClienteOperadores() {
  const fetchApi = useRequestFetch() as unknown as FetchOperadores
  const evento = import.meta.server ? useRequestEvent() : undefined
  const cookie = evento ? getRequestHeader(evento, 'cookie') : undefined

  if (evento) {
    setResponseHeader(evento, 'cache-control', 'no-store, private')
    setResponseHeader(evento, 'vary', 'Cookie')
  }

  async function solicitar<T>(
    ruta: string,
    opciones: OpcionesSolicitud = {},
    metadatos?: MetadatosRespuesta,
  ): Promise<T> {
    const headers = {
      accept: 'application/json',
      ...(cookie ? { cookie } : {}),
      ...opciones.headers,
    }
    try {
      const parametros: Record<string, unknown> = {
        ...opciones,
        headers,
        onResponse({ response }: { response: Response }) {
          if (metadatos) metadatos.etag = response.headers.get('etag')
          if (evento) {
            for (const valor of response.headers.getSetCookie()) {
              appendResponseHeader(evento, 'set-cookie', valor)
            }
          }
        },
      }
      return await fetchApi<T>(ruta, parametros)
    } catch (fallo) {
      const error = fallo as {
        statusCode?: number
        status?: number
        response?: { status?: number; headers?: Headers }
        data?: ErrorApiRespuesta
      }
      const estado = error.response?.status ?? error.statusCode ?? error.status ?? 0
      throw new ErrorOperadoresApi(
        estado,
        error.data?.codigo ?? null,
        mensajeSeguro(estado, opciones.method, error.data?.codigo ?? null),
        error.response?.headers?.get('retry-after') ?? null,
      )
    }
  }

/** Obtiene el detalle y guarda el número de revisión con que se leyó;
 * los cambios posteriores se aceptan solo si la cuenta sigue en esa versión.
 */
  async function detalle(id: string, signal?: AbortSignal) {
    const metadatos: MetadatosRespuesta = { etag: null }
    const datos = await solicitar<DetalleOperador>(
      `/api/v1/operadores/${encodeURIComponent(id)}`,
      { method: 'GET', signal },
      metadatos,
    )
    if (!metadatos.etag || !/^"\d+"$/.test(metadatos.etag)) {
      throw new ErrorOperadoresApi(
        502,
        'ETAG_NO_VALIDO',
        'No pudimos cargar esta cuenta. Actualiza la lista e inténtalo de nuevo.',
      )
    }
    return { datos, etag: metadatos.etag }
  }

  return {
    listar(pagina: string, busqueda: string, estado: FiltroEstadoOperador, signal?: AbortSignal) {
      return solicitar<PaginaOperadores>('/api/v1/operadores', {
        method: 'GET',
        query: { pagina, busqueda, estado },
        signal,
      })
    },
    detalle,
    cambiarEstado(
      id: string,
      estado: Extract<EstadoCuentaOperador, 'PENDIENTE' | 'INACTIVA'>,
      etag: string,
      csrf: string,
      clave?: string,
    ) {
      const headers = { 'if-match': etag, 'x-csrf-token': csrf }
      return solicitar<DetalleOperador>(`/api/v1/operadores/${encodeURIComponent(id)}/estado`, {
        method: 'PATCH',
        body: { estado },
        headers: clave ? { ...headers, 'idempotency-key': clave } : headers,
      })
    },
    reemitirInvitacion(id: string, etag: string, clave: string, csrf: string) {
      return solicitar<RespuestaReemisionInvitacion>(
        `/api/v1/operadores/${encodeURIComponent(id)}/invitacion/reemitir`,
        {
          method: 'POST',
          headers: {
            'if-match': etag,
            'idempotency-key': clave,
            'x-csrf-token': csrf,
          },
        },
      )
    },
    solicitarRecuperacion(id: string, etag: string, clave: string, csrf: string) {
      return solicitar<RespuestaSolicitudRecuperacion>(
        `/api/v1/operadores/${encodeURIComponent(id)}/recuperacion`,
        {
          method: 'POST',
          headers: {
            'if-match': etag,
            'idempotency-key': clave,
            'x-csrf-token': csrf,
          },
        },
      )
    },
  }
}
