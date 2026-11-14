<script setup lang="ts">
const route = useRoute()
const enPortal = computed(() => route.path === '/clientes/portal')
</script>

<template>
  <div class="layout-cliente">
    <header v-if="!enPortal" class="barra-cliente">
      <NuxtLink class="marca-cliente" to="/" aria-label="Smart Parking, inicio">
        <span class="simbolo-marca" aria-hidden="true">
          <UIcon name="i-lucide-square-parking" />
        </span>
        <span>SMART PARKING</span>
      </NuxtLink>
      <nav class="nav-cliente" aria-label="Navegación de cliente">
        <NuxtLink to="/clientes/acceso">Iniciar sesión</NuxtLink>
        <NuxtLink class="enlace-destacado" to="/clientes/registro">Crear cuenta</NuxtLink>
      </nav>
    </header>
    <slot />
    <footer v-if="!enPortal" class="pie-cliente">
      <span>Smart Parking</span>
      <span>Acceso personal</span>
    </footer>
  </div>
</template>

<style scoped>
.layout-cliente {
  display: flex;
  min-height: 100vh;
  flex-direction: column;
  color: var(--app-foreground);
  font-family: 'Manrope Variable', ui-sans-serif, system-ui, sans-serif;
}
.barra-cliente {
  display: flex;
  min-height: 76px;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  border-bottom: 1px solid var(--app-border);
  background: var(--app-surface);
  padding: 12px clamp(20px, 5vw, 72px);
}
.marca-cliente {
  display: inline-flex;
  min-height: 44px;
  align-items: center;
  gap: 10px;
  color: var(--app-foreground);
  font-size: 0.83rem;
  font-weight: 800;
  letter-spacing: 0.09em;
  text-decoration: none;
}
.simbolo-marca {
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  border-radius: 10px;
  background: color-mix(in srgb, var(--app-primary) 9%, var(--app-surface));
  color: var(--app-primary);
  font-size: 1.2rem;
}
.nav-cliente {
  display: flex;
  align-items: center;
  gap: 10px;
}
.nav-cliente a {
  display: inline-flex;
  min-height: 42px;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  padding: 0 14px;
  color: var(--app-foreground);
  font-size: 0.9rem;
  font-weight: 650;
  text-decoration: none;
}
.nav-cliente a:hover {
  background: var(--app-surface-hover);
}
.nav-cliente .enlace-destacado {
  background: var(--app-primary);
  color: white;
}
.nav-cliente .enlace-destacado:hover {
  background: var(--app-primary-hover);
}
.pie-cliente {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  border-top: 1px solid var(--app-border);
  margin-top: auto;
  padding: 22px clamp(20px, 5vw, 72px);
  color: var(--app-muted);
  font-size: 0.8rem;
}
@media (max-width: 38rem) {
  .barra-cliente {
    min-height: 68px;
    padding-inline: 16px;
  }
  .marca-cliente {
    gap: 7px;
    font-size: 0.72rem;
  }
  .nav-cliente {
    gap: 0;
  }
  .nav-cliente a {
    padding-inline: 9px;
    font-size: 0.8rem;
  }
  .pie-cliente {
    padding-inline: 16px;
  }
}
</style>
