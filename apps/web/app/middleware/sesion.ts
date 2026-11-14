/** Actualiza la sesión antes de decidir el destino: si alguien sin sesión intenta
 * abrir administración, lo lleva a la entrada; desde allí dirige al dueño
 * y al operador a sus respectivas áreas.
 */
export default defineNuxtRouteMiddleware(async (to) => {
  const { sesion, actualizar } = useSesion()
  await actualizar()

  if (sesion.value.estado === 'error') return

  const identidad = sesion.value.estado === 'autenticada' ? sesion.value.identidad : null
  if (to.path === '/admin' && !identidad) return navigateTo('/panel')
  if (to.path === '/panel' && identidad?.rol === 'DUENO') return navigateTo('/admin')
  if (to.path === '/panel' && identidad?.rol === 'OPERADOR') return navigateTo('/operador')
})
