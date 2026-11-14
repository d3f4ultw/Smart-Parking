import { appendResponseHeader, getRequestHeader, setResponseHeader } from 'h3'
import type {
  Empleado,
  EstadoEmpleado,
  PaginaEmpleados,
  ReciboRegistroEmpleado,
  RegistroEmpleado,
  RespuestaAccionEmpleadoOperador,
  RespuestaCambioCorreoEmpleadoOperador,
} from '~/types/empleado'

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

interface MetadatosRespuesta {
  etag: string | null
}

type FetchEmpleado = <T>(ruta: string, opciones: Record<string, unknown>) => Promise<T>

const MAXIMO_BIGINT = 9223372036854775807n
const FORMATO_IDENTIFICADOR = /^[1-9]\d{0,18}$/
const FORMATO_REVISION = /^(0|[1-9]\d{0,18})$/
const FORMATO_ETAG = /^"(0|[1-9]\d{0,18})"$/
const FORMATO_UUID = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i

/** Conserva el código de respuesta y el motivo del fallo junto con un mensaje
 * que la pantalla puede mostrar sin exponer información interna.
 */
export class ErrorEmpleadoApi extends Error {
  constructor(
    public readonly estado: number,
    public readonly codigo: string | null,
    mensaje: string,
  ) {
    super(mensaje)
    this.name = 'ErrorEmpleadoApi'
  }
}

function mensajeSeguro(estado: number, metodo?: string, codigo?: string | null) {
  if (codigo === 'CORREO_EN_USO') return 'Ese correo está reservado por otra cuenta.'
  if (codigo === 'OPERADOR_YA_VINCULADO')
    return 'Este empleado ya tiene una cuenta vinculada. Actualiza la lista de operadores.'
  if (codigo === 'EMPLEADO_REQUERIDO')
    return 'Vincula esta cuenta a un empleado antes de continuar.'
  if (codigo === 'CORREOS_DISTINTOS') {
    return 'Los correos no coinciden. Actualízalos explícitamente antes de vincular la cuenta.'
  }
  if (codigo === 'CONFIRMACION_CORREO_REQUERIDA') {
    return 'Confirma que quieres copiar el correo de la cuenta al empleado.'
  }
  if (estado === 400) return 'Revisa los datos e inténtalo de nuevo.'
  if (estado === 401) return 'Tu acceso venció. Inicia sesión de nuevo.'
  if (estado === 403) return 'No tienes permiso para completar esta acción.'
  if (estado === 404) return 'No encontramos al empleado. Actualiza la lista e inténtalo de nuevo.'
  if (estado === 409 || estado === 412) {
    return 'La información cambió. Actualiza la lista y vuelve a intentarlo.'
  }
  if (estado === 429) return 'Espera un momento y vuelve a intentarlo.'
  if ((metodo === 'POST' || metodo === 'PATCH') && (estado === 0 || estado >= 500)) {
    return 'No sabemos si se guardó el cambio. Revisa la lista antes de intentarlo de nuevo.'
  }
  if (estado === 0 || estado >= 500) {
    return 'No pudimos cargar la lista. Revisa tu conexión e inténtalo de nuevo.'
  }
  return 'No pudimos completar el cambio. Revisa la información e inténtalo de nuevo.'
}

function validarIdTexto(idTexto: string) {
  if (!FORMATO_IDENTIFICADOR.test(idTexto) || BigInt(idTexto) > MAXIMO_BIGINT) {
    throw new ErrorEmpleadoApi(400, 'IDENTIFICADOR_NO_VALIDO', 'El empleado indicado no es válido.')
  }
}

function validarIfMatch(etag: string) {
  const revision = FORMATO_ETAG.exec(etag)?.[1]
  if (!revision || BigInt(revision) > MAXIMO_BIGINT) {
    throw new ErrorEmpleadoApi(
      400,
      'ETAG_NO_VALIDO',
      'Actualiza la lista antes de completar el cambio.',
    )
  }
}

function rutaEmpleado(idTexto: string, sufijo = '') {
  validarIdTexto(idTexto)
  return '/api/v1/empleados/' + idTexto + sufijo
}

/** Reúne las consultas y cambios de empleados; al enviar un cambio incluye
 * el número de revisión leído para que el servidor lo acepte solo si sigue vigente.
 */
export function useClienteEmpleados() {
  const fetchApi = useRequestFetch() as unknown as FetchEmpleado
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
        cache: 'no-store',
        headers,
        onResponse({ response }: { response: Response }) {
          if (metadatos) metadatos.etag = response.headers.get('etag')
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
      throw new ErrorEmpleadoApi(
        estadoHttp,
        codigo,
        mensajeSeguro(estadoHttp, opciones.method, codigo),
      )
    }
  }

