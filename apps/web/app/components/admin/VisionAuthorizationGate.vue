<script setup lang="ts">
const props = withDefaults(defineProps<{
  titulo?: string
  descripcion?: string
  pantallaCompleta?: boolean
}>(), {
  titulo: 'Acceso protegido',
  descripcion: 'Ingresa la contraseña administrativa para continuar.',
  pantallaCompleta: false,
})

const vision = useVisionAuthorization()
const contrasena = ref('')
const enviando = ref(false)
const reintentando = ref(false)
const error = ref('')

async function enviar() {
  if (enviando.value || contrasena.value.length === 0) return
  enviando.value = true
  error.value = ''
  const valor = contrasena.value
  contrasena.value = ''
  try {
    await vision.verificar(valor)
  } catch (fallo: unknown) {
    const http = fallo !== null && typeof fallo === 'object'
      ? fallo as { status?: unknown; statusCode?: unknown }
      : {}
    error.value = http.status === 429 || http.statusCode === 429
      ? 'Has intentado varias veces. Espera un momento y vuelve a intentarlo.'
      : 'La contraseña administrativa no es correcta. Inténtalo otra vez.'
  } finally {
    enviando.value = false
  }
}

async function actualizarAutorizacion() {
  if (reintentando.value) return
  reintentando.value = true
  try {
    await vision.actualizar()
  } finally {
    reintentando.value = false
  }
}

onMounted(() => {
  void actualizarAutorizacion()
})
</script>

<template>
  <slot v-if="vision.autorizado.value" />
  <section
    v-else-if="vision.estado.value.state === 'loading'"
    class="vision-gate-loading"
    :class="{ 'vision-gate-loading--pantalla-completa': props.pantallaCompleta }"
    :aria-label="props.pantallaCompleta ? 'Cargando contenido de Vision' : undefined"
    role="status"
    aria-live="polite"
  >
    <span v-if="!props.pantallaCompleta">Preparando la vista…</span>
  </section>
  <section
    v-else-if="vision.estado.value.state === 'error'"
    class="vision-gate vision-gate--recovery"
    :class="{ 'vision-gate--recovery-fullscreen': props.pantallaCompleta }"
    aria-labelledby="vision-gate-recovery-title"
    role="alert"
  >
    <div class="vision-gate-copy">
      <p class="vision-eyebrow">VISION IA</p>
      <h2 id="vision-gate-recovery-title">No pudimos abrir esta vista</h2>
      <p>Hubo un problema momentáneo. Inténtalo de nuevo.</p>
      <button
        class="vision-primary-button"
        type="button"
        :disabled="reintentando"
        @click="actualizarAutorizacion"
      >
        {{ reintentando ? 'Reintentando…' : 'Intentar de nuevo' }}
      </button>
    </div>
  </section>
  <section v-else class="vision-gate" :class="{ 'vision-gate--pantalla-completa': props.pantallaCompleta }" aria-labelledby="vision-gate-title">
    <div class="vision-gate-copy">
      <p class="vision-eyebrow">VISION IA</p>
      <h2 id="vision-gate-title">{{ props.titulo }}</h2>
      <p>{{ props.descripcion }}</p>
      <form class="vision-gate-form" @submit.prevent="enviar">
        <label for="vision-admin-password">Contraseña administrativa</label>
        <input
          id="vision-admin-password"
          v-model="contrasena"
          type="password"
          autocomplete="current-password"
          maxlength="128"
          required
          :disabled="enviando"
        >
        <p v-if="error" class="vision-inline-error" role="alert">{{ error }}</p>
        <button class="vision-primary-button" type="submit" :disabled="enviando || contrasena.length === 0">
          {{ enviando ? 'Un momento…' : 'Continuar' }}
        </button>
      </form>
    </div>
  </section>
</template>

<style scoped>
.vision-gate,
.vision-gate-loading {
  box-sizing: border-box;
  width: min(100%, 31rem);
  margin: clamp(2rem, 8vh, 4.5rem) auto;
  padding: clamp(1.25rem, 4vw, 1.75rem);
  border: 1px solid var(--admin-border);
  border-radius: 1rem;
  background: var(--admin-surface);
  font-family: Manrope, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
}

