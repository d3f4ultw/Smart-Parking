import { registrarCliente } from '../../utils/proxy-registro-cliente'

export default defineEventHandler((event) => registrarCliente(event))
