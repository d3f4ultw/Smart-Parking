import { consultarEmpleados } from '../../utils/proxy-admin-empleados'

export default defineEventHandler((event) => consultarEmpleados(event))
