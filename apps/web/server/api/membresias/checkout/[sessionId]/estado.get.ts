import { consultarEstadoCheckout } from '../../../../utils/proxy-membresias'

export default defineEventHandler((event) => consultarEstadoCheckout(event))
