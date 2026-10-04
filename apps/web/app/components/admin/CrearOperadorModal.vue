<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch } from 'vue'

import {
  construirSolicitudCrearOperador,
  mapearErrorOperador,
  obtenerEstadoErrorOperador,
  validarDatosOperador,
  type CampoFormularioOperador,
  type DatosFormularioOperador,
  type ErroresFormularioOperador,
} from '~/utils/operadores'

const props = defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [abierto: boolean]
  created: []
}>()

const { crearOperador } = useOperadores()
const { limpiarSesion } = useSesion()
const { mostrarToast } = useAdminToasts()
const formulario = reactive<DatosFormularioOperador>({
  nombre: '',
  apellido_paterno: '',
  apellido_materno: '',
  correo: '',
})
const erroresCampos = ref<ErroresFormularioOperador>({})
const estado = ref<'listo' | 'enviando' | 'error'>('listo')
const primerCampo = ref<HTMLInputElement | null>(null)
const dialogo = ref<HTMLElement | null>(null)
let elementoAnterior: HTMLElement | null = null
let overflowAnterior = ''

function reiniciarFormulario() {
  formulario.nombre = ''
  formulario.apellido_paterno = ''
  formulario.apellido_materno = ''
  formulario.correo = ''
  erroresCampos.value = {}
  estado.value = 'listo'
}

function cerrarModal() {
  if (estado.value === 'enviando') {
    return
  }
  emit('update:modelValue', false)
}

function alCambiarCampo(campo: CampoFormularioOperador) {
  const erroresRestantes = { ...erroresCampos.value }
  Reflect.deleteProperty(erroresRestantes, campo)
  erroresCampos.value = erroresRestantes
  if (estado.value === 'error') {
    estado.value = 'listo'
  }
}

async function enviarFormulario() {
  if (estado.value === 'enviando') {
    return
  }

  const errores = validarDatosOperador(formulario)
  erroresCampos.value = errores
  if (Object.keys(errores).length > 0) {
    estado.value = 'listo'
    return
  }

  estado.value = 'enviando'

  try {
    await crearOperador(construirSolicitudCrearOperador(formulario))
    emit('created')
    emit('update:modelValue', false)
  } catch (error: unknown) {
    const estadoError = obtenerEstadoErrorOperador(error)
    if (estadoError === 401) {
      limpiarSesion()
      await navigateTo('/login', { replace: true })
      return
    }

    estado.value = 'error'
    const mensaje = mapearErrorOperador(estadoError)
    if (estadoError === 409) {
      erroresCampos.value.correo = mensaje
      return
    }
    mostrarToast(mensaje, 'error')
  }
}

function manejarTeclado(event: KeyboardEvent) {
  if (!props.modelValue) {
    return
  }

  if (event.key === 'Escape') {
    event.preventDefault()
    cerrarModal()
    return
  }

  if (event.key !== 'Tab' || dialogo.value === null) {
    return
  }

  const elementosEnfocables = Array.from(
    dialogo.value.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])',
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

watch(() => props.modelValue, async (abierto) => {
  if (import.meta.server) {
    return
  }

  if (abierto) {
    reiniciarFormulario()
    elementoAnterior = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    overflowAnterior = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', manejarTeclado)
    await nextTick()
    primerCampo.value?.focus()
    return
  }

  document.removeEventListener('keydown', manejarTeclado)
  document.body.style.overflow = overflowAnterior
  await nextTick()
  if (elementoAnterior?.isConnected) {
    elementoAnterior.focus()
  }
})

onBeforeUnmount(() => {
  if (import.meta.client) {
    document.removeEventListener('keydown', manejarTeclado)
    document.body.style.overflow = overflowAnterior
  }
})
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue" class="modal-backdrop" @click.self="cerrarModal">
      <section
        ref="dialogo"
        class="create-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-operator-title"
      >
        <header class="dialog-header">
          <div>
            <p class="eyebrow">Operadores</p>
            <h2 id="create-operator-title">Crear operador</h2>
          </div>
          <button
            class="icon-button"
            type="button"
            aria-label="Cerrar diálogo"
            :disabled="estado === 'enviando'"
            @click="cerrarModal"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <path d="m6 6 12 12M18 6 6 18" />
            </svg>
          </button>
        </header>

        <form class="operator-form" novalidate @submit.prevent="enviarFormulario">
          <div class="field-group">
            <label for="operator-name">Nombre *</label>
            <input
              id="operator-name"
              ref="primerCampo"
              v-model="formulario.nombre"
              name="nombre"
              type="text"
              autocomplete="given-name"
              maxlength="100"
              required
              :aria-invalid="Boolean(erroresCampos.nombre)"
              aria-describedby="operator-name-error"
              @input="alCambiarCampo('nombre')"
            >
            <p v-if="erroresCampos.nombre" id="operator-name-error" class="field-error">
              {{ erroresCampos.nombre }}
            </p>
          </div>

          <div class="field-group">
            <label for="operator-last-name">Apellido paterno *</label>
            <input
              id="operator-last-name"
              v-model="formulario.apellido_paterno"
              name="apellido_paterno"
              type="text"
              autocomplete="family-name"
              maxlength="100"
              required
              :aria-invalid="Boolean(erroresCampos.apellido_paterno)"
              aria-describedby="operator-last-name-error"
              @input="alCambiarCampo('apellido_paterno')"
            >
            <p v-if="erroresCampos.apellido_paterno" id="operator-last-name-error" class="field-error">
              {{ erroresCampos.apellido_paterno }}
            </p>
          </div>

          <div class="field-group">
            <label for="operator-second-last-name">Apellido materno *</label>
            <input
              id="operator-second-last-name"
              v-model="formulario.apellido_materno"
              name="apellido_materno"
              type="text"
              autocomplete="additional-name"
              maxlength="100"
              required
              :aria-invalid="Boolean(erroresCampos.apellido_materno)"
              aria-describedby="operator-second-last-name-error"
              @input="alCambiarCampo('apellido_materno')"
            >
            <p
              v-if="erroresCampos.apellido_materno"
              id="operator-second-last-name-error"
              class="field-error"
            >
              {{ erroresCampos.apellido_materno }}
            </p>
          </div>

          <div class="field-group">
            <label for="operator-email">Correo electrónico *</label>
            <input
              id="operator-email"
              v-model="formulario.correo"
              name="correo"
              type="email"
              inputmode="email"
              autocomplete="email"
              maxlength="320"
              required
              :aria-invalid="Boolean(erroresCampos.correo)"
              aria-describedby="operator-email-error"
              @input="alCambiarCampo('correo')"
            >
            <p v-if="erroresCampos.correo" id="operator-email-error" class="field-error">
              {{ erroresCampos.correo }}
            </p>
          </div>

          <footer class="form-actions">
            <button class="button secondary" type="button" :disabled="estado === 'enviando'" @click="cerrarModal">
              Cancelar
            </button>
            <button class="button primary" type="submit" :disabled="estado === 'enviando'">
              {{ estado === 'enviando' ? 'Creando…' : 'Crear operador' }}
            </button>
          </footer>
        </form>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  z-index: 100;
  inset: 0;
  display: grid;
  overflow-y: auto;
  padding: 1.25rem;
  background: rgb(24 18 31 / 62%);
  place-items: center;
}

