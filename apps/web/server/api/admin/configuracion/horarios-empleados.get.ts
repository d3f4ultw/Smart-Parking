import { consultarHorariosEmpleados } from '../../../utils/proxy-admin-configuracion'

export default defineEventHandler((event) => consultarHorariosEmpleados(event))
