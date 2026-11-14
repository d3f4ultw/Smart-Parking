/** Antes de abrir el área del operador, comprueba que su sesión siga activa;
 * si no puede hacerlo, muestra un error y no carga el panel.
 */
export default defineNuxtRouteMiddleware(async () => {
  const { sesion, actualizar } = useSesion()
  try {
    await actualizar()
  } catch {
    throw createError({ statusCode: 503, statusMessage: 'No pudimos comprobar tu acceso.' })
  }

  if (sesion.value.estado === 'error') {
    throw createError({ statusCode: 503, statusMessage: 'No pudimos comprobar tu acceso.' })
  }
  if (sesion.value.estado === 'anonima') return navigateTo('/panel')
  if (sesion.value.identidad.rol !== 'OPERADOR') {
    throw createError({
      statusCode: 403,
      statusMessage: 'Acceso no disponible.',
      fatal: true,
    })
  }
})
