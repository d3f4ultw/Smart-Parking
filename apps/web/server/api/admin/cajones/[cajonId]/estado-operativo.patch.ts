import { proxyCambiarEstadoOperativoCajon } from '../../../../utils/proxy-admin-cajones'

export default defineEventHandler((event) =>
  proxyCambiarEstadoOperativoCajon(event),
)
