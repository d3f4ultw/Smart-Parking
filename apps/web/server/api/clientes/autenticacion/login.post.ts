import { createError } from 'h3'

import {
  exigirSinParametros,
  leerObjetoJsonCliente,
  solicitarApiCliente,
} from '../../../utils/proxy-clientes'

export default defineEventHandler(async (event) => {
  exigirSinParametros(event)
  const cuerpo = await leerObjetoJsonCliente(event, ['correo', 'contrasena'])
  if (
    cuerpo.correo!.trim().length === 0
    || cuerpo.correo!.length > 320
    || cuerpo.contrasena!.length === 0
    || cuerpo.contrasena!.length > 128
  ) {
    throw createError({ statusCode: 422, statusMessage: 'Revisa el correo y la contraseña.' })
  }

  await solicitarApiCliente(event, {
    ruta: '/api/clientes/autenticacion/login',
    metodo: 'POST',
    exigirOrigen: true,
    cuerpo,
  })
  return { estado: 'credenciales_validas' as const }
})
