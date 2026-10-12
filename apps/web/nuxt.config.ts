export default defineNuxtConfig({
  compatibilityDate: '2024-04-03',
  devtools: {
    enabled: false,
  },
  modules: ['@nuxt/eslint'],
  runtimeConfig: {
    apiInternalBaseUrl: 'http://api-dev:8000',
    public: {
      managementOrigin: 'http://localhost:3000',
    },
  },
  routeRules: {
    '/activar-cuenta': {
      prerender: false,
      headers: {
        'Cache-Control': 'no-store',
        'Referrer-Policy': 'no-referrer',
      },
    },
    '/admin/gestion-propietario': {
      prerender: false,
      headers: {
        'Cache-Control': 'no-store',
        'Referrer-Policy': 'no-referrer',
        'X-Robots-Tag': 'noindex, nofollow, noarchive',
      },
    },
    '/confirmar-desvinculacion': {
      prerender: false,
      headers: {
        'Cache-Control': 'no-store',
        'Referrer-Policy': 'no-referrer',
        'X-Robots-Tag': 'noindex, nofollow, noarchive',
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
