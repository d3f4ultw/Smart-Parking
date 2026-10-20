import {
  createError,
  getCookie,
  getRequestURL,
  getRouterParam,
  setResponseHeader,
  sendProxy,
  type H3Event,
} from 'h3'

const RUTA_API_CLIENTES = '/api/admin/clientes'
const CODIGO_CLIENTE = /^CLI-[0-9]{4,}$/

function obtenerUrlApi(event: H3Event, ruta: string): string {
  const base = useRuntimeConfig(event).apiInternalBaseUrl.replace(/\/+$/, '')
  return base + ruta
}

function encabezadosSesion(event: H3Event): Record<string, string> {
  const nombreCookie = useRuntimeConfig(event).sessionCookieName
  const cookie = getCookie(event, nombreCookie)
  return cookie === undefined ? {} : { cookie: `${nombreCookie}=${cookie}` }
}

function errorSolicitud(statusCode: number, statusMessage: string): never {
  throw createError({ statusCode, statusMessage })
}

export function consultarClientes(event: H3Event) {
  setResponseHeader(event, 'cache-control', 'no-store')
  const parametros = getRequestURL(event).searchParams
  if (
    [...parametros.keys()].some((parametro) => parametro !== 'pagina')
    || parametros.getAll('pagina').length > 1
  ) {
    errorSolicitud(422, 'La consulta de clientes no es válida')
  }
  const paginaTexto = parametros.get('pagina') ?? '1'
  if (!/^[1-9]\d*$/.test(paginaTexto) || !Number.isSafeInteger(Number(paginaTexto))) {
    errorSolicitud(422, 'La página debe ser un entero positivo')
  }
  return sendProxy(
    event,
    `${obtenerUrlApi(event, RUTA_API_CLIENTES)}?pagina=${Number(paginaTexto)}`,
    { fetchOptions: { method: 'GET', headers: encabezadosSesion(event) } },
  )
}

export function consultarDetalleCliente(event: H3Event) {
  setResponseHeader(event, 'cache-control', 'no-store')
  const codigo = getRouterParam(event, 'codigo')
  if (codigo === undefined || !CODIGO_CLIENTE.test(codigo)) {
    errorSolicitud(404, 'El cliente no está disponible')
  }
  return sendProxy(
    event,
    obtenerUrlApi(event, `${RUTA_API_CLIENTES}/${encodeURIComponent(codigo)}`),
    { fetchOptions: { method: 'GET', headers: encabezadosSesion(event) } },
  )
}
