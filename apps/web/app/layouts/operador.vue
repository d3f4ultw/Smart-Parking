<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  crearControladorEventosTiempoReal,
  proveerEventosTiempoReal,
} from '~/utils/eventos-tiempo-real'
import { mapearErrorLogout } from '~/utils/logout'
import { obtenerNombreCompleto } from '~/utils/sesion'

const { usuario, limpiarSesion } = useSesion()
const { cerrarSesion } = useLogout()
const eventosTiempoReal = crearControladorEventosTiempoReal({
  alPerderSesion: async () => {
    limpiarSesion()
    clearNuxtData()
    await navigateTo('/login', { replace: true })
  },
})
proveerEventosTiempoReal(eventosTiempoReal)

const mobileMenuOpen = ref(false)
const drawer = ref<HTMLElement | null>(null)
const mobileMenuButton = ref<HTMLButtonElement | null>(null)
const drawerCloseButton = ref<HTMLButtonElement | null>(null)
const estadoLogout = ref<'listo' | 'enviando' | 'error'>('listo')
const mensajeErrorLogout = ref('')

const nombreOperador = computed(() => {
  if (usuario.value === null) {
    return 'Operador'
  }
  return obtenerNombreCompleto(usuario.value) || usuario.value.correo
})
const inicialOperador = computed(() => nombreOperador.value.charAt(0).toUpperCase())

function cerrarMenuMovil() {
  mobileMenuOpen.value = false
}

async function enviarLogout() {
  if (estadoLogout.value === 'enviando') {
    return
  }

  estadoLogout.value = 'enviando'
  mensajeErrorLogout.value = ''

  try {
    await cerrarSesion()
  } catch (error: unknown) {
    estadoLogout.value = 'error'
    mensajeErrorLogout.value = mapearErrorLogout(error)
    return
  }

  eventosTiempoReal.detener()
  limpiarSesion()
  await navigateTo('/login', { replace: true })
}

function manejarTeclado(event: KeyboardEvent) {
  if (!mobileMenuOpen.value) {
    return
  }
  if (event.key === 'Escape') {
    cerrarMenuMovil()
    return
  }
  if (event.key !== 'Tab' || drawer.value === null) {
    return
  }

  const elementosEnfocables = Array.from(
    drawer.value.querySelectorAll<HTMLElement>(
      'a[href], button:not(:disabled), [tabindex]:not([tabindex="-1"])',
    ),
  )
  const primero = elementosEnfocables[0]
  const ultimo = elementosEnfocables[elementosEnfocables.length - 1]
  if (primero === undefined || ultimo === undefined) {
    return
  }

  if (event.shiftKey && document.activeElement === primero) {
    event.preventDefault()
    ultimo.focus()
  } else if (!event.shiftKey && document.activeElement === ultimo) {
    event.preventDefault()
    primero.focus()
  }
}

watch(mobileMenuOpen, async (abierto) => {
  await nextTick()
  if (abierto) {
    drawerCloseButton.value?.focus()
  } else {
    mobileMenuButton.value?.focus()
  }
})

onMounted(() => {
  window.addEventListener('keydown', manejarTeclado)
  eventosTiempoReal.iniciar()
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', manejarTeclado)
  eventosTiempoReal.detener()
})
</script>

