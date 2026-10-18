<script setup lang="ts">
definePageMeta({
  layout: 'admin',
  middleware: 'sesion-owner',
})

const route = useRoute()
</script>

<template>
  <NuxtPage v-if="route.path === '/admin/vision/monitoreo/camara'" />
  <main v-else class="monitoring-page">
    <section class="monitoring-card" aria-labelledby="monitoring-title">
      <p class="monitoring-eyebrow">VISION IA</p>
      <h1 id="monitoring-title">Monitoreo Vision</h1>
      <p class="monitoring-description">
        Visualiza las detecciones de vehículos y los cajones desde la cámara.
      </p>
      <a
        class="monitoring-action"
        href="/admin/vision/monitoreo/camara"
        target="_blank"
        rel="noopener"
      >
        Abrir cámara en vivo
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <path d="m10 9 5 3-5 3z" />
        </svg>
      </a>
    </section>
  </main>
</template>

<style scoped>
.monitoring-page {
  display: grid;
  min-height: clamp(30rem, 78vh, 56rem);
  align-content: stretch;
  padding-block: clamp(1rem, 3vh, 2.5rem);
}

.monitoring-card {
  display: grid;
  align-content: center;
  justify-items: center;
  gap: clamp(1rem, 2vh, 1.5rem);
  width: 100%;
  min-height: 100%;
  padding: clamp(2rem, 6vw, 5rem);
  background: #ffffff;
  border: 1px solid #e7e1eb;
  border-radius: 1rem;
  box-shadow: 0 0.5rem 1.5rem rgb(43 29 54 / 5%);
  text-align: center;
}

.monitoring-eyebrow {
  margin: 0;
  color: #72558a;
  font-size: 0.7rem;
  font-weight: 750;
  letter-spacing: 0.14em;
}

h1 {
  margin: 0;
  color: #302637;
  font-size: clamp(2rem, 5vw, 3.5rem);
  letter-spacing: -0.035em;
}

.monitoring-description {
  max-width: 48rem;
  margin: 0;
  color: #695f70;
  font-size: clamp(1rem, 1.6vw, 1.25rem);
  line-height: 1.65;
}

.monitoring-action {
  display: inline-flex;
  min-height: 3.25rem;
  align-items: center;
  justify-content: center;
  gap: 0.65rem;
  margin-top: 0.5rem;
  padding: 0.85rem 1.25rem;
  color: #ffffff;
  background: #694887;
  border: 1px solid #694887;
  border-radius: 0.7rem;
  font-size: 0.9rem;
  font-weight: 700;
  text-decoration: none;
  transition: background-color 150ms ease, border-color 150ms ease;
}

.monitoring-action:hover {
  background: #583b73;
  border-color: #583b73;
}

.monitoring-action:focus-visible {
  outline: 3px solid #c8b3db;
  outline-offset: 3px;
}

.monitoring-action svg {
  width: 1.1rem;
  height: 1.1rem;
}

@media (prefers-reduced-motion: reduce) {
  .monitoring-action {
    transition: none;
  }
}

@media (max-width: 620px) {
  .monitoring-page {
    min-height: clamp(22rem, 64vh, 34rem);
  }

  .monitoring-card {
    padding: clamp(1.5rem, 7vw, 2.25rem);
  }

  h1 {
    font-size: clamp(1.8rem, 9vw, 2.5rem);
  }

  .monitoring-action {
    width: min(100%, 22rem);
  }
}
</style>
