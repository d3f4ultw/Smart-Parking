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
      ? 'Se alcanzó el límite de intentos. Espera antes de volver a probar.'
      : 'La contraseña administrativa no es válida.'
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
    <span v-if="!props.pantallaCompleta">Verificando autorización de Vision…</span>
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
      <h2 id="vision-gate-recovery-title">No se pudo verificar la autorización</h2>
      <p>No se pudo verificar la autorización por un problema de conexión. Reintenta para continuar.</p>
      <button
        class="vision-primary-button"
        type="button"
        :disabled="reintentando"
        @click="actualizarAutorizacion"
      >
        {{ reintentando ? 'Reintentando…' : 'Reintentar verificación' }}
      </button>
    </div>
  </section>
  <section v-else class="vision-gate" aria-labelledby="vision-gate-title">
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
          {{ enviando ? 'Verificando…' : 'Entrar' }}
        </button>
      </form>
      <p class="vision-gate-note">La autorización dura solo esta sesión de OWNER.</p>
    </div>
  </section>
</template>

<style scoped>
.vision-gate,
.vision-gate-loading {
  width: min(100%, 31rem);
  margin: clamp(2rem, 8vh, 4.5rem) auto;
  padding: clamp(1.25rem, 4vw, 1.75rem);
  border: 1px solid var(--admin-border);
  border-radius: 1rem;
  background: var(--admin-surface);
}

.vision-gate-loading--pantalla-completa {
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  width: 100%;
  height: 100dvh;
  margin: 0;
  padding: 1rem;
  border: 0;
  border-radius: 0;
  color: #9caabd;
  background: #0d1118;
  font-size: 0;
}

.vision-gate-loading--pantalla-completa::before {
  width: 1rem;
  height: 1rem;
  flex: 0 0 1rem;
  border: 2px solid #384454;
  border-top-color: #72b9f4;
  border-radius: 50%;
  content: '';
  animation: vision-loading-spin .7s linear infinite;
}

.vision-gate--recovery-fullscreen {
  display: grid;
  align-content: center;
  box-sizing: border-box;
  width: 100%;
  min-height: 100dvh;
  margin: 0;
}

.vision-gate--recovery .vision-primary-button {
  margin-top: .5rem;
}

@keyframes vision-loading-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .vision-gate-loading--pantalla-completa::before {
    animation: none;
  }
}

.vision-gate-copy {
  min-width: 0;
}

.vision-eyebrow {
  margin: 0 0 .5rem;
  color: var(--admin-accent);
  font-size: .7rem;
  font-weight: 750;
  letter-spacing: .12em;
}

h2 {
  margin: 0;
  color: var(--admin-foreground);
  font-size: 1.2rem;
  line-height: 1.35;
}

.vision-gate-copy > p:not(.vision-eyebrow) {
  color: var(--admin-muted);
  line-height: 1.5;
}

.vision-gate-form {
  display: grid;
  gap: .6rem;
  margin-top: 1.25rem;
}

.vision-gate-form label {
  color: var(--admin-foreground);
  font-size: .84rem;
  font-weight: 650;
}

.vision-gate-form input {
  min-height: 2.75rem;
  padding: .6rem .75rem;
  color: var(--admin-foreground);
  background: var(--admin-surface-soft);
  border: 1px solid var(--admin-border);
  border-radius: .6rem;
  font: inherit;
}

.vision-gate-form input:focus-visible {
  border-color: var(--admin-accent);
  outline: 3px solid var(--admin-focus);
}

.vision-primary-button {
  min-height: 2.65rem;
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
  color: var(--admin-accent);
  background: var(--admin-surface-soft);
  border: 1px solid var(--admin-border);
  cursor: not-allowed;
}

.vision-inline-error {
  margin: 0;
  color: #9a343f;
  font-size: .86rem;
}

.vision-gate-note {
  margin: 1rem 0 0;
  color: var(--admin-subtle);
  font-size: .75rem;
}
</style>
