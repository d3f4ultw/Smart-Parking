<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { segundosRestantes, type PanelGestionProps } from '~/utils/gestion-propietario'

const props = defineProps<PanelGestionProps>()
const emit = defineEmits<{
  iniciar: [correo: string]
}>()

const correo = ref('')
const campoCorreo = ref<HTMLInputElement | null>(null)
const correoValido = ref(false)
const ahora = ref(0)
let temporizador: ReturnType<typeof setInterval> | undefined

const inscripcionActiva = computed(() => {
  if (props.estado === null) {
    return null
  }

  return props.estado.inscripciones.find((inscripcion) =>
    inscripcion.correo_inicial_enviado
    && inscripcion.estado !== 'completado'
    && inscripcion.estado !== 'expirado'
    && segundosRestantes(
      inscripcion.segundos_proceso,
      props.consultadoEn,
      ahora.value,
    ) > 0,
  ) ?? null
})

const procesoEnCurso = computed(() => inscripcionActiva.value !== null)
const correoPrecargado = computed(() =>
  props.estado?.owner?.correo ?? inscripcionActiva.value?.correo ?? null)
const mensajeEstado = computed(() => {
  if (props.estado === null) {
    return null
  }
  if (props.estado.owner_activo) {
    return 'El dueño está vinculado actualmente.'
  }
  if (procesoEnCurso.value) {
    return 'El correo queda reservado durante los 60 minutos del proceso. Revisa Historial para consultar el estado y reenviar cuando esté disponible.'
  }
  return 'No hay un dueño vinculado. Ingresa el correo para iniciar un nuevo registro.'
})

function actualizarValidezCorreo() {
  correoValido.value = campoCorreo.value?.validity.valid === true
}

watch(correoPrecargado, async (correoGuardado) => {
  if (correoGuardado === null) {
    correo.value = ''
    correoValido.value = false
    return
  }

  correo.value = correoGuardado
  await nextTick()
  actualizarValidezCorreo()
}, { immediate: true })

function solicitarRegistro() {
  if (
    props.estado === null
    || props.cargando
    || props.estado.owner_activo
    || procesoEnCurso.value
  ) {
    return
  }

  const campo = campoCorreo.value
  if (!campo || !campo.checkValidity()) {
    correoValido.value = false
    return
  }

  const normalizado = correo.value.trim().toLowerCase()
  if (normalizado.length < 3) {
    return
  }
  correoValido.value = true
  emit('iniciar', normalizado)
}

onMounted(() => {
  ahora.value = Date.now()
  temporizador = setInterval(() => {
    ahora.value = Date.now()
  }, 1000)
})

onBeforeUnmount(() => {
  if (temporizador !== undefined) {
    clearInterval(temporizador)
  }
})
</script>

<template>
  <section class="action-panel" aria-labelledby="register-title">
    <header class="panel-heading">
      <div>
        <p class="eyebrow">Alta de cuenta</p>
        <h1 id="register-title">Registrar dueño</h1>
      </div>
    </header>

    <form class="registration-form" @submit.prevent="solicitarRegistro">
      <label for="owner-email">Correo del dueño</label>
      <div class="form-row">
        <input
          id="owner-email"
          ref="campoCorreo"
          v-model="correo"
          autocomplete="email"
          inputmode="email"
          name="correo"
          type="email"
          minlength="3"
          maxlength="320"
          required
          :disabled="props.estado === null || props.cargando || props.enviando || props.estado.owner_activo || procesoEnCurso"
          @input="actualizarValidezCorreo"
        >
        <button
          class="primary-button"
          type="submit"
          :disabled="props.estado === null || props.cargando || props.enviando || props.estado.owner_activo || procesoEnCurso || !correoValido"
        >
          {{ props.estado?.owner_activo
            ? 'Dueño vinculado'
            : procesoEnCurso
              ? 'Proceso en curso'
              : props.enviando ? 'Enviando…' : 'Enviar verificación' }}
        </button>
      </div>
      <p v-if="mensajeEstado" class="form-hint" role="status">
        {{ mensajeEstado }}
      </p>
    </form>

    <p v-if="props.cargando" class="loading-copy" role="status">Consultando el estado guardado…</p>
  </section>
</template>

<style scoped>
.action-panel {
  display: grid;
  gap: 1.5rem;
}

.panel-heading h1 {
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

.form-hint,
.loading-copy {
  max-width: 54rem;
  margin: 0.55rem 0 0;
  color: #655d6c;
  font-size: 0.9rem;
  line-height: 1.55;
}

.registration-form {
  display: grid;
  gap: 0.55rem;
  padding: 1.25rem;
  background: #ffffff;
  border: 1px solid #e5e0e9;
  border-radius: 0.85rem;
}

.registration-form label {
  color: #41364b;
  font-size: 0.83rem;
  font-weight: 700;
}

.form-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: stretch;
  gap: 0.65rem;
}

.form-row input {
  width: 100%;
  min-height: 2.8rem;
  padding: 0.65rem 0.75rem;
  color: #2e2735;
  background: #ffffff;
  border: 1px solid #cfc7d7;
  border-radius: 0.6rem;
  font: inherit;
}

.form-row input:focus-visible {
  border-color: #67488b;
  outline: 3px solid rgb(103 72 139 / 18%);
}

.form-row input:disabled {
  color: #746a7c;
  background: #f4f1f7;
  cursor: not-allowed;
}

.primary-button {
  min-height: 2.8rem;
  padding: 0.65rem 1rem;
  color: #ffffff;
  background: #523775;
  border: 1px solid #523775;
  border-radius: 0.6rem;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}

.primary-button:disabled {
  background: #968aa1;
  border-color: #968aa1;
  cursor: not-allowed;
  opacity: 0.72;
}

@media (max-width: 42rem) {
  .form-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .form-row input {
    width: 100%;
  }
}
</style>
