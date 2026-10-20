<script setup lang="ts">
definePageMeta({ layout: false })

await navigateTo('/cliente/membresias', { replace: true })
</script>

<template>
  <main class="redirect-page" role="status" aria-live="polite">
    <p>Abriendo tu espacio de membresías…</p>
  </main>
</template>

<style scoped>
.redirect-page { display: grid; min-height: 100vh; min-height: 100dvh; place-items: center; padding: 1rem; color: #655e6c; background: #f8f7fa; font-family: Manrope, ui-sans-serif, system-ui, sans-serif; font-size: .9rem; }
</style>
