export default defineNuxtRouteMiddleware(async () => {
  const nuxtApp = useNuxtApp()
  const { autenticado, usuario, resolverSesion } = useSesion()

  // SSR resuelve /me; CSR vuelve a comprobar el rol al cambiar de ruta.
  const forzarVerificacion = import.meta.client && !nuxtApp.isHydrating
  await resolverSesion({ forzar: forzarVerificacion })

  if (!autenticado.value || usuario.value === null) {
    return navigateTo('/login', { replace: true })
  }

  if (usuario.value.rol === 'OWNER') {
    return
  }

  return navigateTo(
    usuario.value.rol === 'OPERADOR' ? '/operador' : '/admin',
    { replace: true },
  )
})
