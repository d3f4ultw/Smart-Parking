import { appendResponseHeader, setResponseHeader } from 'h3'
import type {
  PortalCliente,
  RespuestaCsrfCliente,
  RespuestaEstadoCheckoutMembresia,
  RespuestaCheckoutMembresia,
  RespuestaRegistroCliente,
  RespuestaSesionCliente,
  SolicitudCambioContrasenaCliente,
  SolicitudInicioSesionCliente,
  SolicitudRegistroCliente,
} from '~/types/cliente'

export const CLAVE_PORTAL_CLIENTE = 'portal-cliente-actual'

type MetodoClienteApi = 'GET' | 'POST' | 'DELETE' | 'PATCH'

interface OpcionesSolicitud {
  method?: MetodoClienteApi
  body?: object
  headers?: Record<string, string>
  signal?: AbortSignal
}

type FetchCliente = <T>(ruta: string, opciones: Record<string, unknown>) => Promise<T>

interface ErrorApiRespuesta {
  codigo?: string
}

/** Guarda el código y el motivo del fallo junto con un mensaje que la pantalla
 * puede mostrar sin revelar detalles internos.
 */
export class ErrorClienteApi extends Error {
  constructor(
    public readonly estado: number,
    public readonly codigo: string | null,
    mensaje: string,
  ) {
    super(mensaje)
  }
}

function mensajeSeguro(estado: number, codigo: string | null, metodo?: MetodoClienteApi) {
  if (codigo === 'CREDENCIALES_NO_VALIDAS') {
    return 'El correo o la contraseña no son correctos.'
  }
  if (estado === 401) return 'Tu acceso venció. Inicia sesión de nuevo.'
  if (codigo === 'CSRF_RECHAZADO')
    return 'La solicitud venció. Actualiza la página e inténtalo de nuevo.'
  if (estado === 400) return 'Revisa los datos e inténtalo de nuevo.'
  if (codigo === 'REGISTRO_NO_DISPONIBLE') {
    return 'No pudimos crear la cuenta con esos datos. Revisa la información e inténtalo de nuevo.'
  }
  if (estado === 409) {
    return 'La información cambió o la acción no está disponible. Actualiza la página e inténtalo de nuevo.'
  }
  if (estado === 429) return 'Has intentado varias veces. Espera un momento e inténtalo de nuevo.'
  if (estado === 0 || estado >= 500) {
    return metodo === 'POST' || metodo === 'PATCH' || metodo === 'DELETE'
      ? 'No pudimos confirmar la acción. Revisa el estado de tu cuenta antes de volver a intentarlo.'
      : 'No pudimos conectar con Smart Parking. Revisa tu conexión e inténtalo de nuevo.'
  }
  return 'No pudimos completar la acción. Revisa la información e inténtalo de nuevo.'
}

/** Reúne las operaciones del portal; usa los datos de sesión del navegador al preparar
 * la página en el servidor y evita guardar respuestas privadas para reutilizarlas después.
 */
export function useClienteApi() {
  const fetchApi = useRequestFetch() as unknown as FetchCliente
  const evento = import.meta.server ? useRequestEvent() : undefined

  if (evento) {
    setResponseHeader(evento, 'cache-control', 'no-store, private')
    setResponseHeader(evento, 'vary', 'Cookie')
  }

  async function solicitar<T>(ruta: string, opciones: OpcionesSolicitud = {}): Promise<T> {
    const encabezados = {
      accept: 'application/json',
      ...(opciones.body ? { 'content-type': 'application/json' } : {}),
      ...opciones.headers,
    }
    const parametros: Record<string, unknown> = {
      ...opciones,
      cache: 'no-store',
      headers: encabezados,
      onResponse({ response }: { response: Response }) {
        if (!evento) return
        for (const valor of response.headers.getSetCookie()) {
          appendResponseHeader(evento, 'set-cookie', valor)
        }
      },
    }

    try {
      return await fetchApi<T>(ruta, parametros)
    } catch (fallo) {
      const error = fallo as {
        statusCode?: number
        status?: number
        response?: { status?: number }
        data?: ErrorApiRespuesta
      }
      const estado = error.response?.status ?? error.statusCode ?? error.status ?? 0
      const codigo = typeof error.data?.codigo === 'string' ? error.data.codigo : null
      throw new ErrorClienteApi(
        estado || 503,
        codigo,
        mensajeSeguro(estado, codigo, opciones.method),
      )
    }
  }

  return {
    obtenerCsrf() {
      return solicitar<RespuestaCsrfCliente>('/api/v1/clientes/csrf')
    },
    registrar(datos: SolicitudRegistroCliente, tokenCsrf: string) {
      return solicitar<RespuestaRegistroCliente>('/api/v1/clientes/registro', {
        method: 'POST',
        body: datos,
        headers: { 'x-csrf-token': tokenCsrf },
      })
    },
    consultarSesion() {
      return solicitar<RespuestaSesionCliente>('/api/v1/clientes/sesion')
    },
    iniciarSesion(datos: SolicitudInicioSesionCliente, tokenCsrf: string) {
      return solicitar<RespuestaSesionCliente>('/api/v1/clientes/sesion', {
        method: 'POST',
        body: datos,
        headers: { 'x-csrf-token': tokenCsrf },
      })
    },
    cerrarSesion(tokenCsrf: string) {
      return solicitar<void>('/api/v1/clientes/sesion', {
        method: 'DELETE',
        headers: { 'x-csrf-token': tokenCsrf },
      })
    },
    consultarPortal(signal?: AbortSignal) {
      return solicitar<PortalCliente>('/api/v1/clientes/portal', { signal })
    },
    crearCheckoutMembresia(tokenCsrf: string, claveIdempotencia: string) {
      return solicitar<RespuestaCheckoutMembresia>('/api/v1/clientes/membresia/checkout', {
        method: 'POST',
        headers: { 'x-csrf-token': tokenCsrf, 'idempotency-key': claveIdempotencia },
      })
    },
    consultarCheckoutMembresia(intentoId: string, signal?: AbortSignal) {
      return solicitar<RespuestaEstadoCheckoutMembresia>(
        `/api/v1/clientes/membresia/checkout/${encodeURIComponent(intentoId)}`,
        { signal },
      )
    },
    cambiarContrasena(datos: SolicitudCambioContrasenaCliente, tokenCsrf: string) {
      return solicitar<void>('/api/v1/clientes/contrasena', {
        method: 'PATCH',
        body: datos,
        headers: { 'x-csrf-token': tokenCsrf },
      })
    },
  }
}
