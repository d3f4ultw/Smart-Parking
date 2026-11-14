import { esRutaModuloOperador } from '~/utils/rutas-modulos-operador'

function esRutaDePropietario(ruta: string) {
  return ruta === '/admin' || ruta.startsWith('/admin/')
}

/** Deja al dueño en sus páginas de administración y al operador solo en las páginas
 * de su área; quien no tiene sesión va a la entrada, y las demás combinaciones
 * de persona y página reciben acceso denegado.
 */
export default defineNuxtRouteMiddleware((to) => {
  const { sesion } = useSesion()

  if (sesion.value.estado === 'error') {
    throw createError({ statusCode: 503, statusMessage: 'No pudimos comprobar tu acceso.' })
  }
  if (sesion.value.estado === 'anonima') return navigateTo('/panel')

  const rol = sesion.value.identidad.rol
  if (rol === 'DUENO' && esRutaDePropietario(to.path)) return
  if (rol === 'OPERADOR' && esRutaModuloOperador(to.path)) return

  throw createError({
    statusCode: 403,
    statusMessage: 'Acceso no disponible.',
    fatal: true,
  })
})
