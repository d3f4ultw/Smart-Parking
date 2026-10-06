import { getRequestURL } from 'h3'

import { proxyAdminOperadores } from '../../utils/proxy-admin-operadores'

export default defineEventHandler((event) => {
  const parametros = getRequestURL(event).searchParams
  return proxyAdminOperadores(
    event,
    '',
    parametros.get('pagina'),
    parametros.get('buscar'),
  )
})
