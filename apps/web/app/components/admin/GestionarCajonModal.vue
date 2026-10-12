<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  crearSolicitudEstadoOperativo,
  ETIQUETAS_ESTADO_EFECTIVO,
  ETIQUETAS_ESTADO_FISICO,
  ETIQUETAS_ESTADO_OPERATIVO,
  type Cajon,
  type EstadoOperativoCajon,
  type SolicitudEstadoOperativoCajon,
} from '~/utils/cajones'

const props = defineProps<{
  modelValue: boolean
  cajon: Cajon
  procesando: boolean
  reconciliacionPendiente: boolean
  errorGuardado: string | null
}>()

const emit = defineEmits<{
  'update:modelValue': [abierto: boolean]
  guardar: [cajonId: number, solicitud: SolicitudEstadoOperativoCajon]
  'reintentar-sincronizacion': []
  'limpiar-error': []
}>()

const dialogo = ref<HTMLElement | null>(null)
const selectorEstado = ref<HTMLSelectElement | null>(null)
const estadoBase = ref<EstadoOperativoCajon>(props.cajon.estado_operativo)
const motivoBase = ref<string | null>(props.cajon.motivo_operativo)
const estadoBorrador = ref<EstadoOperativoCajon>(props.cajon.estado_operativo)
const motivoBorrador = ref(props.cajon.motivo_operativo ?? '')
let elementoAnterior: HTMLElement | null = null
let overflowAnterior = ''

const conflictoOperativo = computed(() =>
  props.cajon.estado_operativo !== estadoBase.value
  || props.cajon.motivo_operativo !== motivoBase.value,
)
const solicitudValidada = computed(() =>
  crearSolicitudEstadoOperativo(estadoBorrador.value, motivoBorrador.value),
)
const motivoNormalizado = computed(() => motivoBorrador.value.trim())
const estadoActual = computed(() =>
  ETIQUETAS_ESTADO_OPERATIVO[props.cajon.estado_operativo],
)

function cerrarModal() {
  if (props.procesando) {
    return
  }
  emit('update:modelValue', false)
}

function aceptarCambioExterno() {
  estadoBase.value = props.cajon.estado_operativo
  motivoBase.value = props.cajon.motivo_operativo
}

function enviarFormulario() {
  emit('limpiar-error')
  if (props.procesando) {
    return
  }
  if (props.reconciliacionPendiente) {
    emit('reintentar-sincronizacion')
    return
  }
  if (conflictoOperativo.value || solicitudValidada.value.tipo !== 'valida') {
    return
  }

  emit('guardar', props.cajon.id, solicitudValidada.value.solicitud)
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

  if (event.key !== 'Tab') {
    return
  }

  const elementosEnfocables = dialogo.value?.querySelectorAll<HTMLElement>(
    'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
  )
  if (!elementosEnfocables || elementosEnfocables.length === 0) {
    event.preventDefault()
    dialogo.value?.focus()
    return
  }

  const primero = elementosEnfocables[0]
  const ultimo = elementosEnfocables[elementosEnfocables.length - 1]
  if (event.shiftKey && document.activeElement === primero) {
    event.preventDefault()
    ultimo?.focus()
  } else if (!event.shiftKey && document.activeElement === ultimo) {
    event.preventDefault()
    primero?.focus()
  }
}

function actualizarFocoInicial() {
  void nextTick().then(() => selectorEstado.value?.focus())
}

