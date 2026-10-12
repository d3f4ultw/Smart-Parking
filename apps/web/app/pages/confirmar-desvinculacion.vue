<script setup lang="ts">
import { onMounted, ref } from 'vue'

definePageMeta({ layout: false })

useHead({
  title: 'Confirmación de desvinculación | Smart Parking',
  meta: [
    { name: 'referrer', content: 'no-referrer' },
    { name: 'robots', content: 'noindex, nofollow, noarchive' },
  ],
})

const estado = ref<'procesando' | 'exito' | 'error'>('procesando')
let enviada = false

function quitarCredencialDeLaUrl() {
  window.history.replaceState(
    window.history.state,
    '',
    window.location.pathname,
  )
}

onMounted(async () => {
  if (enviada) {
    return
  }
  enviada = true

  const fragmento = window.location.hash.slice(1)
  const prefijo = 'desvincular='
  const token = fragmento.startsWith(prefijo)
    ? fragmento.slice(prefijo.length)
    : ''
  quitarCredencialDeLaUrl()

  if (!/^[A-Za-z0-9_-]{43,64}$/.test(token)) {
    estado.value = 'error'
    return
  }

  try {
    await $fetch('/api/gestion-propietario/desvinculacion/confirmar', {
      method: 'POST',
      body: { token },
      retry: 0,
    })
    estado.value = 'exito'
  } catch {
    estado.value = 'error'
  }
})
</script>

<template>
  <main class="confirmation-page" aria-labelledby="confirmation-title">
    <section class="confirmation-card" aria-live="polite">
      <p class="eyebrow">Smart Parking</p>
      <h1 id="confirmation-title">
        {{ estado === 'exito' ? 'Dueño desvinculado' : 'Confirmación por correo' }}
      </h1>
      <p v-if="estado === 'procesando'" role="status">
        Procesando el enlace seguro…
      </p>
      <p v-else-if="estado === 'exito'" role="status">
        Los datos y el historial se conservaron.
      </p>
      <p v-else role="alert">
        El enlace venció, ya se utilizó o no está disponible. Solicita uno nuevo
        desde la página de gestión.
      </p>
      <NuxtLink v-if="estado !== 'procesando'" to="/login">
        Iniciar sesión
      </NuxtLink>
    </section>
  </main>
</template>

<style scoped>
.confirmation-page {
  display: grid;
  min-height: 100vh;
  padding: 1.5rem;
  place-items: center;
  color: #30263b;
  background: #f4f3f5;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
}

.confirmation-card {
  display: grid;
  width: min(100%, 32rem);
  gap: 0.8rem;
  padding: clamp(1.5rem, 5vw, 2.25rem);
  border: 1px solid #e5e0e9;
  border-radius: 1rem;
  background: #ffffff;
  box-shadow: 0 1.5rem 4rem rgb(32 24 42 / 8%);
}

.eyebrow {
  margin: 0;
  color: #74647f;
  font-size: 0.72rem;
  font-weight: 750;
  letter-spacing: 0.11em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: clamp(1.5rem, 4vw, 2rem);
  letter-spacing: -0.03em;
}

p {
  margin: 0;
  color: #655d6c;
  line-height: 1.6;
}

a {
  justify-self: start;
  margin-top: 0.4rem;
  color: #5c3a86;
  font-weight: 650;
}
</style>
