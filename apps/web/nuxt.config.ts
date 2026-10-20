export default defineNuxtConfig({
  compatibilityDate: '2024-04-03',
  devtools: {
    enabled: false,
  },
  modules: ['@nuxt/eslint'],
  runtimeConfig: {
    apiInternalBaseUrl: 'http://api-dev:8000',
    sessionCookieName: 'smart_parking_session',
    public: {
      managementOrigin: 'http://localhost:3000',
    },
  },
  routeRules: {
    '/admin/empleados': {
      prerender: false,
      headers: {
        'Cache-Control': 'no-store',
        'X-Robots-Tag': 'noindex, nofollow, noarchive',
      },
    },
    '/admin/clientes': {
      prerender: false,
      headers: {
        'Cache-Control': 'no-store',
        'X-Robots-Tag': 'noindex, nofollow, noarchive',
      },
    },
    '/membresias': {
      prerender: false,
      headers: { 'Cache-Control': 'no-store' },
    },
    '/membresias/resultado': {
      prerender: false,
      headers: {
        'Cache-Control': 'no-store',
        'Referrer-Policy': 'no-referrer',
        'X-Robots-Tag': 'noindex, nofollow, noarchive',
      },
    },
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
      allowedHosts: ['parking.atelierfolio.dev'],
      watch: {
        usePolling: true,
        interval: 100,
      },
    },
  },
})
