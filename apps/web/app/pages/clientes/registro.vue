<script setup lang="ts">
import FormularioAcceso from '~/components/clientes/FormularioAcceso.vue'

/** Muestra el mismo formulario de acceso en modo de creación de cuenta. */
definePageMeta({ layout: 'cliente', middleware: 'cliente-sesion' })
useHead({
  title: 'Crear cuenta | Smart Parking',
  meta: [{ name: 'referrer', content: 'no-referrer' }],
})
</script>

<template>
  <main class="pagina-registro-cliente">
    <section class="tarjeta-registro-cliente" aria-labelledby="titulo-registro">
      <header class="encabezado-registro-cliente">
        <span class="icono-registro" aria-hidden="true">
          <UIcon name="i-lucide-user-round-plus" />
        </span>
        <div>
          <p class="sobrelinea-cliente">Portal personal</p>
          <h1 id="titulo-registro">Crear cuenta</h1>
        </div>
      </header>
      <FormularioAcceso modo="registro" />
    </section>
  </main>
</template>

<style scoped>
.pagina-registro-cliente {
  display: grid;
  flex: 1;
  place-items: center;
  padding: 38px 20px 56px;
}
.tarjeta-registro-cliente {
  width: min(100%, 38rem);
  border: 1px solid var(--app-border);
  border-radius: 16px;
  background: var(--app-surface);
  padding: clamp(24px, 5vw, 40px);
}
.encabezado-registro-cliente {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 26px;
}
.icono-registro {
  display: grid;
  width: 48px;
  height: 48px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 13px;
  background: color-mix(in srgb, var(--app-primary) 9%, var(--app-surface));
  color: var(--app-primary);
  font-size: 1.3rem;
}
.sobrelinea-cliente {
  margin: 0;
  color: var(--app-primary);
  font-size: 0.75rem;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
h1 {
  margin: 4px 0 0;
  font-size: clamp(1.85rem, 5vw, 2.25rem);
  letter-spacing: -0.045em;
}
</style>
