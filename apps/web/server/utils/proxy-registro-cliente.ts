import { createHash } from 'node:crypto'
import { isIP } from 'node:net'
import {
  createError,
  getRequestHeader,
  getRequestURL,
  setResponseHeader,
  setResponseStatus,
  type H3Event,
} from 'h3'

const RUTA_API_REGISTRO_CLIENTE = '/api/clientes/registro'
const TAMANO_MAXIMO_REGISTRO = 8 * 1024
const CAMPOS_REQUERIDOS = ['nombre', 'apellido_paterno', 'correo', 'contrasena']
const CAMPOS_PERMITIDOS = new Set([
  ...CAMPOS_REQUERIDOS,
  'apellido_materno',
])

type SolicitudRegistroCliente = {
  nombre: string
  apellido_paterno: string
  apellido_materno?: string | null
  correo: string
  contrasena: string
}

function errorSolicitud(statusCode: number, statusMessage: string): never {
  throw createError({ statusCode, statusMessage })
}

function exigirOrigenMismoSitio(event: H3Event): void {
  const origenRecibido = getRequestHeader(event, 'origin')
  const origenEsperado = useRuntimeConfig(event).public.managementOrigin
  try {
    if (
      origenRecibido === undefined
      || new URL(origenRecibido).origin !== new URL(origenEsperado).origin
    ) {
      errorSolicitud(403, 'La solicitud de registro no es válida')
    }
  } catch {
    errorSolicitud(403, 'La solicitud de registro no es válida')
  }
}

function validarCuerpo(valor: unknown): SolicitudRegistroCliente {
  if (valor === null || typeof valor !== 'object' || Array.isArray(valor)) {
    errorSolicitud(422, 'Solicitud invalida')
  }

  const registro = valor as Record<string, unknown>
  const claves = Object.keys(registro)
  if (
    claves.some((clave) => !CAMPOS_PERMITIDOS.has(clave))
    || CAMPOS_REQUERIDOS.some((clave) => !Object.hasOwn(registro, clave))
  ) {
    errorSolicitud(422, 'Solicitud invalida')
  }

  for (const campo of CAMPOS_REQUERIDOS) {
    if (typeof registro[campo] !== 'string') {
      errorSolicitud(422, 'Solicitud invalida')
    }
  }
  if (
    Object.hasOwn(registro, 'apellido_materno')
    && registro.apellido_materno !== null
    && typeof registro.apellido_materno !== 'string'
  ) {
    errorSolicitud(422, 'Solicitud invalida')
  }

  return {
    nombre: registro.nombre as string,
    apellido_paterno: registro.apellido_paterno as string,
    ...(Object.hasOwn(registro, 'apellido_materno')
      ? { apellido_materno: registro.apellido_materno as string | null }
      : {}),
    correo: registro.correo as string,
    contrasena: registro.contrasena as string,
  }
}

function huellaOrigenCliente(event: H3Event): string {
  const ipCloudflare = getRequestHeader(event, 'cf-connecting-ip')?.trim()
  const ipSocket = event.node.req.socket.remoteAddress
  const origen = ipCloudflare && isIP(ipCloudflare) !== 0
    ? ipCloudflare
    : ipSocket ?? 'desconocido'
  return createHash('sha256').update(`registro-cliente:${origen}`).digest('hex')
}

async function leerCuerpoLimitado(event: H3Event): Promise<string> {
  const longitudDeclarada = getRequestHeader(event, 'content-length')
  if (longitudDeclarada !== undefined) {
    if (!/^\d+$/.test(longitudDeclarada)) {
      errorSolicitud(400, 'Solicitud invalida')
    }
    if (Number(longitudDeclarada) > TAMANO_MAXIMO_REGISTRO) {
      errorSolicitud(413, 'La solicitud supera el tamaño permitido')
    }
  }

  const partes: Buffer[] = []
  let bytesRecibidos = 0
  for await (const parte of event.node.req) {
    const bytes = Buffer.isBuffer(parte) ? parte : Buffer.from(parte)
    bytesRecibidos += bytes.byteLength
    if (bytesRecibidos > TAMANO_MAXIMO_REGISTRO) {
      errorSolicitud(413, 'La solicitud supera el tamaño permitido')
    }
    partes.push(bytes)
  }
  return Buffer.concat(partes, bytesRecibidos).toString('utf8')
}

function responderErrorUpstream(event: H3Event, statusCode: number): never {
  if (statusCode === 429) {
    errorSolicitud(429, 'Se alcanzó el límite de solicitudes. Inténtalo más tarde.')
  }
  if (statusCode === 413) {
    errorSolicitud(413, 'La solicitud supera el tamaño permitido')
  }
  if (statusCode === 415) {
    errorSolicitud(415, 'Se requiere una solicitud JSON')
  }
  if (statusCode === 422) {
    errorSolicitud(422, 'Revisa los datos del formulario')
  }
  setResponseHeader(event, 'cache-control', 'no-store')
  errorSolicitud(503, 'El registro no está disponible temporalmente')
}

export async function registrarCliente(event: H3Event) {
  setResponseHeader(event, 'cache-control', 'no-store')
  if (getRequestURL(event).search) {
    errorSolicitud(422, 'Solicitud invalida')
  }
  exigirOrigenMismoSitio(event)

  const contentType = getRequestHeader(event, 'content-type')
  if (
    contentType === undefined
    || !/^application\/json(?:\s*;|\s*$)/i.test(contentType)
  ) {
    errorSolicitud(415, 'Se requiere una solicitud JSON')
  }

  const cuerpo = await leerCuerpoLimitado(event)
  let datos: unknown
  try {
    datos = JSON.parse(cuerpo) as unknown
  } catch {
    errorSolicitud(422, 'Solicitud invalida')
  }
  const solicitud = validarCuerpo(datos)
  const config = useRuntimeConfig(event)
  let respuesta: globalThis.Response
  try {
    respuesta = await fetch(
      `${config.apiInternalBaseUrl.replace(/\/+$/, '')}${RUTA_API_REGISTRO_CLIENTE}`,
      {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-sp-registration-origin': huellaOrigenCliente(event),
        },
        body: JSON.stringify(solicitud),
        redirect: 'error',
      },
    )
  } catch {
    errorSolicitud(503, 'El registro no está disponible temporalmente')
  }

  await respuesta.body?.cancel().catch(() => undefined)
  if (respuesta.status !== 202) {
    responderErrorUpstream(event, respuesta.status)
  }

  setResponseStatus(event, 202)
  return { estado: 'solicitud_recibida' as const }
}