.create-dialog {
  width: min(100%, 38rem);
  max-height: min(92vh, 54rem);
  overflow-y: auto;
  padding: clamp(1.25rem, 3vw, 2rem);
  color: #29252f;
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 1rem;
  box-shadow: 0 1.5rem 4.5rem rgb(15 10 21 / 24%);
}

.dialog-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.eyebrow {
  margin: 0 0 0.35rem;
  color: #6b4a89;
  font-size: 0.68rem;
  font-weight: 750;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h2 {
  margin: 0;
  color: #29252f;
  font-size: clamp(1.35rem, 3vw, 1.65rem);
  letter-spacing: -0.035em;
}

.icon-button {
  display: grid;
  width: 2.5rem;
  height: 2.5rem;
  flex: 0 0 auto;
  place-items: center;
  color: #746f7b;
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 0.7rem;
  cursor: pointer;
}

.icon-button:hover:not(:disabled) {
  color: #5c3a86;
  background: #f8f6fa;
  border-color: #d9cde3;
}

.icon-button svg {
  width: 1.2rem;
  height: 1.2rem;
}

.operator-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem 1.1rem;
}

.field-group {
  display: grid;
  min-width: 0;
  align-content: start;
  gap: 0.45rem;
}

label {
  color: #403847;
  font-size: 0.84rem;
  font-weight: 650;
}

input {
  width: 100%;
  min-height: 2.8rem;
  padding: 0.65rem 0.75rem;
  color: #29252f;
  background: #fdfcfe;
  border: 1px solid #ded9e3;
  border-radius: 0.6rem;
  font: inherit;
  font-size: 0.9rem;
  transition: border-color 140ms ease, box-shadow 140ms ease;
}

input:focus {
  border-color: #76569a;
  outline: 3px solid rgb(92 58 134 / 17%);
  outline-offset: 1px;
}

input[aria-invalid="true"] {
  border-color: #76569a;
}

.field-error {
  margin: 0;
  color: #67456e;
  font-size: 0.8rem;
  line-height: 1.4;
}

.form-actions {
  display: flex;
  grid-column: 1 / -1;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.65rem;
  margin-top: 0.35rem;
  padding-top: 1rem;
  border-top: 1px solid #eeeaf0;
}

.button {
  display: inline-flex;
  min-height: 2.75rem;
  align-items: center;
  justify-content: center;
  padding: 0.65rem 0.95rem;
  border: 1px solid transparent;
  border-radius: 0.62rem;
  font: inherit;
  font-size: 0.86rem;
  font-weight: 700;
  cursor: pointer;
  transition: background-color 140ms ease, border-color 140ms ease, color 140ms ease;
}

.button:disabled,
.icon-button:disabled {
  cursor: wait;
  opacity: 0.65;
}

.primary {
  color: #ffffff;
  background: #5c3a86;
  border-color: #5c3a86;
}

.primary:hover:not(:disabled) {
  background: #6c4a97;
  border-color: #6c4a97;
}

.secondary {
  color: #4e4556;
  background: #ffffff;
  border-color: #ded9e3;
}

.secondary:hover:not(:disabled) {
  color: #4d326f;
  background: #f8f6fa;
  border-color: #cfc1dc;
}

.button:focus-visible,
.icon-button:focus-visible {
  outline: 3px solid rgb(92 58 134 / 25%);
  outline-offset: 2px;
}

@media (max-width: 38rem) {
  .modal-backdrop {
    align-items: end;
    padding: 0;
  }

  .create-dialog {
    width: 100%;
    max-height: 94vh;
    padding: 1.25rem 1rem max(1.25rem, env(safe-area-inset-bottom));
    border-radius: 1rem 1rem 0 0;
  }

  .operator-form {
    grid-template-columns: minmax(0, 1fr);
    gap: 0.9rem;
  }

  .form-actions {
    grid-column: auto;
  }

  .form-actions .button {
    flex: 1 1 auto;
  }
}

@media (prefers-reduced-motion: reduce) {
  input,
  .button {
    transition: none;
  }
}
</style>
