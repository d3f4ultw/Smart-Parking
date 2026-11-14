/** Comprueba de nuevo la sesión cuando el navegador vuelve a mostrar una página
 * que había dejado abierta, para no conservar a la vista un panel sin acceso vigente.
 */
export default defineNuxtPlugin((nuxtApp) => {
  const { sesion, actualizar, limpiar } = useSesion()
  let solicitudOperador: Promise<void> | null = null
  let ultimaRevalidacion = 0

  function esRutaOperador(ruta: string): boolean {
    return ruta === '/operador' || ruta.startsWith('/operador/')
  }

  async function revalidarOperador(): Promise<void> {
    if (solicitudOperador) return solicitudOperador
    if (!esRutaOperador(window.location.pathname)) return

    limpiar()
    const verificacion = (async () => {
      try {
        await actualizar()
      } catch {
        return
      }

      if (!esRutaOperador(window.location.pathname)) return
      if (sesion.value.estado === 'anonima') {
        await navigateTo('/panel')
      } else if (sesion.value.estado === 'error') {
        return
      } else if (sesion.value.identidad.rol !== 'OPERADOR') {
        showError(createError({ statusCode: 403, statusMessage: 'Acceso no disponible.' }))
      }
    })()

    solicitudOperador = verificacion
    try {
      await verificacion
    } finally {
      if (solicitudOperador === verificacion) solicitudOperador = null
    }
  }

  function revalidarAlVolver() {
    const ahora = Date.now()
    if (!esRutaOperador(window.location.pathname)) return
    if (solicitudOperador || ahora - ultimaRevalidacion < 800) return
    ultimaRevalidacion = ahora
    void revalidarOperador()
  }

  async function revalidarPropietarioEnCache() {
    await actualizar()
    if (sesion.value.estado === 'anonima') await navigateTo('/panel')
  }

  nuxtApp.hook('app:mounted', () => {
    ultimaRevalidacion = Date.now()
    window.addEventListener('pageshow', (evento) => {
      if (!evento.persisted) return
      if (esRutaOperador(window.location.pathname)) revalidarAlVolver()
      else if (window.location.pathname === '/admin') void revalidarPropietarioEnCache()
    })
    window.addEventListener('focus', revalidarAlVolver)
  })
})
