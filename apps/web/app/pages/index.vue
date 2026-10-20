<script setup lang="ts">
import { ref } from 'vue'

const mostrarAvisoRegistro = ref(false)

useHead({
  title: 'Smart Parking',
  meta: [
    {
      name: 'description',
      content: 'Gestión de estacionamientos y membresías en un solo lugar.',
    },
  ],
})
</script>

<template>
  <main class="landing" aria-labelledby="landing-title">
    <div class="landing__content">
      <span class="landing__detail" aria-hidden="true" />
      <h1 id="landing-title">Smart Parking</h1>
      <p class="landing__description">
        Gestión de estacionamientos y membresías en un solo lugar.
      </p>

      <nav class="landing__actions" aria-label="Acceso a Smart Parking">
        <NuxtLink class="landing__action landing__action--primary" to="/login">
          Iniciar sesión
        </NuxtLink>
        <button
          class="landing__action landing__action--secondary"
          type="button"
          @click="mostrarAvisoRegistro = true"
        >
          Registrarse
        </button>
      </nav>

      <p v-if="mostrarAvisoRegistro" class="landing__notice" role="status">
        Registro próximamente
      </p>
    </div>
  </main>
</template>

<style scoped>
.landing {
  --landing-background: #faf9fb;
  --landing-foreground: #28232e;
  --landing-muted: #6e6873;
  --landing-border: #d9d4df;
  --landing-accent: #5c3a86;
  --landing-accent-hover: #4d2f74;
  --landing-on-accent: #fff;

  position: fixed;
  inset: 0;
  display: grid;
  min-height: 100vh;
  min-height: 100dvh;
  overflow-y: auto;
  place-items: center;
  padding: clamp(1.5rem, 6vw, 5rem) 1.25rem;
  background: var(--landing-background);
  color: var(--landing-foreground);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.landing,
.landing * {
  box-sizing: border-box;
}

.landing__content {
  width: min(100%, 42rem);
  text-align: center;
}

.landing__detail {
  display: block;
  width: 2rem;
  height: 0.2rem;
  margin: 0 auto 1.5rem;
  border-radius: 999px;
  background: var(--landing-accent);
}

.landing h1 {
  margin: 0;
  font-size: clamp(2.5rem, 8vw, 5rem);
  font-weight: 650;
  letter-spacing: -0.065em;
  line-height: 1;
}

.landing__description {
  max-width: 30rem;
  margin: 1.25rem auto 2rem;
  color: var(--landing-muted);
  font-size: clamp(1rem, 2.5vw, 1.125rem);
  line-height: 1.6;
}

.landing__actions {
  display: flex;
  justify-content: center;
  gap: 0.75rem;
}

.landing__action {
  display: inline-flex;
  min-width: 11.5rem;
  min-height: 3rem;
  align-items: center;
  justify-content: center;
  padding: 0.75rem 1.25rem;
  border: 1px solid transparent;
  border-radius: 0.625rem;
  cursor: pointer;
  font-family: inherit;
  font-size: 0.9rem;
  font-weight: 700;
  line-height: 1.25;
  text-decoration: none;
}

.landing__action:focus-visible {
  outline: 3px solid var(--landing-accent);
  outline-offset: 3px;
}

.landing__action--primary {
  background: var(--landing-accent);
  color: var(--landing-on-accent);
}

.landing__action--primary:hover {
  background: var(--landing-accent-hover);
}

.landing__action--secondary {
  border-color: var(--landing-border);
  background: transparent;
  color: var(--landing-foreground);
}

.landing__action--secondary:hover {
  border-color: var(--landing-accent);
  color: var(--landing-accent);
}

.landing__notice {
  margin: 0.875rem 0 0;
  color: var(--landing-muted);
  font-size: 0.875rem;
}

@media (max-width: 32rem) {
  .landing__actions {
    width: min(100%, 22rem);
    margin-inline: auto;
    flex-direction: column;
  }

  .landing__action {
    width: 100%;
  }
}
</style>
