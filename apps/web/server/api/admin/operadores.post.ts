import { proxyAdminOperadores } from '../../utils/proxy-admin-operadores'

export default defineEventHandler((event) => {
  return proxyAdminOperadores(event)
})
