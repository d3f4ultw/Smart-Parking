<script setup lang="ts">
import { obtenerPaginaSolicitadaOperadores } from '~/utils/gestion-operadores'

definePageMeta({
  layout: 'admin',
  middleware: 'sesion-admin',
})

const route = useRoute()
const pagina = obtenerPaginaSolicitadaOperadores(route.query.pagina)
const operadorId = String(route.params.id)

await navigateTo({
  path: '/admin/operadores',
  query: {
    ...(pagina > 1 ? { pagina: String(pagina) } : {}),
    modal: 'detalle',
    operador: operadorId,
  },
}, { replace: true })
</script>

<template>
  <main class="redirect-state" role="status">
    Abriendo el detalle del operador…
  </main>
</template>

<style scoped>
.redirect-state {
  padding: 1rem;
  color: #746f7b;
}
</style>
