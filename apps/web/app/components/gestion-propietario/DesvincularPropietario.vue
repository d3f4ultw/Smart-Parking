<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  formatearDuracion,
  segundosRestantes,
  type PanelGestionProps,
} from '~/utils/gestion-propietario'

const props = defineProps<PanelGestionProps>()
const emit = defineEmits<{ solicitar: [contrasenaAdmin: string] }>()
const contrasenaAdmin = ref('')
const contrasenaVisible = ref(false)
const ahora = ref(0)
const segundosEnlaceRestantes = computed(() => segundosRestantes(
  props.estado?.desvinculacion_segundos_restantes ?? 0,
  props.consultadoEn,
  ahora.value,
))
const enlaceVigente = computed(() => segundosEnlaceRestantes.value > 0)
const textoBoton = computed(() => {
  if (props.enviando) {
    return 'Enviando…'
  }
  if (enlaceVigente.value) {
    return `Enlace activo · ${formatearDuracion(segundosEnlaceRestantes.value)}`
  }
  return 'Enviar confirmación'
})
let temporizadorCuentaRegresiva: ReturnType<typeof setInterval> | undefined

watch(enlaceVigente, (vigente) => {
  if (vigente) {
    contrasenaAdmin.value = ''
    contrasenaVisible.value = false
  }
})

function enviarSolicitud() {
  if (
    props.enviando
    || enlaceVigente.value
    || !props.estado?.owner
    || contrasenaAdmin.value.length === 0
  ) {
    return
  }

  emit('solicitar', contrasenaAdmin.value)
  contrasenaAdmin.value = ''
  contrasenaVisible.value = false
}

onMounted(() => {
  ahora.value = Date.now()
  temporizadorCuentaRegresiva = setInterval(() => {
    ahora.value = Date.now()
  }, 1000)
})

onBeforeUnmount(() => {
  if (temporizadorCuentaRegresiva !== undefined) {
    clearInterval(temporizadorCuentaRegresiva)
  }
})
</script>

<template>
  <section class="action-panel" aria-labelledby="unlink-title">
    <header>
      <p class="eyebrow">Acción protegida</p>
      <h1 id="unlink-title">Desvincular dueño</h1>
    </header>

    <p v-if="cargando && estado === null" class="state-copy" role="status">
      Consultando el dueño actual…
    </p>
    <p v-else-if="estado !== null && estado.owner === null" class="state-copy" role="status">
      No hay un dueño vinculado.
    </p>

    <div v-if="estado?.owner" class="owner-card">
      <p>Se enviará el enlace de confirmación a:</p>
      <strong>{{ estado.owner.nombre }}</strong>
      <span>{{ estado.owner.correo }}</span>
    </div>

    <form
      v-if="estado?.owner"
      class="unlink-form"
      @submit.prevent="enviarSolicitud"
    >
      <label for="owner-admin-password">Contraseña administrativa independiente</label>
      <div class="password-control">
        <input
          id="owner-admin-password"
          v-model="contrasenaAdmin"
          :type="contrasenaVisible ? 'text' : 'password'"
          autocomplete="current-password"
          :disabled="enlaceVigente || enviando || cargando"
          maxlength="128"
          name="contrasena_admin"
          required
        >
        <button
          class="password-toggle"
          type="button"
          :aria-label="contrasenaVisible ? 'Ocultar contraseña' : 'Mostrar contraseña'"
          :title="contrasenaVisible ? 'Ocultar contraseña' : 'Mostrar contraseña'"
          :aria-pressed="contrasenaVisible"
          aria-controls="owner-admin-password"
          :disabled="enlaceVigente || enviando || cargando"
          @click="contrasenaVisible = !contrasenaVisible"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" />
            <circle v-if="!contrasenaVisible" cx="12" cy="12" r="3" />
            <path v-else d="m3 3 18 18" />
          </svg>
        </button>
      </div>
      <p class="hint">
        El cambio se completará al abrir el enlace enviado al correo del dueño.
        El enlace dura 15 minutos.
      </p>
      <button class="primary-button" type="submit" :disabled="enviando || cargando || enlaceVigente">
        {{ textoBoton }}
      </button>
    </form>
  </section>
</template>

<style scoped>
.action-panel {
  display: grid;
  gap: 1rem;
}

h1 {
  margin: 0;
  color: #30263b;
  font-size: clamp(1.5rem, 3vw, 2rem);
  letter-spacing: -0.03em;
}

.eyebrow {
  margin: 0 0 0.35rem;
  color: #74647f;
  font-size: 0.69rem;
  font-weight: 750;
  letter-spacing: 0.11em;
  text-transform: uppercase;
}

.state-copy,
.owner-card,
.unlink-form {
  margin: 0;
  padding: 1rem;
  border: 1px solid #ded6e7;
  border-radius: 0.65rem;
  background: #ffffff;
}

.owner-card {
  display: grid;
  gap: 0.3rem;
  color: #443653;
}

.owner-card p {
  margin: 0 0 0.35rem;
  color: #655d6c;
}

.owner-card span {
  color: #655d6c;
  overflow-wrap: anywhere;
}

.unlink-form {
  display: grid;
  gap: 0.7rem;
}

label {
  color: #443653;
  font-size: 0.9rem;
  font-weight: 650;
}

input {
  min-width: 0;
  padding: 0.7rem 0.8rem;
  border: 1px solid #cfc7d8;
  border-radius: 0.5rem;
  color: #30263b;
  font: inherit;
}

.password-control {
  position: relative;
}

.password-control input {
  width: 100%;
  padding-right: 3.1rem;
}

.password-toggle {
  position: absolute;
  top: 50%;
  right: 0.35rem;
  display: grid;
  width: 2.25rem;
  height: 2.25rem;
  padding: 0.45rem;
  color: #5c3a86;
  background: transparent;
  border: 0;
  border-radius: 0.4rem;
  place-items: center;
  transform: translateY(-50%);
  cursor: pointer;
}

.password-toggle svg {
  width: 1.25rem;
  height: 1.25rem;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.8;
}

.password-toggle:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

input:focus-visible,
button:focus-visible {
  outline: 3px solid rgb(92 58 134 / 24%);
  outline-offset: 2px;
}

input:disabled {
  background: #f8f6fa;
  cursor: not-allowed;
  opacity: 0.72;
}

.hint {
  margin: 0;
  color: #655d6c;
  font-size: 0.84rem;
  line-height: 1.5;
}

.primary-button {
  justify-self: start;
  padding: 0.7rem 1rem;
  border: 0;
  border-radius: 0.5rem;
  color: #ffffff;
  background: #5c3a86;
  font: inherit;
  font-weight: 650;
  cursor: pointer;
}

.primary-button:disabled {
  cursor: not-allowed;
  opacity: 0.65;
}
</style>
