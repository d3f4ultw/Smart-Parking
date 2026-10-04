<script setup lang="ts">
import { ref } from 'vue'

import { mapearErrorLogout } from '~/utils/logout'
import { obtenerNombreCompleto } from '~/utils/sesion'

definePageMeta({
  middleware: 'sesion-operador',
})

const { usuario, limpiarSesion } = useSesion()
const { cerrarSesion } = useLogout()
const estadoLogout = ref<'listo' | 'enviando' | 'error'>('listo')
const mensajeError = ref('')

async function enviarLogout() {
  if (estadoLogout.value === 'enviando') {
    return
  }

  estadoLogout.value = 'enviando'
  mensajeError.value = ''

  try {
    await cerrarSesion()
  } catch (error: unknown) {
    estadoLogout.value = 'error'
    mensajeError.value = mapearErrorLogout(error)
    return
  }

  limpiarSesion()
  await navigateTo('/login', { replace: true })
}
</script>

<template>
  <main class="operator-page">
    <section class="operator-card" aria-labelledby="operator-title">
      <p class="eyebrow">Smart Parking</p>
      <h1 id="operator-title">Área de operador</h1>
      <p>Sesión de OPERADOR activa.</p>
      <p v-if="usuario" class="operator-name">
        {{ obtenerNombreCompleto(usuario) }}
      </p>
      <p v-if="usuario" class="operator-email">{{ usuario.correo }}</p>

      <div v-if="mensajeError" class="state-block error" role="alert">
        <p>{{ mensajeError }}</p>
      </div>

      <button
        class="button logout-button"
        type="button"
        :disabled="estadoLogout === 'enviando'"
        @click="enviarLogout"
      >
        {{ estadoLogout === 'enviando' ? 'Cerrando sesión…' : 'Cerrar sesión' }}
      </button>
    </section>
  </main>
</template>

<style scoped>
:global(*) {
  box-sizing: border-box;
}

:global(body) {
  margin: 0;
  color: #18324b;
  background: #edf5f8;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
}

.operator-page {
  display: grid;
  width: 100%;
  min-height: 100vh;
  padding: 1.5rem;
  place-items: center;
}

.operator-card {
  width: min(100%, 40rem);
  padding: clamp(1.5rem, 4vw, 2.75rem);
  background: #ffffff;
  border: 1px solid #d6e5ea;
  border-radius: 1.25rem;
  box-shadow: 0 1.5rem 4rem rgb(24 50 75 / 12%);
}

.eyebrow {
  margin: 0 0 0.5rem;
  color: #0d7286;
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h1 {
  margin: 0 0 0.65rem;
  color: #102a43;
  font-size: clamp(1.8rem, 5vw, 2.4rem);
}

p {
  line-height: 1.55;
}

.operator-email {
  overflow-wrap: anywhere;
}

.operator-name {
  color: #102a43;
  font-weight: 700;
}

.button {
  display: inline-flex;
  min-height: 2.9rem;
  align-items: center;
  justify-content: center;
  padding: 0.7rem 1rem;
  border: 0;
  border-radius: 0.55rem;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}

.button:disabled {
  cursor: wait;
  opacity: 0.65;
}

.logout-button {
  margin-top: 1.25rem;
  color: #ffffff;
  background: #b54747;
}

.logout-button:hover:not(:disabled),
.logout-button:focus-visible {
  background: #933b3b;
}

.state-block {
  margin-top: 1.25rem;
  padding: 1rem;
  background: #f4f8fa;
  border: 1px solid #d6e5ea;
  border-radius: 0.75rem;
}

.state-block p:last-child {
  margin-bottom: 0;
}

.state-block.error {
  background: #fff5f3;
  border-color: #edc2ba;
}

@media (max-width: 32rem) {
  .operator-page {
    padding: 0.75rem;
  }

  .operator-card {
    border-radius: 0.9rem;
  }
}
</style>