<template>
  <div class="operator-shell">
    <button
      v-if="mobileMenuOpen"
      class="drawer-backdrop"
      type="button"
      aria-label="Cerrar menú de operador"
      @click="cerrarMenuMovil"
    />

    <aside
      id="operator-sidebar"
      ref="drawer"
      class="operator-sidebar"
      :class="{ 'is-open': mobileMenuOpen }"
      aria-label="Navegación de operador"
    >
      <div class="sidebar-top">
        <NuxtLink class="brand-lockup" to="/operador" @click="cerrarMenuMovil">
          <span class="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
              <path d="M13 31V9h9a7 7 0 0 1 0 14h-9" />
              <path d="M10 35h20" />
            </svg>
          </span>
          <span class="brand-name-group">
            <span class="brand-name">Smart Parking</span>
            <span class="brand-caption">OPERACIÓN</span>
          </span>
        </NuxtLink>

        <button
          ref="drawerCloseButton"
          class="drawer-close"
          type="button"
          aria-label="Cerrar menú"
          @click="cerrarMenuMovil"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
            <path d="m6 6 12 12M18 6 6 18" />
          </svg>
        </button>
      </div>

      <nav class="primary-navigation" aria-label="Principal">
        <p class="navigation-label">OPERACIÓN</p>
        <NuxtLink
          class="navigation-item is-active"
          to="/operador"
          aria-current="page"
          @click="cerrarMenuMovil"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 20V9l9-5 9 5v11M3 12h18M7 20v-5h10v5" />
          </svg>
          <span>Estacionamiento</span>
        </NuxtLink>
      </nav>

      <div class="sidebar-footer">
        <div v-if="mensajeErrorLogout" class="logout-error" role="alert">
          {{ mensajeErrorLogout }}
        </div>
        <div class="operator-profile">
          <span class="operator-avatar" aria-hidden="true">{{ inicialOperador }}</span>
          <span class="operator-copy">
            <span class="operator-name">{{ nombreOperador }}</span>
            <span class="operator-role">Operador</span>
          </span>
        </div>
        <button
          class="logout-button"
          type="button"
          :disabled="estadoLogout === 'enviando'"
          @click="enviarLogout"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M10 17l5-5-5-5M15 12H3M12 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6" />
          </svg>
          <span>{{ estadoLogout === 'enviando' ? 'Cerrando sesión…' : 'Cerrar sesión' }}</span>
        </button>
      </div>
    </aside>

    <main class="operator-main">
      <header class="mobile-header">
        <button
          ref="mobileMenuButton"
          class="mobile-menu-toggle"
          type="button"
          aria-controls="operator-sidebar"
          :aria-expanded="mobileMenuOpen"
          aria-label="Abrir menú de operador"
          @click="mobileMenuOpen = true"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
            <path d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <span>Smart Parking</span>
      </header>
      <div class="operator-content">
        <slot />
      </div>
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
  color: #29252f;
  background: #f6f5f7;
  font-family: Manrope, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
}

button,
a {
  -webkit-tap-highlight-color: transparent;
}

.operator-shell {
  --operator-border: #e8e5eb;
  display: grid;
  min-height: 100vh;
  grid-template-columns: 16.5rem minmax(0, 1fr);
  color: #29252f;
  background: #f6f5f7;
  font-family: Manrope, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
}

.operator-sidebar {
  position: sticky;
  top: 0;
  display: flex;
  height: 100vh;
  min-height: 36rem;
  flex-direction: column;
  padding: 1.75rem 1rem 1rem;
  color: #f8f6fa;
  background:
    radial-gradient(ellipse at 8% 0%, rgb(104 77 137 / 12%), transparent 34%),
    linear-gradient(160deg, #1d1725 0%, #17121e 76%, #15101b 100%);
  border-right: 1px solid rgb(255 255 255 / 7%);
}

.sidebar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0 0 2.6rem;
  padding: 0 0.5rem;
}

.brand-lockup {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.75rem;
  color: inherit;
  text-decoration: none;
}

.brand-mark {
  display: grid;
  width: 2.75rem;
  height: 2.75rem;
  flex: 0 0 auto;
  place-items: center;
  color: #ffffff;
  background: rgb(255 255 255 / 9%);
  border: 1px solid rgb(255 255 255 / 17%);
  border-radius: 0.85rem;
}

.brand-mark svg {
  width: 1.65rem;
  height: 1.65rem;
}

.brand-name-group,
.operator-copy {
  display: grid;
  min-width: 0;
}

