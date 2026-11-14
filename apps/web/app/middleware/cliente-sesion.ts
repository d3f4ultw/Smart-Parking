/** Exige una sesión de cliente para mostrar el portal. El acceso y el registro siguen
 * disponibles sin sesión, y el regreso desde el proveedor de pago no requiere comprobarla.
 */
export default defineNuxtRouteMiddleware(async (to) => {
  if (!to.path.startsWith('/clientes/') || to.path === '/clientes/checkout/retorno') return

  const rutaProtegida = to.path === '/clientes/portal'
  const { actualizar } = useSesionCliente()
  const estadoSesion = await actualizar()

  if (estadoSesion.estado === 'error') {
    if (rutaProtegida) {
      return abortNavigation(
        createError({
          statusCode: 503,
          statusMessage: 'No pudimos comprobar tu acceso. Inténtalo de nuevo.',
        }),
      )
    }
    return
  }

  const autenticada = estadoSesion.estado === 'autenticada'
  if (rutaProtegida && !autenticada) {
    return navigateTo('/clientes/acceso')
  }
  if (autenticada && (to.path === '/clientes/acceso' || to.path === '/clientes/registro')) {
    return navigateTo('/clientes/portal')
  }
})
