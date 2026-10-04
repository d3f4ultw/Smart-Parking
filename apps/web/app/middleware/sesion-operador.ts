export default defineNuxtRouteMiddleware(async () => {
  const nuxtApp = useNuxtApp()
  const { autenticado, usuario, resolverSesion } = useSesion()

  // Durante hidratacion se reutiliza el resultado SSR para no duplicar /me.
  const forzarVerificacion = import.meta.client && !nuxtApp.isHydrating
  await resolverSesion({ forzar: forzarVerificacion })

  if (!autenticado.value || usuario.value === null) {
    return navigateTo('/login', { replace: true })
  }

  if (usuario.value.rol !== 'OPERADOR') {
    return navigateTo('/admin', { replace: true })
  }
})
