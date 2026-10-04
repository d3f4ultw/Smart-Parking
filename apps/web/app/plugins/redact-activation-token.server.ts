export default defineNuxtPlugin((nuxtApp) => {
  nuxtApp.hook('app:rendered', () => {
    const renderedPath = nuxtApp.payload.path
    if (!renderedPath) {
      return
    }

    const url = new URL(renderedPath, 'http://smart-parking.local')
    if (!['/activar', '/activar-cuenta'].includes(url.pathname) || !url.searchParams.has('token')) {
      return
    }

    url.searchParams.delete('token')
    // Nuxt adds the browser's current query back during hydration when the
    // rendered path contains only the stable pathname.
    nuxtApp.payload.path = url.pathname
  })
})
