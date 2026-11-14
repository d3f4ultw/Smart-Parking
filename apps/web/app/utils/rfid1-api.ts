import { appendResponseHeader, getRequestHeader, setResponseHeader } from 'h3'
import type {
  CancelacionTarjetaRfid1,
  CapturaRfid1,
  CandidatoPersonaRfid1,
  ConfirmacionRfid1,
  FiltroTipoEntidadRfid1,
  PaginaTarjetasRfid1,
  RespuestaEstadoConexionRfid1,
  RespuestaInicioCapturaRfid1,
  RespuestaModalidadRfid1,
  SolicitudCapturaRfid1,
  TarjetaRfid1,
  VistaPreviaRfid1,
} from '~/types/rfid1'

interface ErrorApiRespuesta {
  codigo?: string
}

interface OpcionesSolicitud {
  method?: 'GET' | 'POST' | 'DELETE'
  headers?: Record<string, string>
  body?: SolicitudCapturaRfid1 | undefined
  signal?: AbortSignal
  retry?: number
}

type FetchRfid1 = <T>(ruta: string, opciones: Record<string, unknown>) => Promise<T>

const RUTA_CAPTURAS = '/api/v1/rfid-1/capturas'
const RUTA_TARJETAS = '/api/v1/tarjetas-rfid'
const RUTA_MODALIDAD = `${RUTA_TARJETAS}/modalidad`
const RUTA_ESTADO_CONEXION = '/api/v1/rfid-1/estado-conexion'
const FORMATO_CAPTURA = /^[0-9a-f]{32}$/
const FORMATO_ASOCIACION = /^[1-9]\d*$/
const ESTADOS_TARJETA = new Set(['TODAS', 'ACTIVA', 'CANCELADA'])

/** Conserva el código de respuesta y el motivo del fallo con un mensaje seguro,
 * para que la pantalla decida si vuelve a consultar o cierra la lectura.
 */
export class ErrorRfid1Api extends Error {
  constructor(
    public readonly estado: number,
    public readonly codigo: string | null,
    mensaje: string,
  ) {
    super(mensaje)
    this.name = 'ErrorRfid1Api'
  }
}

function mensajeSeguro(estado: number, metodo?: string, codigo?: string) {
  if (codigo === 'PERSONA_CON_TARJETA') return 'Esta persona ya tiene una tarjeta asociada.'
  if (
    ['TARJETA_ASOCIADA', 'TARJETA_YA_ASOCIADA', 'UID_DUPLICADO', 'UID_TARJETA_DUPLICADA'].includes(
      codigo ?? '',
    )
  ) {
    return 'Esta tarjeta ya está asociada a otra persona.'
  }
  if (codigo === 'CAPTURA_EN_CURSO') {
    return 'Ya hay una captura en curso. Espera a que termine antes de iniciar otra.'
  }
  if (codigo === 'PERSONA_NO_ENCONTRADA') return 'No encontramos a la persona indicada.'
  if (estado === 400) return 'Revisa los datos e inténtalo de nuevo.'
  if (estado === 401) return 'Tu acceso venció. Inicia sesión de nuevo.'
  if (estado === 403) return 'Tu acceso ya no permite completar esta acción.'
  if (estado === 404) return 'No encontramos la captura indicada.'
  if (estado === 409 || estado === 410) {
    return 'La captura cambió o venció. Consulta su estado e inténtalo de nuevo.'
  }
  if (estado === 0 || estado >= 500) {
    return metodo === 'POST' || metodo === 'DELETE'
      ? 'No sabemos si la solicitud se completó. Consulta el estado antes de intentarlo de nuevo.'
      : 'No pudimos consultar la captura. Revisa tu conexión e inténtalo de nuevo.'
  }
  return 'No pudimos completar la solicitud de captura.'
}

function validarCapturaId(capturaId: string) {
  if (!FORMATO_CAPTURA.test(capturaId)) {
    throw new ErrorRfid1Api(400, 'CAPTURA_ID_NO_VALIDO', 'La captura indicada no es válida.')
  }
}

function validarAsociacionId(asociacionId: number) {
  if (
    !Number.isSafeInteger(asociacionId) ||
    asociacionId < 1 ||
    !FORMATO_ASOCIACION.test(String(asociacionId))
  ) {
    throw new ErrorRfid1Api(400, 'ASOCIACION_ID_NO_VALIDO', 'La tarjeta indicada no es válida.')
  }
}

function contieneControl(valor: string) {
  return [...valor].some((caracter) => {
    const codigo = caracter.codePointAt(0) ?? 0
    return codigo <= 0x1f || codigo === 0x7f
  })
}

function exigirPeticionDeCliente() {
  if (import.meta.server) {
    throw new ErrorRfid1Api(
      0,
      'PETICION_NO_DISPONIBLE',
      'Consulta la información después de abrir la página.',
    )
  }
}

/** Reúne las consultas de personas, tarjetas y lecturas RFID1;
 * comprueba los identificadores y pasa la sesión correcta a cada solicitud.
 */
