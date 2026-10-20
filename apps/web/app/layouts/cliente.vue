<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { useSesionCliente } from '~/composables/useSesionCliente'

const route = useRoute()
const { cliente, cerrarSesion } = useSesionCliente()
const menuMovilAbierto = ref(false)
const drawer = ref<HTMLElement | null>(null)
const botonMenu = ref<HTMLButtonElement | null>(null)
const botonCerrarMenu = ref<HTMLButtonElement | null>(null)
const cerrandoSesion = ref(false)
const errorLogout = ref('')

const nombreCliente = computed(() => {
  if (cliente.value === null) {
    return 'Mi cuenta'
  }

  return [
    cliente.value.nombre,
    cliente.value.apellido_paterno,
    cliente.value.apellido_materno,
  ]
    .filter((parte): parte is string => parte !== null && parte.length > 0)
    .join(' ')
    || cliente.value.correo
})

const inicialCliente = computed(() => nombreCliente.value.charAt(0).toUpperCase())

function rutaActiva(ruta: 'inicio' | 'membresias' | 'configuracion') {
  if (ruta === 'inicio') {
    return route.path === '/cliente'
  }
  if (ruta === 'membresias') {
    return route.path.startsWith('/cliente/membresias')
  }
  return route.path.startsWith('/cliente/configuracion')
}

function cerrarDrawer() {
  menuMovilAbierto.value = false
}

async function enviarLogout() {
  if (cerrandoSesion.value) {
    return
  }
  cerrandoSesion.value = true
  errorLogout.value = ''

  try {
    await cerrarSesion()
    await navigateTo('/cliente/login', { replace: true })
  } catch {
    errorLogout.value = 'No fue posible cerrar la sesión. Inténtalo nuevamente.'
  } finally {
    cerrandoSesion.value = false
  }
}

