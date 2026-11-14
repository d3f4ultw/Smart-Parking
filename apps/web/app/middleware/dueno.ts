/** Solo permite que el dueño abra el área administrativa; sin sesión vuelve a la entrada,
 * y si no se puede comprobar el acceso muestra un error en vez de abrir el panel.
 */
export default defineNuxtRouteMiddleware(async () => {
  const { sesion, actualizar } = useSesion()
  await actualizar()

  if (sesion.value.estado === 'error') {
    throw createError({ statusCode: 503, statusMessage: 'No pudimos comprobar tu acceso.' })
  }
  if (sesion.value.estado === 'anonima') return navigateTo('/panel')
  if (sesion.value.identidad.rol !== 'DUENO') {
    throw createError({
      statusCode: 403,
      statusMessage: 'Acceso no disponible.',
      fatal: true,
    })
  }
})
