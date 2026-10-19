import { getRouterParam } from 'h3'

import { cambiarEstadoEmpleado } from '../../../../utils/proxy-admin-empleados'

export default defineEventHandler((event) =>
  cambiarEstadoEmpleado(event, getRouterParam(event, 'id')),
)