function manejarTeclado(event: KeyboardEvent) {
  if (!menuMovilAbierto.value) {
    return
  }
  if (event.key === 'Escape') {
    cerrarDrawer()
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

watch(menuMovilAbierto, async (abierto) => {
  await nextTick()
  if (abierto) {
    botonCerrarMenu.value?.focus()
  } else {
    botonMenu.value?.focus()
  }
})

onMounted(() => window.addEventListener('keydown', manejarTeclado))
onBeforeUnmount(() => window.removeEventListener('keydown', manejarTeclado))

useHead({
  meta: [{ name: 'robots', content: 'noindex, nofollow, noarchive' }],
  link: [
    { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
    { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: 'anonymous' },
    {
      rel: 'stylesheet',
      href: 'https://fonts.googleapis.com/css2?family=Manrope:wght@400..800&display=swap',
    },
  ],
})
</script>

<template>
  <div class="cliente-shell">
    <button
      v-if="menuMovilAbierto"
      class="drawer-backdrop"
      type="button"
      aria-label="Cerrar menú de cliente"
      @click="cerrarDrawer"
    />

    <aside
      id="cliente-sidebar"
      ref="drawer"
      class="cliente-sidebar"
      :class="{ 'is-open': menuMovilAbierto }"
      aria-label="Navegación de cliente"
    >
      <div class="sidebar-top">
        <NuxtLink class="brand-lockup" to="/cliente" @click="cerrarDrawer">
          <span class="brand-mark" aria-hidden="true">SP</span>
          <span class="brand-name-group">
            <span class="brand-name">Smart Parking</span>
            <span class="brand-caption">CUENTA DE CLIENTE</span>
          </span>
        </NuxtLink>

        <button
          ref="botonCerrarMenu"
          class="drawer-close"
          type="button"
          aria-label="Cerrar menú"
          @click="cerrarDrawer"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
            <path d="m6 6 12 12M18 6 6 18" />
          </svg>
        </button>
      </div>

      <nav class="primary-navigation" aria-label="Principal">
        <NuxtLink
          class="navigation-item"
          :class="{ 'is-active': rutaActiva('inicio') }"
          to="/cliente"
          :aria-current="rutaActiva('inicio') ? 'page' : undefined"
          @click="cerrarDrawer"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z" />
          </svg>
          <span>Inicio</span>
        </NuxtLink>
        <NuxtLink
          class="navigation-item"
          :class="{ 'is-active': rutaActiva('membresias') }"
          to="/cliente/membresias"
          :aria-current="rutaActiva('membresias') ? 'page' : undefined"
          @click="cerrarDrawer"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="5" width="18" height="14" rx="2" />
            <path d="M3 10h18M7 15h3" />
          </svg>
          <span>Membresías</span>
        </NuxtLink>
        <NuxtLink
          class="navigation-item"
          :class="{ 'is-active': rutaActiva('configuracion') }"
          to="/cliente/configuracion"
          :aria-current="rutaActiva('configuracion') ? 'page' : undefined"
          @click="cerrarDrawer"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="m19.4 15 .1.1 1.4 1.1-1.4 2.4-1.7-.6a7.8 7.8 0 0 1-1.5.9l-.3 1.8h-2.8l-.3-1.8a7.8 7.8 0 0 1-1.5-.9l-1.7.6-1.4-2.4 1.4-1.1a7.5 7.5 0 0 1 0-1.8l-1.4-1.1 1.4-2.4 1.7.6a7.8 7.8 0 0 1 1.5-.9l.3-1.8h2.8l.3 1.8a7.8 7.8 0 0 1 1.5.9l1.7-.6 1.4 2.4-1.4 1.1a7.5 7.5 0 0 1 0 1.8Z" />
          </svg>
          <span>Mi cuenta</span>
        </NuxtLink>
      </nav>

      <div class="sidebar-footer">
        <div class="cliente-profile">
          <span class="cliente-avatar" aria-hidden="true">{{ inicialCliente }}</span>
          <span class="cliente-copy">
            <span class="cliente-name">{{ nombreCliente }}</span>
            <span class="cliente-email">{{ cliente?.correo }}</span>
          </span>
        </div>

        <p v-if="errorLogout" class="logout-error" role="alert">{{ errorLogout }}</p>
        <button
          class="logout-button"
          type="button"
          :disabled="cerrandoSesion"
          @click="enviarLogout"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M10 17l5-5-5-5M15 12H3M12 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6" />
          </svg>
          <span>{{ cerrandoSesion ? 'Cerrando sesión…' : 'Cerrar sesión' }}</span>
        </button>
      </div>
    </aside>

    <div class="cliente-main">
      <header class="mobile-header">
        <button
          ref="botonMenu"
          class="mobile-menu-toggle"
          type="button"
          aria-label="Abrir menú de cliente"
          aria-controls="cliente-sidebar"
          :aria-expanded="menuMovilAbierto"
          @click="menuMovilAbierto = true"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
            <path d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <span>Smart Parking</span>
      </header>
      <main class="cliente-content">
        <slot />
      </main>
    </div>
  </div>
</template>

<style scoped>
.cliente-shell,
.cliente-shell * { box-sizing: border-box; }
.cliente-shell {
  --cliente-bg: #f7f6f8;
  --cliente-foreground: #29252f;
  --cliente-muted: #746f7b;
  --cliente-border: #e8e5eb;
  --cliente-accent: #5c3a86;
  display: grid;
  min-height: 100vh;
  min-height: 100dvh;
  grid-template-columns: 16.5rem minmax(0, 1fr);
  color: var(--cliente-foreground);
  background: var(--cliente-bg);
  font-family: Manrope, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.cliente-sidebar {
  position: sticky;
  top: 0;
  display: flex;
  height: 100vh;
  min-height: 34rem;
  flex-direction: column;
  padding: 1.75rem 1rem 1rem;
  color: #f8f6fa;
  background: linear-gradient(160deg, #1d1725 0%, #17121e 76%, #15101b 100%);
  border-right: 1px solid rgb(255 255 255 / 7%);
}
.sidebar-top { display: flex; align-items: center; justify-content: space-between; margin: 0 0 2.6rem; padding: 0 .5rem; }
.brand-lockup { display: flex; min-width: 0; align-items: center; gap: .75rem; color: inherit; text-decoration: none; }
.brand-mark { display: grid; width: 2.75rem; height: 2.75rem; flex: 0 0 auto; place-items: center; color: #fff; background: rgb(255 255 255 / 9%); border: 1px solid rgb(255 255 255 / 17%); border-radius: .85rem; font-size: .75rem; font-weight: 800; letter-spacing: .05em; }
.brand-name-group, .cliente-copy { display: grid; min-width: 0; }
.brand-name { overflow: hidden; font-size: .98rem; font-weight: 700; letter-spacing: -.02em; text-overflow: ellipsis; white-space: nowrap; }
.brand-caption { margin-top: .2rem; color: #b7afc0; font-size: .59rem; font-weight: 700; letter-spacing: .12em; }
.drawer-close { display: none; width: 2.5rem; height: 2.5rem; flex: 0 0 auto; place-items: center; color: #f8f6fa; background: transparent; border: 1px solid rgb(255 255 255 / 15%); border-radius: .7rem; cursor: pointer; }
.drawer-close svg { width: 1.2rem; height: 1.2rem; }
.primary-navigation { display: grid; align-content: start; gap: .35rem; }
.navigation-item { display: flex; min-height: 2.8rem; align-items: center; gap: .8rem; padding: .65rem .75rem; color: #c9c3d0; background: transparent; border: 1px solid transparent; border-radius: .75rem; font-size: .88rem; font-weight: 550; text-decoration: none; transition: color 150ms ease, background-color 150ms ease, border-color 150ms ease; }
.navigation-item > svg { width: 1.15rem; height: 1.15rem; flex: 0 0 auto; color: #a79daf; }
.navigation-item:hover, .navigation-item:focus-visible { color: #fff; background: rgb(255 255 255 / 6%); }
.navigation-item.is-active { color: #fff; background: rgb(113 82 150 / 28%); border-color: rgb(166 140 196 / 20%); }
.navigation-item.is-active > svg { color: #cdb9e3; }
.sidebar-footer { display: grid; gap: .8rem; margin-top: auto; padding: 1rem .25rem 0; border-top: 1px solid rgb(255 255 255 / 11%); }
.cliente-profile { display: flex; min-width: 0; align-items: center; gap: .7rem; padding: .35rem .4rem; }
.cliente-avatar { display: grid; width: 2.35rem; height: 2.35rem; flex: 0 0 auto; place-items: center; color: #e8def1; background: rgb(112 81 149 / 38%); border: 1px solid rgb(188 164 211 / 24%); border-radius: 50%; font-size: .9rem; font-weight: 700; }
.cliente-name { overflow: hidden; color: #f8f6fa; font-size: .78rem; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.cliente-email { overflow: hidden; margin-top: .15rem; color: #aaa2b4; font-size: .7rem; text-overflow: ellipsis; white-space: nowrap; }
.logout-button { display: flex; min-height: 2.7rem; align-items: center; gap: .75rem; padding: .6rem .75rem; color: #d6d0dc; background: transparent; border: 1px solid transparent; border-radius: .7rem; font: inherit; font-size: .84rem; font-weight: 550; text-align: left; cursor: pointer; }
.logout-button svg { width: 1.1rem; height: 1.1rem; flex: 0 0 auto; }
.logout-button:hover:not(:disabled), .logout-button:focus-visible { color: #fff; background: rgb(255 255 255 / 7%); }
.logout-button:disabled { cursor: wait; opacity: .72; }
.logout-error { margin: 0; padding: .7rem; color: #eadff2; background: rgb(118 76 126 / 22%); border: 1px solid rgb(188 148 198 / 28%); border-radius: .65rem; font-size: .78rem; line-height: 1.45; }
.cliente-main { min-width: 0; }
.cliente-content { width: min(100%, 92rem); min-width: 0; margin: 0 auto; padding: clamp(1.5rem, 3vw, 2.75rem) clamp(1rem, 3vw, 3rem); }
.mobile-header { display: none; }
.mobile-menu-toggle { display: grid; width: 2.7rem; height: 2.7rem; place-items: center; color: #483a55; background: #fff; border: 1px solid var(--cliente-border); border-radius: .75rem; cursor: pointer; }
.mobile-menu-toggle svg { width: 1.25rem; height: 1.25rem; }
.drawer-backdrop { display: none; }
.brand-lockup:focus-visible, .drawer-close:focus-visible, .navigation-item:focus-visible, .logout-button:focus-visible, .mobile-menu-toggle:focus-visible { outline: 3px solid #bda6d6; outline-offset: 3px; }
@media (max-width: 54rem) {
  .cliente-shell { display: block; }
  .cliente-sidebar { position: fixed; z-index: 30; inset: 0 auto 0 0; width: min(19rem, calc(100vw - 3rem)); min-height: 100vh; visibility: hidden; transform: translateX(-102%); transition: transform 180ms ease, visibility 180ms; }
  .cliente-sidebar.is-open { visibility: visible; transform: translateX(0); }
  .drawer-close { display: grid; }
  .drawer-backdrop { position: fixed; z-index: 20; inset: 0; display: block; background: rgb(19 14 25 / 58%); border: 0; cursor: pointer; }
  .mobile-header { display: flex; min-height: 4.2rem; align-items: center; gap: .8rem; padding: .65rem 1rem; color: #3c3344; background: #fff; border-bottom: 1px solid var(--cliente-border); font-size: .95rem; font-weight: 700; }
  .cliente-content { padding: 1.25rem 1rem 2rem; }
}
@media (prefers-reduced-motion: reduce) { .navigation-item, .cliente-sidebar { transition: none; } }
</style>