onMounted(() => {
  elementoAnterior = document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null
  overflowAnterior = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  document.addEventListener('keydown', manejarTeclado)
  actualizarFocoInicial()
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', manejarTeclado)
  document.body.style.overflow = overflowAnterior
  if (elementoAnterior?.isConnected) {
    elementoAnterior.focus()
  }
})
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue" class="modal-backdrop" @click.self="cerrarModal">
      <section
        ref="dialogo"
        class="parking-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="parking-dialog-title"
        tabindex="-1"
      >
        <header class="dialog-header">
          <div>
            <p class="eyebrow">Administración de estacionamiento</p>
            <h2 id="parking-dialog-title">Lugar {{ cajon.numero }}</h2>
          </div>
        </header>

        <dl class="confirmed-details" aria-label="Estado confirmado del cajón">
          <div>
            <dt>Estado físico · solo lectura</dt>
            <dd>{{ ETIQUETAS_ESTADO_FISICO[cajon.estado_fisico] }}</dd>
          </div>
          <div>
            <dt>Estado operativo confirmado</dt>
            <dd>{{ estadoActual }}</dd>
          </div>
          <div>
            <dt>Estado efectivo del servidor</dt>
            <dd>{{ ETIQUETAS_ESTADO_EFECTIVO[cajon.estado_efectivo] }}</dd>
          </div>
          <div v-if="cajon.motivo_operativo !== null">
            <dt>Motivo confirmado</dt>
            <dd>{{ cajon.motivo_operativo }}</dd>
          </div>
        </dl>

        <section v-if="conflictoOperativo" class="conflict-notice" role="alert">
          <h3>El estado operativo cambió en tiempo real</h3>
          <p>
            El valor más reciente es <strong>{{ estadoActual }}</strong>
            <template v-if="cajon.motivo_operativo">
              con motivo: “{{ cajon.motivo_operativo }}”.
            </template>
            Revisa este valor antes de guardar tu borrador.
          </p>
          <button class="button secondary" type="button" @click="aceptarCambioExterno">
            Revisé el cambio
          </button>
        </section>

        <div v-if="reconciliacionPendiente" class="pending-notice" role="alert">
          <h3>Falta sincronizar la lista</h3>
          <p>El cambio pudo aplicarse. Se conservaron los datos confirmados y solo se reintentará la consulta.</p>
        </div>

        <form class="operational-form" @submit.prevent="enviarFormulario">
          <label for="operational-state">Estado operativo</label>
          <select
            id="operational-state"
            ref="selectorEstado"
            v-model="estadoBorrador"
            :disabled="procesando || reconciliacionPendiente"
            @change="emit('limpiar-error')"
          >
            <option value="DISPONIBLE">Disponible</option>
            <option value="MANTENIMIENTO">Mantenimiento</option>
            <option value="FUERA_DE_SERVICIO">Fuera de servicio</option>
          </select>

          <template v-if="estadoBorrador !== 'DISPONIBLE'">
            <label for="operational-reason">Motivo (opcional)</label>
            <textarea
              id="operational-reason"
              v-model="motivoBorrador"
              rows="3"
              aria-describedby="reason-hint"
              :disabled="procesando || reconciliacionPendiente"
              @input="emit('limpiar-error')"
            />
            <p id="reason-hint" class="field-hint">
              Puedes agregar un motivo de hasta 250 caracteres; guardar sin motivo también está permitido.
              {{ motivoNormalizado.length }}/250
            </p>
            <p
              v-if="solicitudValidada.tipo === 'invalida'"
              class="field-error"
              role="alert"
            >
              {{ solicitudValidada.mensaje }}
            </p>
          </template>

          <p v-if="errorGuardado" class="field-error" role="alert">
            {{ errorGuardado }}
          </p>
          <p v-if="procesando" class="saving-status" role="status" aria-live="polite">
            {{ reconciliacionPendiente ? 'Sincronizando…' : 'Guardando y sincronizando…' }}
          </p>

          <footer class="dialog-actions">
            <button
              class="button secondary"
              type="button"
              :disabled="procesando"
              @click="cerrarModal"
            >
              Cancelar
            </button>
            <button
              class="button primary"
              type="submit"
              :disabled="procesando || (!reconciliacionPendiente && (conflictoOperativo || solicitudValidada.tipo !== 'valida'))"
            >
              {{ procesando
                ? 'Guardando…'
                : reconciliacionPendiente
                  ? 'Reintentar sincronización'
                  : 'Guardar estado' }}
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
  padding: 1.1rem;
  background: rgb(24 18 31 / 62%);
  place-items: center;
}

