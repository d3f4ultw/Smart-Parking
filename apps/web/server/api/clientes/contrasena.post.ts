import { createError } from 'h3'

import {
  exigirSinParametros,
  leerObjetoJsonCliente,
  solicitarApiCliente,
} from '../../utils/proxy-clientes'

export default defineEventHandler(async (event) => {
  exigirSinParametros(event)
  const cuerpo = await leerObjetoJsonCliente(event, [
    'contrasena_actual',
    'contrasena_nueva',
  ])
  if (
    cuerpo.contrasena_actual!.length === 0
    || cuerpo.contrasena_actual!.length > 128
    || cuerpo.contrasena_nueva!.length === 0
    || cuerpo.contrasena_nueva!.length > 128
  ) {
    throw createError({ statusCode: 422, statusMessage: 'Revisa los datos enviados.' })
  }

  await solicitarApiCliente(event, {
    ruta: '/api/clientes/contrasena',
    metodo: 'POST',
    incluirSesion: true,
    exigirOrigen: true,
    cuerpo: {
      contrasena_actual: cuerpo.contrasena_actual!,
      contrasena_nueva: cuerpo.contrasena_nueva!,
      confirmacion_contrasena_nueva: cuerpo.contrasena_nueva!,
    },
  })
  return { estado: 'contrasena_actualizada' as const }
})
