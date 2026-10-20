export default defineNuxtRouteMiddleware(async () => {
  const nuxtApp = useNuxtApp()
  const { autenticado, cliente, limpiarSesion, resolverSesion } = useSesionCliente()

  // La hidratación reutiliza la sesión resuelta por SSR; las navegaciones CSR
  // verifican de nuevo la cookie con el servidor antes de abrir la ruta.
  const forzarVerificacion = import.meta.client && !nuxtApp.isHydrating

  try {
    await resolverSesion({ forzar: forzarVerificacion })
  } catch {
    limpiarSesion()
    return navigateTo('/cliente/login', { replace: true })
  }

  if (!autenticado.value || cliente.value === null) {
    return navigateTo('/cliente/login', { replace: true })
  }
})
