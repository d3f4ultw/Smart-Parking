import { createError } from 'h3'

import {
  exigirSinParametros,
  solicitarApiCliente,
} from '../../../utils/proxy-clientes'

function validarRespuestaSesion(valor: unknown) {
  if (valor === null || typeof valor !== 'object' || Array.isArray(valor)) {
    throw createError({ statusCode: 502, statusMessage: 'La respuesta de sesión no es válida.' })
  }

  const respuesta = valor as Record<string, unknown>
  const cliente = respuesta.cliente
  if (
    respuesta.autenticado !== true
    || cliente === null
    || typeof cliente !== 'object'
    || Array.isArray(cliente)
  ) {
    throw createError({ statusCode: 502, statusMessage: 'La respuesta de sesión no es válida.' })
  }

  const identidad = cliente as Record<string, unknown>
  if (
    typeof identidad.nombre !== 'string'
    || typeof identidad.apellido_paterno !== 'string'
    || (identidad.apellido_materno !== null && typeof identidad.apellido_materno !== 'string')
    || typeof identidad.correo !== 'string'
    || typeof identidad.correo_verificado !== 'boolean'
  ) {
    throw createError({ statusCode: 502, statusMessage: 'La respuesta de sesión no es válida.' })
  }

  return {
    autenticado: true as const,
    cliente: {
      nombre: identidad.nombre,
      apellido_paterno: identidad.apellido_paterno,
      apellido_materno: identidad.apellido_materno,
      correo: identidad.correo,
      correo_verificado: identidad.correo_verificado,
    },
  }
}

export default defineEventHandler(async (event) => {
  exigirSinParametros(event, 'La consulta de sesión no es válida.')
  const respuesta = await solicitarApiCliente(event, {
    ruta: '/api/clientes/autenticacion/me',
    metodo: 'GET',
    incluirSesion: true,
  })
  return validarRespuestaSesion(respuesta)
})
