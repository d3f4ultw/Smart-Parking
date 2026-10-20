import { consultarClientes } from '../../utils/proxy-admin-clientes'

export default defineEventHandler((event) => consultarClientes(event))
