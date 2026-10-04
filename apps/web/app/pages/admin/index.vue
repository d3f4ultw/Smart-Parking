<script setup lang="ts">
import { computed, ref } from 'vue'

import { mapearErrorLogout } from '~/utils/logout'

definePageMeta({
  middleware: 'sesion-admin',
})

const { usuario, limpiarSesion } = useSesion()
const { cerrarSesion } = useLogout()
const estadoLogout = ref<'listo' | 'enviando' | 'error'>('listo')
const mensajeError = ref('')

const nombreAdmin = computed(() => {
  if (usuario.value === null) {
    return ''
  }

  const nombreCompleto = [
    usuario.value.nombre,
    usuario.value.apellido_paterno,
    usuario.value.apellido_materno,
  ]
    .filter((parte): parte is string => parte !== null && parte.length > 0)
    .join(' ')

  return nombreCompleto || usuario.value.correo
})

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
  <main class="admin-page">
    <section class="admin-card" aria-labelledby="admin-title">
      <p class="eyebrow">Smart Parking</p>
      <h1 id="admin-title">Panel de administración</h1>
      <p>Sesión de ADMIN activa.</p>

      <dl v-if="usuario" class="admin-identity">
        <div>
          <dt>Administrador</dt>
          <dd>{{ nombreAdmin }}</dd>
        </div>
        <div>
          <dt>Correo electrónico</dt>
          <dd>{{ usuario.correo }}</dd>
        </div>
      </dl>

      <div v-if="mensajeError" class="state-block error" role="alert">
        <p>{{ mensajeError }}</p>
      </div>

      <NuxtLink class="button operator-link" to="/admin/operadores/nuevo?desde=panel">
        Crear operador
      </NuxtLink>

      <NuxtLink class="button operator-link" to="/admin/operadores">
        Administrar operadores
      </NuxtLink>

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

.admin-page {
  display: grid;
  width: 100%;
  min-height: 100vh;
  padding: 1.5rem;
  place-items: center;
}

.admin-card {
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
  margin-top: 1.75rem;
  color: #ffffff;
  background: #b54747;
}

.operator-link {
  margin-top: 1.75rem;
  color: #ffffff;
  background: #0d7286;
  text-decoration: none;
}

.operator-link:hover,
.operator-link:focus-visible {
  background: #09596a;
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

.admin-identity {
  display: grid;
  gap: 1rem;
  margin: 1.75rem 0 0;
}

.admin-identity div {
  padding: 1rem;
  background: #f4f8fa;
  border: 1px solid #d6e5ea;
  border-radius: 0.75rem;
}

dt {
  color: #5c7487;
  font-size: 0.85rem;
  font-weight: 700;
}

dd {
  margin: 0.3rem 0 0;
  color: #102a43;
  font-weight: 600;
  overflow-wrap: anywhere;
}

@media (max-width: 32rem) {
  .admin-page {
    padding: 0.75rem;
  }

  .admin-card {
    border-radius: 0.9rem;
  }
}
</style>
