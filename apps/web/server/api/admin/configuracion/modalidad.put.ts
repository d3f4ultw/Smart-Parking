import { cambiarConfiguracionEstacionamiento } from '../../../utils/proxy-admin-configuracion'

export default defineEventHandler((event) =>
  cambiarConfiguracionEstacionamiento(event))
