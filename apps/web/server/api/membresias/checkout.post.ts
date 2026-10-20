import { iniciarCheckoutMembresia } from '../../utils/proxy-membresias'

export default defineEventHandler((event) => iniciarCheckoutMembresia(event))
