import { proxyEventos } from '../utils/eventos'

export default defineEventHandler((event) => {
  return proxyEventos(event)
})