.brand-name {
  overflow: hidden;
  font-size: 0.98rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.brand-caption {
  margin-top: 0.2rem;
  color: #b7afc0;
  font-size: 0.59rem;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.drawer-close {
  display: none;
  width: 2.5rem;
  height: 2.5rem;
  flex: 0 0 auto;
  place-items: center;
  color: #f8f6fa;
  background: transparent;
  border: 1px solid rgb(255 255 255 / 15%);
  border-radius: 0.7rem;
  cursor: pointer;
}

.drawer-close svg,
.mobile-menu-toggle svg {
  width: 1.2rem;
  height: 1.2rem;
}

.primary-navigation {
  display: grid;
  align-content: start;
  gap: 0.35rem;
}

.navigation-label {
  margin: 0.15rem 0 0.45rem 0.75rem;
  color: #958ca0;
  font-size: 0.65rem;
  font-weight: 750;
  letter-spacing: 0.15em;
}

.navigation-item {
  display: flex;
  width: auto;
  min-height: 2.8rem;
  align-items: center;
  gap: 0.8rem;
  margin-right: 0.75rem;
  padding: 0.65rem 0.75rem;
  color: #c9c3d0;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 0.75rem;
  font-size: 0.88rem;
  font-weight: 550;
  text-decoration: none;
  transition: color 150ms ease, background-color 150ms ease, border-color 150ms ease;
}

.navigation-item > svg {
  width: 1.15rem;
  height: 1.15rem;
  flex: 0 0 auto;
  color: #a79daf;
}

.navigation-item:hover,
.navigation-item:focus-visible {
  color: #ffffff;
  background: rgb(255 255 255 / 6%);
}

.navigation-item.is-active {
  color: #ffffff;
  background: rgb(113 82 150 / 28%);
  border-color: rgb(166 140 196 / 20%);
}

.navigation-item.is-active > svg {
  color: #cdb9e3;
}

.sidebar-footer {
  display: grid;
  gap: 0.85rem;
  margin-top: auto;
  padding: 1rem 0.25rem 0;
  border-top: 1px solid rgb(255 255 255 / 11%);
}

.operator-profile {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.7rem;
  padding: 0.35rem 0.4rem;
}

.operator-avatar {
  display: grid;
  width: 2.35rem;
  height: 2.35rem;
  flex: 0 0 auto;
  place-items: center;
  color: #e8def1;
  background: rgb(112 81 149 / 38%);
  border: 1px solid rgb(188 164 211 / 24%);
  border-radius: 50%;
  font-size: 0.9rem;
  font-weight: 700;
}

.operator-name {
  overflow: hidden;
  color: #f8f6fa;
  font-size: 0.78rem;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.operator-role {
  margin-top: 0.15rem;
  color: #aaa2b4;
  font-size: 0.72rem;
}

.logout-button {
  display: flex;
  min-height: 2.7rem;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6rem 0.75rem;
  color: #d6d0dc;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 0.7rem;
  font: inherit;
  font-size: 0.84rem;
  font-weight: 550;
  text-align: left;
  cursor: pointer;
}

.logout-button svg {
  width: 1.1rem;
  height: 1.1rem;
  flex: 0 0 auto;
}

.logout-button:hover:not(:disabled),
.logout-button:focus-visible {
  color: #ffffff;
  background: rgb(255 255 255 / 7%);
}

.logout-button:disabled {
  cursor: wait;
  opacity: 0.72;
}

.logout-error {
  padding: 0.7rem;
  color: #eadff2;
  background: rgb(118 76 126 / 22%);
  border: 1px solid rgb(188 148 198 / 28%);
  border-radius: 0.65rem;
  font-size: 0.78rem;
  line-height: 1.45;
}

.operator-main {
  min-width: 0;
}

.operator-content {
  width: min(100%, 92rem);
  min-width: 0;
  margin: 0 auto;
  padding: clamp(1.5rem, 3vw, 2.75rem) clamp(1rem, 3vw, 3rem);
}

.mobile-header {
  display: none;
}

.mobile-menu-toggle {
  display: grid;
  width: 2.7rem;
  height: 2.7rem;
  place-items: center;
  color: #483a55;
  background: #ffffff;
  border: 1px solid var(--operator-border);
  border-radius: 0.75rem;
  cursor: pointer;
}

.drawer-backdrop {
  display: none;
}

.brand-lockup:focus-visible,
.drawer-close:focus-visible,
.navigation-item:focus-visible,
.logout-button:focus-visible,
.mobile-menu-toggle:focus-visible {
  outline: 3px solid #bda6d6;
  outline-offset: 3px;
}

@media (max-width: 54rem) {
  .operator-shell {
    display: block;
  }

  .operator-sidebar {
    position: fixed;
    z-index: 30;
    inset: 0 auto 0 0;
    width: min(19rem, calc(100vw - 3rem));
    min-height: 100vh;
    visibility: hidden;
    transform: translateX(-102%);
    transition: transform 180ms ease, visibility 180ms;
  }

  .operator-sidebar.is-open {
    visibility: visible;
    transform: translateX(0);
  }

  .drawer-close {
    display: grid;
  }

  .drawer-backdrop {
    position: fixed;
    z-index: 20;
    inset: 0;
    display: block;
    background: rgb(19 14 25 / 58%);
    border: 0;
    cursor: pointer;
  }

  .mobile-header {
    display: flex;
    min-height: 4.2rem;
    align-items: center;
    gap: 0.8rem;
    padding: 0.65rem 1rem;
    color: #3c3344;
    background: #ffffff;
    border-bottom: 1px solid var(--operator-border);
    font-size: 0.95rem;
    font-weight: 700;
  }

  .operator-content {
    padding: 1.25rem 1rem 2rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .navigation-item,
  .operator-sidebar {
    transition: none;
  }
}
</style>
