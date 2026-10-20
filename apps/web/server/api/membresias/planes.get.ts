import { consultarPlanesMembresia } from '../../utils/proxy-membresias'

export default defineEventHandler((event) => consultarPlanesMembresia(event))
