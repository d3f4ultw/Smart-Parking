export default defineNuxtConfig({
  compatibilityDate: '2024-04-03',
  devtools: {
    enabled: false,
  },
  modules: ['@nuxt/eslint'],
  runtimeConfig: {
    apiInternalBaseUrl: 'http://api-dev:8000',
  },
  routeRules: {
    '/activar-cuenta': {
      prerender: false,
      headers: {
        'Cache-Control': 'no-store',
        'Referrer-Policy': 'no-referrer',
      },
    },
  },
  vite: {
    server: {
      watch: {
        usePolling: true,
        interval: 100,
      },
    },
  },
})
