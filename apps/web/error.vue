<script setup lang="ts">
import type { NuxtError } from '#app'

const props = defineProps<{ error: NuxtError }>()
const noEncontrada = computed(() => props.error.statusCode === 404)

useHead({
  title: computed(() =>
    noEncontrada.value
      ? 'Página no encontrada | Smart Parking'
      : 'No pudimos abrir esta página | Smart Parking',
  ),
})

function volverAlInicio() {
  clearError({ redirect: '/' })
}
</script>

<template>
  <UApp>
    <main class="pagina-error" aria-labelledby="titulo-error">
      <section class="tarjeta-error">
        <header class="identidad-error" aria-label="Smart Parking">
          <p class="marca-error">SMART PARKING</p>
          <div class="simbolo-error" aria-hidden="true">
            <UIcon name="i-lucide-square-parking" />
          </div>
          <p class="lema-error">Control claro para tu estacionamiento.</p>
        </header>

        <div class="contenido-error">
          <p class="sobrelinea-error">Smart Parking</p>
          <h1 id="titulo-error">
            {{ noEncontrada ? 'No encontramos esta página' : 'No pudimos abrir esta página' }}
          </h1>
          <p class="mensaje-error">
            {{
              noEncontrada
                ? 'Revisa la dirección o vuelve al inicio.'
                : 'Vuelve al inicio e inténtalo de nuevo.'
            }}
          </p>
          <UButton @click="volverAlInicio">Volver al inicio</UButton>
        </div>
      </section>
    </main>
  </UApp>
</template>

<style scoped>
.pagina-error {
  display: grid;
  min-height: 100vh;
  padding: clamp(16px, 4vw, 48px);
  place-items: center;
}

.tarjeta-error {
  display: grid;
  grid-template-columns: minmax(0, 0.85fr) minmax(0, 1.15fr);
  width: min(100%, 64rem);
  min-height: 27rem;
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: 1.5rem;
  background: var(--app-surface);
  box-shadow: 0 24px 80px rgb(41 37 47 / 8%);
}

.identidad-error {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: clamp(28px, 5vw, 56px);
  background: var(--sidebar-gradient);
  color: #fff;
}

.marca-error {
  margin: 0;
  color: #e9e2f0;
  font-size: 0.8rem;
  font-weight: 750;
  letter-spacing: 0.1em;
}

.simbolo-error {
  display: grid;
  width: 4rem;
  height: 4rem;
  margin: auto 0;
  place-items: center;
  border: 1px solid rgb(255 255 255 / 20%);
  border-radius: 1.25rem;
  background: rgb(255 255 255 / 8%);
}

.simbolo-error :deep(svg) {
  width: 2rem;
  height: 2rem;
}

.lema-error {
  max-width: 24ch;
  margin: 0;
  color: #d0c8d7;
  font-size: 1.1rem;
  line-height: 1.6;
}

.contenido-error {
  display: grid;
  align-content: center;
  justify-items: start;
  gap: 16px;
  padding: clamp(28px, 5vw, 64px);
}

.sobrelinea-error {
  margin: 0;
  color: var(--app-muted);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.contenido-error h1 {
  max-width: 16ch;
  margin: 0;
  color: var(--app-foreground);
  font-size: clamp(1.8rem, 4vw, 2.4rem);
  font-weight: 650;
  letter-spacing: -0.04em;
  line-height: 1.12;
}

.mensaje-error {
  margin: 0 0 8px;
  color: var(--app-muted);
  font-size: 1rem;
  line-height: 1.6;
}

@media (max-width: 640px) {
  .tarjeta-error {
    grid-template-columns: 1fr;
    min-height: 0;
  }

  .identidad-error {
    min-height: 13rem;
  }

  .simbolo-error {
    margin: 24px 0;
  }
}
</style>
