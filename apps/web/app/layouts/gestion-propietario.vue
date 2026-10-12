<script setup lang="ts">
import { onBeforeUnmount, onMounted, watch } from 'vue'

const sesionActiva = useState<boolean>('gestion-propietario:activa', () => false)
let temporizadorLatido: ReturnType<typeof setInterval> | undefined
let latidoEnCurso = false

function detenerLatidos() {
  if (temporizadorLatido !== undefined) {
    clearInterval(temporizadorLatido)
    temporizadorLatido = undefined
  }
}

async function enviarLatido() {
  if (latidoEnCurso || !sesionActiva.value) {
    return
  }
  latidoEnCurso = true
  try {
    const respuesta = await $fetch<{ activa: boolean }>(
      '/api/gestion-propietario/latido',
      { method: 'POST', retry: 0 },
    )
    if (!respuesta.activa) {
      sesionActiva.value = false
    }
  } catch (error: unknown) {
    const respuesta = error as { status?: number; statusCode?: number }
    if (respuesta.status === 401 || respuesta.statusCode === 401) {
      sesionActiva.value = false
    }
  } finally {
    latidoEnCurso = false
  }
}

function iniciarLatidos() {
  if (!import.meta.client || temporizadorLatido !== undefined) {
    return
  }
  temporizadorLatido = setInterval(() => {
    void enviarLatido()
  }, 15_000)
}

watch(sesionActiva, (activa) => {
  if (!import.meta.client) {
    return
  }
  if (activa) {
    iniciarLatidos()
  } else {
    detenerLatidos()
  }
})

onMounted(() => {
  if (sesionActiva.value) {
    iniciarLatidos()
  }
})

onBeforeUnmount(detenerLatidos)
</script>

<template>
  <div class="owner-management-shell">
    <header class="management-header">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true">P</span>
        <span>
          <strong>Smart Parking</strong>
          <small>GESTIÓN DE DUEÑO</small>
        </span>
      </div>
      <div class="session-indicator" :class="{ 'is-active': sesionActiva }" role="status">
        <span
          class="session-dot"
          :style="sesionActiva
            ? { backgroundColor: '#75d19b', boxShadow: '0 0 0 0.2rem rgb(117 209 155 / 16%)' }
            : undefined"
          aria-hidden="true"
        />
        {{ sesionActiva ? 'Sesión temporal activa' : 'Esperando autorización' }}
      </div>
    </header>
    <main class="management-main">
      <slot />
    </main>
    <AdminToastNotifications />
  </div>
</template>

<style>
* {
  box-sizing: border-box;
}

body {
  margin: 0;
  color: #30263b;
  background: #f6f4f8;
  font-family: Manrope, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
}

button,
input {
  font: inherit;
}

.owner-management-shell {
  min-height: 100vh;
  background:
    radial-gradient(ellipse at 8% 0%, rgb(127 95 156 / 8%), transparent 33%),
    #f6f4f8;
}

.management-header {
  display: flex;
  min-height: 4.7rem;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.75rem clamp(1rem, 4vw, 3.5rem);
  color: #ffffff;
  background: #20192a;
}

.brand {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  color: inherit;
}

.brand > span:last-child {
  display: grid;
  gap: 0.12rem;
}

.brand strong {
  font-size: 0.95rem;
  font-weight: 700;
}

.brand small {
  color: #b6abbf;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.brand-mark {
  display: grid;
  width: 2.55rem;
  height: 2.55rem;
  place-items: center;
  color: #ffffff;
  background: #594074;
  border: 1px solid rgb(255 255 255 / 18%);
  border-radius: 0.8rem;
  font-weight: 800;
}

.session-indicator {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: #c7bfce;
  font-size: 0.78rem;
}

.session-indicator.is-active {
  color: #e9d9f6;
}

.session-dot {
  width: 0.55rem;
  height: 0.55rem;
  background: #a29aa8;
  border-radius: 50%;
}

.session-indicator.is-active .session-dot {
  background: #75d19b;
  box-shadow: 0 0 0 0.2rem rgb(117 209 155 / 16%);
}

.management-main {
  width: min(100%, 75rem);
  margin: 0 auto;
  padding: clamp(1.25rem, 4vw, 2.5rem) clamp(1rem, 4vw, 2.75rem) 2rem;
}

@media (max-width: 38rem) {
  .management-header {
    align-items: flex-start;
  }

  .session-indicator {
    max-width: 8.5rem;
    justify-content: flex-end;
    text-align: right;
  }
}
</style>
