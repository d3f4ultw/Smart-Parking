import { getRouterParam } from 'h3'

import { proxyAdminOperadores } from '../../../../utils/proxy-admin-operadores'

export default defineEventHandler((event) => {
  const operadorId = getRouterParam(event, 'id')
  if (!operadorId) {
    throw createError({ statusCode: 404, statusMessage: 'Operador no encontrado' })
  }
  return proxyAdminOperadores(
    event,
    `/${encodeURIComponent(operadorId)}/desactivar`,
  )
})
