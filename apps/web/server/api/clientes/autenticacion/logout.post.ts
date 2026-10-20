import {
  exigirSinParametros,
  solicitarApiCliente,
} from '../../../utils/proxy-clientes'

export default defineEventHandler(async (event) => {
  exigirSinParametros(event)
  await solicitarApiCliente(event, {
    ruta: '/api/clientes/autenticacion/logout',
    metodo: 'POST',
    incluirSesion: true,
    exigirOrigen: true,
  })
  return { estado: 'sesion_cerrada' as const }
})
