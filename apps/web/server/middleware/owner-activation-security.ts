import { getRequestURL, setResponseHeader } from 'h3'

export default defineEventHandler((event) => {
  const ruta = getRequestURL(event).pathname
  if (
    ruta === '/activar-propietario'
    || ruta.startsWith('/api/autenticacion/activacion-propietario/')
  ) {
    setResponseHeader(event, 'cache-control', 'no-store')
    setResponseHeader(event, 'referrer-policy', 'no-referrer')
  }
})
