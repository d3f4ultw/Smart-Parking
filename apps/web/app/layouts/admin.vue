<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  crearControladorEventosTiempoReal,
  proveerEventosTiempoReal,
} from '~/utils/eventos-tiempo-real'
import { mapearErrorLogout } from '~/utils/logout'

const route = useRoute()
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

useHead({
  link: [
    { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
    { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: 'anonymous' },
    {
      rel: 'stylesheet',
      href: 'https://fonts.googleapis.com/css2?family=Manrope:wght@400..800&display=swap',
    },
  ],
})

const mobileMenuOpen = ref(false)
const drawer = ref<HTMLElement | null>(null)
const mobileMenuButton = ref<HTMLButtonElement | null>(null)
const drawerCloseButton = ref<HTMLButtonElement | null>(null)
const estadoLogout = ref<'listo' | 'enviando' | 'error'>('listo')
const mensajeErrorLogout = ref('')

const nombreAdmin = computed(() => {
  if (usuario.value === null) {
    return 'Administrador'
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

const inicialAdmin = computed(() => nombreAdmin.value.charAt(0).toUpperCase())

function esRutaActiva(ruta: 'inicio' | 'operadores') {
  return ruta === 'inicio'
    ? route.path === '/admin'
    : route.path.startsWith('/admin/operadores')
}

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
  <div class="admin-shell">
    <button
      v-if="mobileMenuOpen"
      class="drawer-backdrop"
      type="button"
      aria-label="Cerrar menú de administración"
      @click="cerrarMenuMovil"
    />

    <aside
      id="admin-sidebar"
      ref="drawer"
      class="admin-sidebar"
      :class="{ 'is-open': mobileMenuOpen }"
      aria-label="Navegación de administración"
    >
      <div class="sidebar-top">
        <NuxtLink class="brand-lockup" to="/admin" @click="cerrarMenuMovil">
          <span class="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
              <path d="M13 31V9h9a7 7 0 0 1 0 14h-9" />
              <path d="M10 35h20" />
            </svg>
          </span>
          <span class="brand-name-group">
            <span class="brand-name">Smart Parking</span>
            <span class="brand-caption">ADMINISTRACIÓN</span>
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
        <p class="navigation-label">GESTIÓN</p>
        <NuxtLink
          class="navigation-item"
          :class="{ 'is-active': esRutaActiva('inicio') }"
          to="/admin"
          :aria-current="esRutaActiva('inicio') ? 'page' : undefined"
          @click="cerrarMenuMovil"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z" />
          </svg>
          <span>Dashboard</span>
        </NuxtLink>
        <button class="navigation-item navigation-disabled" type="button" disabled aria-disabled="true">
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 20V9l9-5 9 5v11M3 12h18M7 20v-5h10v5" />
          </svg>
          <span>Estacionamiento</span>
        </button>
        <NuxtLink
          class="navigation-item"
          :class="{ 'is-active': esRutaActiva('operadores') }"
          to="/admin/operadores"
          :aria-current="esRutaActiva('operadores') ? 'page' : undefined"
          @click="cerrarMenuMovil"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="9" cy="8" r="3.5" />
            <path d="M2.5 20v-1.5A4.5 4.5 0 0 1 7 14h4a4.5 4.5 0 0 1 4.5 4.5V20M16 5a3.5 3.5 0 0 1 0 6.8M17 14h.5a4 4 0 0 1 4 4v2" />
          </svg>
          <span>Operadores</span>
        </NuxtLink>
        <button class="navigation-item navigation-disabled" type="button" disabled aria-disabled="true">
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 4h16v16H4zM8 8h8M8 12h8M8 16h5" />
          </svg>
          <span>Registros</span>
          <small>Próximamente</small>
        </button>

        <p class="navigation-label account-label">CUENTA</p>
        <button class="navigation-item navigation-disabled" type="button" disabled aria-disabled="true">
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="m19.4 15 .1.1a1.7 1.7 0 0 1-2.4 2.4l-.1-.1a1.7 1.7 0 0 0-2.9 1.2v.2a1.7 1.7 0 0 1-3.4 0v-.2a1.7 1.7 0 0 0-2.9-1.2l-.1.1a1.7 1.7 0 0 1-2.4-2.4l.1-.1a1.7 1.7 0 0 0-1.2-2.9H4a1.7 1.7 0 0 1 0-3.4h.2a1.7 1.7 0 0 0 1.2-2.9l-.1-.1a1.7 1.7 0 0 1 2.4-2.4l.1.1a1.7 1.7 0 0 0 2.9-1.2V4a1.7 1.7 0 0 1 3.4 0v.2a1.7 1.7 0 0 0 2.9 1.2l.1-.1a1.7 1.7 0 0 1 2.4 2.4l-.1.1a1.7 1.7 0 0 0 1.2 2.9h.2a1.7 1.7 0 0 1 0 3.4h-.2a1.7 1.7 0 0 0-1.2.9Z" />
          </svg>
          <span>Configuración</span>
          <small>Próximamente</small>
        </button>
      </nav>

      <div class="sidebar-footer">
        <div v-if="mensajeErrorLogout" class="logout-error" role="alert">
          {{ mensajeErrorLogout }}
        </div>
        <div class="admin-profile">
          <span class="admin-avatar" aria-hidden="true">{{ inicialAdmin }}</span>
          <span class="admin-copy">
            <span class="admin-name">{{ nombreAdmin }}</span>
            <span class="admin-role">Administrador</span>
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

    <main class="admin-main">
      <header class="mobile-header">
        <button
          ref="mobileMenuButton"
          class="mobile-menu-toggle"
          type="button"
          aria-controls="admin-sidebar"
          :aria-expanded="mobileMenuOpen"
          aria-label="Abrir menú de administración"
          @click="mobileMenuOpen = true"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
            <path d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <span>Smart Parking</span>
      </header>
      <div class="admin-content">
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

.admin-shell {
  --admin-bg: #f6f5f7;
  --admin-surface: #ffffff;
  --admin-surface-soft: #f8f7f9;
  --admin-foreground: #29252f;
  --admin-muted: #746f7b;
  --admin-subtle: #98929f;
  --admin-border: #e8e5eb;
  --admin-accent: #5c3a86;
  --admin-accent-hover: #6c4a97;
  --admin-focus: rgb(92 58 134 / 22%);
  display: grid;
  min-height: 100vh;
  grid-template-columns: 16.5rem minmax(0, 1fr);
  color: var(--admin-foreground);
  background: var(--admin-bg);
  font-family: Manrope, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
}

.admin-sidebar {
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
.admin-copy {
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

.drawer-close svg {
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

.account-label {
  margin-top: 1.75rem;
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
  font: inherit;
  font-size: 0.88rem;
  font-weight: 550;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
  transition: color 150ms ease, background-color 150ms ease, border-color 150ms ease;
}

.navigation-item > svg {
  width: 1.15rem;
  height: 1.15rem;
  flex: 0 0 auto;
  color: #a79daf;
}

.navigation-item:hover:not(:disabled),
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

.navigation-item.navigation-disabled {
  color: #918999;
  cursor: not-allowed;
}

.navigation-item.navigation-disabled > svg {
  color: #81798a;
}

.navigation-item small {
  margin-left: auto;
  color: #a69eaf;
  font-size: 0.59rem;
  font-weight: 600;
  white-space: nowrap;
}

.sidebar-footer {
  display: grid;
  gap: 0.85rem;
  margin-top: auto;
  padding: 1rem 0.25rem 0;
  border-top: 1px solid rgb(255 255 255 / 11%);
}

.admin-profile {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.7rem;
  padding: 0.35rem 0.4rem;
}

.admin-avatar {
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

.admin-name {
  overflow: hidden;
  color: #f8f6fa;
  font-size: 0.78rem;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.admin-role {
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

.admin-main {
  min-width: 0;
}

.admin-content {
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
  border: 1px solid var(--admin-border);
  border-radius: 0.75rem;
  cursor: pointer;
}

.mobile-menu-toggle svg {
  width: 1.25rem;
  height: 1.25rem;
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
  .admin-shell {
    display: block;
  }

  .admin-sidebar {
    position: fixed;
    z-index: 30;
    inset: 0 auto 0 0;
    width: min(19rem, calc(100vw - 3rem));
    min-height: 100vh;
      visibility: hidden;
    transform: translateX(-102%);
      transition: transform 180ms ease, visibility 180ms;
  }

  .admin-sidebar.is-open {
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
    border-bottom: 1px solid var(--admin-border);
    font-size: 0.95rem;
    font-weight: 700;
  }

  .admin-content {
    padding: 1.25rem 1rem 2rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .navigation-item,
  .admin-sidebar {
    transition: none;
  }
}
</style>
