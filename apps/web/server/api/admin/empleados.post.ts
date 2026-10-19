import { registrarEmpleado } from '../../utils/proxy-admin-empleados'

export default defineEventHandler((event) => registrarEmpleado(event))
