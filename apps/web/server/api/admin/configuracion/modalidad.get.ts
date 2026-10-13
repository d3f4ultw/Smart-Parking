import { consultarConfiguracionEstacionamiento } from '../../../utils/proxy-admin-configuracion'

export default defineEventHandler((event) =>
  consultarConfiguracionEstacionamiento(event))
