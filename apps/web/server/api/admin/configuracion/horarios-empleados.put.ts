import { cambiarHorariosEmpleados } from '../../../utils/proxy-admin-configuracion'

export default defineEventHandler((event) => cambiarHorariosEmpleados(event))