/** Comprueba que el identificador y el número de revisión coincidan en los datos
 * del empleado y en la respuesta del servidor antes de mostrar el detalle.
 */
  async function detalle(idTexto: string, signal?: AbortSignal) {
    const metadatos: MetadatosRespuesta = { etag: null }
    const datos = await solicitar<Empleado>(
      rutaEmpleado(idTexto),
      { method: 'GET', signal },
      metadatos,
    )
    const etag = metadatos.etag
    if (!etag || !FORMATO_ETAG.test(etag)) {
      throw new ErrorEmpleadoApi(
        502,
        'ETAG_NO_VALIDO',
        'No pudimos cargar al empleado. Actualiza la lista e inténtalo de nuevo.',
      )
    }
    validarIfMatch(etag)
    const revisionEtag = FORMATO_ETAG.exec(etag)?.[1]
    if (
      datos.idTexto !== idTexto ||
      !revisionEtag ||
      datos.revisionTexto !== revisionEtag ||
      !FORMATO_REVISION.test(datos.revisionTexto) ||
      BigInt(datos.revisionTexto) > MAXIMO_BIGINT
    ) {
      throw new ErrorEmpleadoApi(
        502,
        'RESPUESTA_NO_VALIDA',
        'No pudimos validar la información del empleado.',
      )
    }
    return { datos, etag }
  }

  function solicitarAccion(
    idTexto: string,
    sufijo: string,
    etag: string,
    clave: string,
    csrf: string,
    body: Record<string, unknown> = {},
  ) {
    validarIfMatch(etag)
    return solicitar<RespuestaAccionEmpleadoOperador>(rutaEmpleado(idTexto, sufijo), {
      method: 'POST',
      body,
      headers: {
        'content-type': 'application/json',
        'if-match': etag,
        'idempotency-key': clave,
        'x-csrf-token': csrf,
      },
    })
  }

  return {
    listar(pagina: string | string[], signal?: AbortSignal) {
      return solicitar<PaginaEmpleados>('/api/v1/empleados', {
        method: 'GET',
        query: { pagina },
        signal,
      })
    },
    listarElegiblesOperador(pagina: string, busqueda: string, signal?: AbortSignal) {
      const query: Record<string, string> = {
        pagina,
        soloElegiblesOperador: 'true',
      }
      if (busqueda.trim()) query.busqueda = busqueda.trim()
      return solicitar<PaginaEmpleados>('/api/v1/empleados', {
        method: 'GET',
        query,
        signal,
      })
    },
    detalle,
    registrar(datos: RegistroEmpleado, clave: string, csrf: string) {
      return solicitar<ReciboRegistroEmpleado>('/api/v1/empleados', {
        method: 'POST',
        body: datos,
        headers: {
          'content-type': 'application/json',
          'idempotency-key': clave,
          'x-csrf-token': csrf,
        },
      })
    },
    cambiarEstado(idTexto: string, estado: EstadoEmpleado, etag: string, csrf: string) {
      validarIfMatch(etag)
      return solicitar<Empleado>(rutaEmpleado(idTexto, '/estado'), {
        method: 'PATCH',
        body: { estado },
        headers: {
          'content-type': 'application/json',
          'x-csrf-token': csrf,
          'if-match': etag,
        },
      })
    },
    cambiarCorreo(
      idTexto: string,
      correo: string | null,
      etag: string,
      clave: string,
      csrf: string,
    ) {
      validarIfMatch(etag)
      return solicitar<RespuestaCambioCorreoEmpleadoOperador>(rutaEmpleado(idTexto, '/correo'), {
        method: 'PATCH',
        body: { correo },
        headers: {
          'content-type': 'application/json',
          'if-match': etag,
          'idempotency-key': clave,
          'x-csrf-token': csrf,
        },
      })
    },
    promocionar(idTexto: string, etag: string, clave: string, csrf: string, correo?: string) {
      return solicitarAccion(
        idTexto,
        '/operador/promocion',
        etag,
        clave,
        csrf,
        correo === undefined ? {} : { correo },
      )
    },
    desactivarAcceso(idTexto: string, etag: string, clave: string, csrf: string) {
      return solicitarAccion(idTexto, '/operador/desactivacion', etag, clave, csrf)
    },
    vincular(
      idTexto: string,
      operadorId: string,
      revisionOperador: string,
      copiarCorreoOperador: boolean,
      etag: string,
      clave: string,
      csrf: string,
    ) {
      if (
        !FORMATO_UUID.test(operadorId) ||
        !FORMATO_REVISION.test(revisionOperador) ||
        BigInt(revisionOperador) > MAXIMO_BIGINT
      ) {
        throw new ErrorEmpleadoApi(400, 'VINCULO_NO_VALIDO', 'Selecciona una cuenta válida.')
      }
      return solicitarAccion(idTexto, '/operador/vinculacion', etag, clave, csrf, {
        operadorId,
        revisionOperador,
        copiarCorreoOperador,
      })
    },
  }
}