.vision-gate--pantalla-completa,
.vision-gate--recovery-fullscreen,
.vision-gate-loading--pantalla-completa {
  --admin-foreground: #29252f;
  --admin-muted: #746f7b;
  --admin-subtle: #98929f;
  --admin-border: #e8e5eb;
  --admin-surface: #ffffff;
  --admin-surface-soft: #f8f7f9;
  --admin-accent: #5c3a86;
  --admin-accent-hover: #6c4a97;
  --admin-focus: rgb(92 58 134 / 22%);
  display: grid;
  box-sizing: border-box;
  width: 100%;
  min-height: 100dvh;
  place-items: center;
  margin: 0;
  padding: clamp(1rem, 4vw, 3rem);
  border: 0;
  border-radius: 0;
  color: var(--admin-foreground);
  background: #f6f5f7;
  color-scheme: light;
  font-family: Manrope, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
}

.vision-gate-loading--pantalla-completa {
  display: flex;
  padding: 1rem;
  font-size: 0;
}

.vision-gate-loading--pantalla-completa::before {
  width: 1rem;
  height: 1rem;
  flex: 0 0 1rem;
  border: 2px solid #e8e5eb;
  border-top-color: #5c3a86;
  border-radius: 50%;
  content: '';
  animation: vision-loading-spin .7s linear infinite;
}

.vision-gate--pantalla-completa .vision-gate-copy,
.vision-gate--recovery-fullscreen .vision-gate-copy {
  box-sizing: border-box;
  width: min(100%, 31rem);
  padding: clamp(1.5rem, 5vw, 2.25rem);
  border: 1px solid var(--admin-border);
  border-radius: 1rem;
  background: var(--admin-surface);
  box-shadow: 0 1.25rem 3rem rgb(41 37 47 / 8%);
}

.vision-gate-copy {
  min-width: 0;
}

.vision-eyebrow {
  margin: 0 0 .55rem;
  color: var(--admin-accent);
  font-size: .7rem;
  font-weight: 750;
  letter-spacing: .12em;
}

h2 {
  margin: 0;
  color: var(--admin-foreground);
  font-size: clamp(1.35rem, 3vw, 1.65rem);
  font-weight: 750;
  line-height: 1.3;
  letter-spacing: -.025em;
}

.vision-gate-copy > p:not(.vision-eyebrow) {
  margin: .65rem 0 0;
  color: var(--admin-muted);
  line-height: 1.55;
}

.vision-gate-form {
  display: grid;
  gap: .65rem;
  margin-top: 1.5rem;
}

.vision-gate-form label {
  color: var(--admin-foreground);
  font-size: .84rem;
  font-weight: 650;
}

.vision-gate-form input {
  box-sizing: border-box;
  width: 100%;
  min-height: 2.75rem;
  padding: .6rem .75rem;
  color: var(--admin-foreground);
  background: var(--admin-surface);
  border: 1px solid var(--admin-border);
  border-radius: .6rem;
  font: inherit;
}

.vision-gate-form input:focus-visible {
  border-color: var(--admin-accent);
  outline: 3px solid var(--admin-focus);
}

.vision-primary-button {
  min-height: 2.75rem;
  margin-top: .2rem;
  padding: 0 1rem;
  color: #fff;
  background: var(--admin-accent);
  border: 0;
  border-radius: .6rem;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}

.vision-primary-button:hover:not(:disabled) {
  background: var(--admin-accent-hover);
}

.vision-primary-button:focus-visible {
  outline: 3px solid var(--admin-focus);
  outline-offset: 2px;
}

.vision-primary-button:disabled {
  color: var(--admin-subtle);
  background: var(--admin-surface-soft);
  border: 1px solid var(--admin-border);
  cursor: not-allowed;
}

.vision-inline-error {
  margin: 0;
  color: #9a343f;
  font-size: .86rem;
}

.vision-gate--recovery .vision-primary-button {
  margin-top: 1rem;
}

@keyframes vision-loading-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .vision-gate-loading--pantalla-completa::before {
    animation: none;
  }
}
</style>
