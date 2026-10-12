import { proxyActivacionPropietario } from '../../../utils/proxy-activacion-propietario'

export default defineEventHandler((event) => proxyActivacionPropietario(event, 'completar'))
