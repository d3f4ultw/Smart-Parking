<script setup lang="ts">
import { obtenerPaginaSolicitadaOperadores } from '~/utils/gestion-operadores'

definePageMeta({
  layout: 'admin',
  middleware: 'sesion-admin',
})

const route = useRoute()
const pagina = obtenerPaginaSolicitadaOperadores(route.query.pagina)

await navigateTo({
  path: '/admin/operadores',
  query: {
    ...(pagina > 1 ? { pagina: String(pagina) } : {}),
    modal: 'crear',
  },
}, { replace: true })
</script>

<template>
  <main class="redirect-state" role="status">
    Abriendo el formulario para crear operador…
  </main>
</template>

<style scoped>
.redirect-state {
  padding: 1rem;
  color: #746f7b;
}
</style>
