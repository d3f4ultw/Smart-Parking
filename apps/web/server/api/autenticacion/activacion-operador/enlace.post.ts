import { proxyActivacionOperador } from '../../../utils/proxy-activacion-operador'

export default defineEventHandler((event) => {
  return proxyActivacionOperador(event, 'enlace')
})
