import { consultarDetalleCliente } from '../../../utils/proxy-admin-clientes'

export default defineEventHandler((event) => consultarDetalleCliente(event))
