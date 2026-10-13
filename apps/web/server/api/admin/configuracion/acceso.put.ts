import { cambiarAccesoEstacionamiento } from '../../../utils/proxy-admin-configuracion'

export default defineEventHandler((event) =>
  cambiarAccesoEstacionamiento(event))