.parking-dialog {
  width: min(100%, 38rem);
  max-height: min(92vh, 48rem);
  overflow-y: auto;
  padding: clamp(1.15rem, 3vw, 1.8rem);
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
  margin-bottom: 1rem;
}

.eyebrow {
  margin: 0 0 0.35rem;
  color: #6b4a89;
  font-size: 0.68rem;
  font-weight: 750;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h2,
h3,
p,
dd {
  overflow-wrap: anywhere;
}

h2 {
  margin: 0;
  color: #29252f;
  font-size: clamp(1.35rem, 3vw, 1.65rem);
  letter-spacing: -0.035em;
}

.confirmed-details {
  display: grid;
  gap: 0.55rem;
  margin: 0;
}

.confirmed-details > div {
  display: grid;
  grid-template-columns: minmax(10rem, 0.8fr) minmax(0, 1.2fr);
  gap: 0.7rem;
  padding: 0.72rem 0.8rem;
  background: #faf9fb;
  border: 1px solid #eeebf0;
  border-radius: 0.65rem;
}

.confirmed-details dt,
.field-hint {
  color: #746f7b;
  font-size: 0.78rem;
  line-height: 1.5;
}

.confirmed-details dd {
  margin: 0;
  color: #302b35;
  font-size: 0.82rem;
  font-weight: 650;
  line-height: 1.5;
}

.operational-form {
  display: grid;
  gap: 0.55rem;
  margin-top: 1.2rem;
}

.operational-form label {
  margin-top: 0.35rem;
  color: #48424e;
  font-size: 0.82rem;
  font-weight: 700;
}

.operational-form select,
.operational-form textarea {
  width: 100%;
  min-width: 0;
  padding: 0.72rem 0.8rem;
  color: #302b35;
  background: #ffffff;
  border: 1px solid #d9d4de;
  border-radius: 0.65rem;
  font: inherit;
  font-size: 0.87rem;
}

.operational-form textarea {
  resize: vertical;
}

.operational-form select:focus-visible,
.operational-form textarea:focus-visible,
.button:focus-visible,
.icon-button:focus-visible {
  outline: 3px solid rgb(92 58 134 / 27%);
  outline-offset: 2px;
}

.field-hint,
.field-error,
.saving-status {
  margin: 0;
}

.field-error {
  color: #9f3030;
  font-size: 0.8rem;
  line-height: 1.5;
}

.saving-status {
  color: #6b4a89;
  font-size: 0.83rem;
  font-weight: 650;
}

.conflict-notice,
.pending-notice {
  margin-top: 0.9rem;
  padding: 0.9rem;
  background: #fff8e9;
  border: 1px solid #eddfc1;
  border-radius: 0.7rem;
}

.pending-notice {
  background: #fbefef;
  border-color: #efd9d9;
}

.conflict-notice h3,
.pending-notice h3 {
  margin: 0;
  color: #674b24;
  font-size: 0.88rem;
}

.pending-notice h3 {
  color: #803b3b;
}

.conflict-notice p,
.pending-notice p {
  margin: 0.35rem 0 0.65rem;
  color: #665c4e;
  font-size: 0.81rem;
  line-height: 1.5;
}

.dialog-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.55rem;
  margin-top: 0.65rem;
}

.button {
  display: inline-flex;
  min-height: 2.65rem;
  align-items: center;
  justify-content: center;
  padding: 0.62rem 0.9rem;
  border: 1px solid transparent;
  border-radius: 0.65rem;
  font: inherit;
  font-size: 0.82rem;
  font-weight: 700;
  cursor: pointer;
}

.button.primary {
  color: #ffffff;
  background: #5c3a86;
  border-color: #5c3a86;
}

.button.secondary {
  color: #554b5e;
  background: #ffffff;
  border-color: #d9d4de;
}

.button:disabled {
  cursor: wait;
  opacity: 0.65;
}

@media (max-width: 34rem) {
  .confirmed-details > div {
    grid-template-columns: minmax(0, 1fr);
    gap: 0.2rem;
  }

  .dialog-actions > .button {
    flex: 1 1 9rem;
  }
}
</style>
