import { proxyGestionPropietario } from '../../utils/proxy-gestion-propietario'

export default defineEventHandler((event) => proxyGestionPropietario(event, 'estado'))
