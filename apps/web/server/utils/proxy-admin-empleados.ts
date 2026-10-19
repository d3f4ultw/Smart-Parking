import {
  createError,
  getCookie,
  getRequestHeader,
  getRequestURL,
  readBody,
  sendProxy,
  setResponseHeader,
  type H3Event,
} from 'h3'

const RUTA_API_EMPLEADOS = '/api/admin/empleados'
const CLAVE_IDEMPOTENCIA = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const MAXIMO_ID_BIGINT = BigInt('9223372036854775807')

interface SolicitudRegistrarEmpleado {
  nombres: string
  apellido_paterno: string
  apellido_materno: string | null
  turno_empleado_id: number
}

interface SolicitudCambiarEstadoEmpleado {
  esta_activo: boolean
  revision_esperada: number
}

function crearErrorSolicitud(statusCode: number, statusMessage: string): never {
  throw createError({ statusCode, statusMessage })
}

function esObjeto(valor: unknown): valor is Record<string, unknown> {
  return valor !== null && typeof valor === 'object' && !Array.isArray(valor)
}

function validarJson(event: H3Event): void {
  const contentType = getRequestHeader(event, 'content-type')
  if (
    contentType === undefined
    || !/^application\/json(?:\s*;|\s*$)/i.test(contentType)
  ) {
    crearErrorSolicitud(415, 'Se requiere una solicitud JSON')
  }
}

function encabezadosSesion(event: H3Event): Record<string, string> {
  const nombreCookie = useRuntimeConfig(event).sessionCookieName
  const cookieSesion = getCookie(event, nombreCookie)
  return cookieSesion === undefined
    ? {}
    : { cookie: `${nombreCookie}=${cookieSesion}` }
}

function obtenerUrlApi(event: H3Event, rutaApi: string): string {
  const apiBaseUrl = useRuntimeConfig(event).apiInternalBaseUrl.replace(/\/+$/, '')
  return apiBaseUrl + rutaApi
}

function validarNombre(valor: unknown): string | null {
  if (typeof valor !== 'string') {
    return null
  }

  const nombre = valor.trim()
  return nombre.length > 0 && nombre.length <= 100 ? nombre : null
}

function validarSolicitudRegistro(valor: unknown): SolicitudRegistrarEmpleado | null {
  if (!esObjeto(valor)) {
    return null
  }

  const camposPermitidos = new Set([
    'nombres',
    'apellido_paterno',
    'apellido_materno',
    'turno_empleado_id',
  ])
  if (Object.keys(valor).some((campo) => !camposPermitidos.has(campo))) {
    return null
  }

  const nombres = validarNombre(valor.nombres)
  const apellidoPaterno = validarNombre(valor.apellido_paterno)
  const turnoId = valor.turno_empleado_id
  if (
    nombres === null
    || apellidoPaterno === null
    || typeof turnoId !== 'number'
    || !Number.isSafeInteger(turnoId)
    || turnoId < 1
  ) {
    return null
  }

  let apellidoMaterno: string | null = null
  if (valor.apellido_materno !== undefined && valor.apellido_materno !== null) {
    if (typeof valor.apellido_materno !== 'string') {
      return null
    }
    const normalizado = valor.apellido_materno.trim()
    if (normalizado.length > 100) {
      return null
    }
    apellidoMaterno = normalizado || null
  }

  return {
    nombres,
    apellido_paterno: apellidoPaterno,
    apellido_materno: apellidoMaterno,
    turno_empleado_id: turnoId,
  }
}

function validarSolicitudEstado(valor: unknown): SolicitudCambiarEstadoEmpleado | null {
  if (!esObjeto(valor)) {
    return null
  }

  if (
    Object.keys(valor).length !== 2
    || !Object.hasOwn(valor, 'esta_activo')
    || !Object.hasOwn(valor, 'revision_esperada')
    || typeof valor.esta_activo !== 'boolean'
    || typeof valor.revision_esperada !== 'number'
    || !Number.isSafeInteger(valor.revision_esperada)
    || valor.revision_esperada < 1
  ) {
    return null
  }

  return {
    esta_activo: valor.esta_activo,
    revision_esperada: valor.revision_esperada,
  }
}

export function consultarEmpleados(event: H3Event) {
  setResponseHeader(event, 'cache-control', 'no-store')

  const parametros = getRequestURL(event).searchParams
  if (
    [...parametros.keys()].some((parametro) => parametro !== 'pagina')
    || parametros.getAll('pagina').length > 1
  ) {
    crearErrorSolicitud(422, 'La consulta de empleados no es válida')
  }

  const paginaTexto = parametros.get('pagina') ?? '1'
  if (!/^[1-9]\d*$/.test(paginaTexto)) {
    crearErrorSolicitud(422, 'La página debe ser un entero positivo')
  }
  const pagina = Number(paginaTexto)
  if (!Number.isSafeInteger(pagina)) {
    crearErrorSolicitud(422, 'La página debe ser un entero positivo')
  }

  return sendProxy(
    event,
    `${obtenerUrlApi(event, RUTA_API_EMPLEADOS)}?pagina=${pagina}`,
    {
      fetchOptions: {
        method: 'GET',
        headers: encabezadosSesion(event),
      },
    },
  )
}

export async function registrarEmpleado(event: H3Event) {
  setResponseHeader(event, 'cache-control', 'no-store')
  validarJson(event)

  const claveIdempotencia = getRequestHeader(event, 'idempotency-key')
  if (
    claveIdempotencia === undefined
    || !CLAVE_IDEMPOTENCIA.test(claveIdempotencia)
  ) {
    crearErrorSolicitud(422, 'Se requiere una clave de registro válida')
  }

  const solicitud = validarSolicitudRegistro(await readBody<unknown>(event))
  if (solicitud === null) {
    crearErrorSolicitud(422, 'La solicitud de empleado no es válida')
  }

  return sendProxy(event, obtenerUrlApi(event, RUTA_API_EMPLEADOS), {
    fetchOptions: {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'idempotency-key': claveIdempotencia.toLowerCase(),
        ...encabezadosSesion(event),
      },
      body: JSON.stringify(solicitud),
    },
  })
}

export async function cambiarEstadoEmpleado(event: H3Event, empleadoId: string | undefined) {
  setResponseHeader(event, 'cache-control', 'no-store')

  if (empleadoId === undefined || !/^[1-9]\d{0,18}$/.test(empleadoId)) {
    crearErrorSolicitud(400, 'El ID del empleado no es válido')
  }
  if (BigInt(empleadoId) > MAXIMO_ID_BIGINT) {
    crearErrorSolicitud(400, 'El ID del empleado no es válido')
  }

  validarJson(event)
  const solicitud = validarSolicitudEstado(await readBody<unknown>(event))
  if (solicitud === null) {
    crearErrorSolicitud(422, 'La solicitud de estado no es válida')
  }

  return sendProxy(
    event,
    `${obtenerUrlApi(event, `${RUTA_API_EMPLEADOS}/${empleadoId}/estado`)}`,
    {
      fetchOptions: {
        method: 'PATCH',
        headers: {
          'content-type': 'application/json',
          ...encabezadosSesion(event),
        },
        body: JSON.stringify(solicitud),
      },
    },
  )
}