export function useClienteRfid1() {
  const fetchApi = useRequestFetch() as unknown as FetchRfid1
  const evento = import.meta.server ? useRequestEvent() : undefined
  const cookie = evento ? getRequestHeader(evento, 'cookie') : undefined

  if (evento) {
    setResponseHeader(evento, 'cache-control', 'no-store, private')
    setResponseHeader(evento, 'vary', 'Cookie')
  }

  async function solicitar<T>(ruta: string, opciones: OpcionesSolicitud = {}): Promise<T> {
    const headers = {
      accept: 'application/json',
      ...(cookie ? { cookie } : {}),
      ...opciones.headers,
    }
    try {
      const parametros: Record<string, unknown> = {
        ...opciones,
        cache: 'no-store',
        headers,
        onResponse({ response }: { response: Response }) {
          if (!evento) return
          for (const valor of response.headers.getSetCookie()) {
            appendResponseHeader(evento, 'set-cookie', valor)
          }
        },
      }
      return await fetchApi<T>(ruta, parametros)
    } catch (fallo) {
      const error = fallo as {
        statusCode?: number
        status?: number
        response?: { status?: number }
        data?: ErrorApiRespuesta
      }
      const estadoHttp = error.response?.status ?? error.statusCode ?? error.status ?? 503
      const codigo = error.data?.codigo ?? null
      throw new ErrorRfid1Api(
        estadoHttp,
        codigo,
        mensajeSeguro(estadoHttp, opciones.method, codigo ?? undefined),
      )
    }
  }

  return {
    consultarModalidad(signal?: AbortSignal) {
      exigirPeticionDeCliente()
      return solicitar<RespuestaModalidadRfid1>(RUTA_MODALIDAD, { method: 'GET', signal })
    },
    buscarPersonas(tipoEntidad: FiltroTipoEntidadRfid1, busqueda: string, signal?: AbortSignal) {
      const consulta = new URLSearchParams({ tipoEntidad, busqueda: busqueda.trim() })
      return solicitar<CandidatoPersonaRfid1[]>(`${RUTA_TARJETAS}/personas?${consulta}`, {
        method: 'GET',
        signal,
      })
    },
    listarTarjetas(
      tipoEntidad: FiltroTipoEntidadRfid1,
      estado: 'TODAS' | 'ACTIVA' | 'CANCELADA',
      pagina: number,
      busqueda: string,
      signal?: AbortSignal,
    ) {
      exigirPeticionDeCliente()
      if (!ESTADOS_TARJETA.has(estado) || !Number.isSafeInteger(pagina) || pagina < 1) {
        throw new ErrorRfid1Api(
          400,
          'CONSULTA_NO_VALIDA',
          'Los filtros del directorio no son válidos.',
        )
      }
      const consulta = new URLSearchParams({ tipoEntidad, estado, pagina: String(pagina) })
      if (busqueda.trim()) consulta.set('busqueda', busqueda.trim())
      return solicitar<PaginaTarjetasRfid1>(`${RUTA_TARJETAS}?${consulta}`, {
        method: 'GET',
        retry: 0,
        signal,
      })
    },
    consultarTarjeta(asociacionId: number, signal?: AbortSignal) {
      exigirPeticionDeCliente()
      validarAsociacionId(asociacionId)
      return solicitar<TarjetaRfid1>(`${RUTA_TARJETAS}/${asociacionId}`, { method: 'GET', signal })
    },
    cancelarTarjeta(asociacionId: number, csrf: string) {
      exigirPeticionDeCliente()
      validarAsociacionId(asociacionId)
      return solicitar<CancelacionTarjetaRfid1>(`${RUTA_TARJETAS}/${asociacionId}/cancelacion`, {
        method: 'POST',
        headers: { 'x-csrf-token': csrf },
      })
    },
    iniciar(datos: SolicitudCapturaRfid1, clave: string, csrf: string) {
      exigirPeticionDeCliente()
      return solicitar<RespuestaInicioCapturaRfid1>(RUTA_CAPTURAS, {
        method: 'POST',
        body: datos,
        headers: {
          'content-type': 'application/json',
          'idempotency-key': clave,
          'x-csrf-token': csrf,
        },
      })
    },
    consultarActiva(signal?: AbortSignal) {
      return solicitar<CapturaRfid1 | null>(`${RUTA_CAPTURAS}/activa`, {
        method: 'GET',
        signal,
      }).then((captura) => captura ?? null)
    },
    consultarEstadoConexion(signal?: AbortSignal) {
      exigirPeticionDeCliente()
      return solicitar<RespuestaEstadoConexionRfid1>(RUTA_ESTADO_CONEXION, {
        method: 'GET',
        signal,
      })
    },
    consultar(capturaId: string, signal?: AbortSignal) {
      validarCapturaId(capturaId)
      return solicitar<CapturaRfid1>(`${RUTA_CAPTURAS}/${capturaId}`, { method: 'GET', signal })
    },
    async cancelar(capturaId: string, csrf: string): Promise<void> {
      exigirPeticionDeCliente()
      validarCapturaId(capturaId)
      await solicitar<null>(`${RUTA_CAPTURAS}/${capturaId}`, {
        method: 'DELETE',
        headers: { 'x-csrf-token': csrf },
      })
    },
    consultarVistaPrevia(capturaId: string, signal?: AbortSignal) {
      exigirPeticionDeCliente()
      validarCapturaId(capturaId)
      return solicitar<VistaPreviaRfid1>(`${RUTA_CAPTURAS}/${capturaId}/vista-previa`, {
        method: 'GET',
        signal,
      })
    },
    confirmar(capturaId: string, claveIdempotencia: string, csrf: string) {
      exigirPeticionDeCliente()
      validarCapturaId(capturaId)
      if (
        claveIdempotencia.length < 16 ||
        claveIdempotencia.length > 200 ||
        contieneControl(claveIdempotencia)
      ) {
        throw new ErrorRfid1Api(
          400,
          'CLAVE_IDEMPOTENCIA_NO_VALIDA',
          'No pudimos confirmar la tarjeta.',
        )
      }
      return solicitar<ConfirmacionRfid1>(`${RUTA_CAPTURAS}/${capturaId}/confirmacion`, {
        method: 'POST',
        headers: {
          'x-csrf-token': csrf,
          'idempotency-key': claveIdempotencia,
        },
      })
    },
  }
}
