export default defineNuxtConfig({
  compatibilityDate: '2026-10-25',
  runtimeConfig: {
    apiInternalBase: '',
  },
  colorMode: {
    preference: 'light',
    fallback: 'light',
  },
  devtools: { enabled: false },
  modules: ['@nuxt/ui'],
  fonts: {
    families: [
      { name: 'Inter Variable', provider: 'none' },
      { name: 'Manrope Variable', provider: 'none' },
    ],
  },
  css: ['~/assets/css/main.css'],
})
