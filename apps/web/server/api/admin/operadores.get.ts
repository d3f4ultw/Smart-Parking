import { getRequestURL } from 'h3'

import { proxyAdminOperadores } from '../../utils/proxy-admin-operadores'

export default defineEventHandler((event) => {
  const pagina = getRequestURL(event).searchParams.get('pagina')
  return proxyAdminOperadores(event, '', pagina)
})
