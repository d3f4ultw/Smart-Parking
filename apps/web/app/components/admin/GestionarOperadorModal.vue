<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { obtenerEstadoErrorOperador } from '~/utils/operadores'
import {
  etiquetaEstadoCuentaOperador,
  mapearErrorGestionOperador,
  obtenerSegundosRetryAfter,
  puedeReenviarInvitacionOperador,
  puedeRegenerarContrasenaOperador,
  type DetalleOperadorConCooldown,
} from '~/utils/gestion-operadores'

const props = defineProps<{
  modelValue: boolean
  operatorId: string
}>()

const emit = defineEmits<{
  'update:modelValue': [abierto: boolean]
  'operator-state-changed': [operadorId: number]
  'action-busy': [operadorId: number, ocupada: boolean]
}>()

const CLAVE_LISTA_OPERADORES = 'admin-operadores-lista'
const claveDetalle = `admin-operador-${props.operatorId}`
const {
  desactivarOperador,
  obtenerDetalleOperador,
  reactivarOperador,
  reenviarInvitacionOperador,
  regenerarContrasenaOperador,
} = useOperadores()
const { limpiarSesion } = useSesion()
const { mostrarToast } = useAdminToasts()
const procesando = ref(false)
const segundosCooldownReenvio = ref(0)
const anuncioCooldownReenvio = ref('')
const dialogo = ref<HTMLElement | null>(null)
const botonCerrar = ref<HTMLButtonElement | null>(null)
let elementoAnterior: HTMLElement | null = null
let overflowAnterior = ''
let dialogoActivo = false
let invocadorConfirmacion: HTMLElement | null = null
let finCooldownReenvio = 0
let temporizadorCooldownReenvio: ReturnType<typeof setInterval> | undefined

type AccionConfirmable = 'desactivar' | 'reactivar' | 'regenerar-contrasena'

const CONFIRMACIONES: Record<AccionConfirmable, {
  titulo: string
  mensaje: string
  etiquetaAccion: string
}> = {
  desactivar: {
    titulo: '¿Desactivar esta cuenta?',
    mensaje: 'Sus sesiones actuales dejarán de funcionar.',
    etiquetaAccion: 'Desactivar operador',
  },
  reactivar: {
    titulo: '¿Reactivar esta cuenta?',
    mensaje: 'Una cuenta pendiente necesitará una invitación nueva.',
    etiquetaAccion: 'Reactivar operador',
  },
  'regenerar-contrasena': {
    titulo: '¿Regenerar la contraseña de este operador?',
    mensaje: 'Si el envío se completa, la contraseña anterior dejará de funcionar y sus sesiones activas se cerrarán. La contraseña nueva se enviará al correo registrado y no se mostrará en este panel. Si falla la entrega, se conserva la contraseña actual.',
    etiquetaAccion: 'Regenerar contraseña',
  },
}
const confirmacionPendiente = ref<AccionConfirmable | null>(null)
const dialogoConfirmacion = ref<HTMLElement | null>(null)
const botonCancelarConfirmacion = ref<HTMLButtonElement | null>(null)
const confirmacionActual = computed(() => {
  const accion = confirmacionPendiente.value
  return accion === null ? null : CONFIRMACIONES[accion]
})
const etiquetaReenvio = computed(() => {
  if (procesando.value) {
    return 'Procesando…'
  }
  if (segundosCooldownReenvio.value > 0) {
    return `Reenviar en ${segundosCooldownReenvio.value} s`
  }
  return 'Reenviar invitación'
})

const {
  data: detalleOperador,
  error,
  pending,
  refresh,
} = await useAsyncData<DetalleOperadorConCooldown | null>(
  claveDetalle,
  () => obtenerDetalleOperador(props.operatorId),
  {
    default: () => null,
    dedupe: 'defer',
  },
)
const operador = computed(() => detalleOperador.value?.operador ?? null)
segundosCooldownReenvio.value =
  detalleOperador.value?.cooldown_reenvio_segundos ?? 0

async function atenderError(errorActual: unknown) {
  const codigo = obtenerEstadoErrorOperador(errorActual)
  if (codigo === 401) {
    limpiarSesion()
    clearNuxtData(CLAVE_LISTA_OPERADORES)
    clearNuxtData(claveDetalle)
    await navigateTo('/login', { replace: true })
    return
  }
  if (import.meta.client) {
    mostrarToast(mapearErrorGestionOperador(codigo), 'error')
  }
}

if (error.value && obtenerEstadoErrorOperador(error.value) === 401) {
  await atenderError(error.value)
}

watch(error, (errorActual) => {
  if (import.meta.client && errorActual) {
    void atenderError(errorActual)
  }
})

function cerrarModal() {
  if (procesando.value) {
    return
  }
  emit('update:modelValue', false)
}

function detenerTemporizadorCooldownReenvio() {
  if (temporizadorCooldownReenvio !== undefined) {
    clearInterval(temporizadorCooldownReenvio)
    temporizadorCooldownReenvio = undefined
  }
}

function actualizarCooldownReenvio() {
  const restantes = Math.max(
    0,
    Math.ceil((finCooldownReenvio - Date.now()) / 1000),
  )
  segundosCooldownReenvio.value = restantes

  if (restantes === 0) {
    detenerTemporizadorCooldownReenvio()
    anuncioCooldownReenvio.value = 'Ya puedes reenviar la invitación.'
  }
}

function iniciarCooldownReenvio(segundos: number) {
  if (!Number.isSafeInteger(segundos) || segundos <= 0 || segundos > 86_400) {
    return
  }

  detenerTemporizadorCooldownReenvio()
  finCooldownReenvio = Date.now() + segundos * 1000
  segundosCooldownReenvio.value = segundos
  anuncioCooldownReenvio.value =
    `Podrás reenviar la invitación en ${segundos} segundos.`
  temporizadorCooldownReenvio = setInterval(actualizarCooldownReenvio, 1000)
}

function obtenerCooldownDelError(errorActual: unknown): number | null {
  if (typeof errorActual !== 'object' || errorActual === null) {
    return null
  }

  const posibleError = errorActual as { response?: Response }
  return obtenerSegundosRetryAfter(
    posibleError.response?.headers.get('Retry-After') ?? null,
  )
}

function solicitarConfirmacion(accion: AccionConfirmable) {
  if (procesando.value || operador.value === null) {
    return
  }

  if (
    accion === 'regenerar-contrasena'
    && !puedeRegenerarContrasenaOperador(operador.value)
  ) {
    return
  }

  invocadorConfirmacion = document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null
  confirmacionPendiente.value = accion
  void nextTick().then(() => botonCancelarConfirmacion.value?.focus())
}

function cancelarConfirmacion() {
  if (confirmacionPendiente.value === null) {
    return
  }

  confirmacionPendiente.value = null
  void nextTick().then(() => {
    if (invocadorConfirmacion?.isConnected) {
      invocadorConfirmacion.focus()
    } else {
      dialogo.value?.focus()
    }
    invocadorConfirmacion = null
  })
}

function confirmarAccion() {
  const accion = confirmacionPendiente.value
  if (accion === null) {
    return
  }

  confirmacionPendiente.value = null
  invocadorConfirmacion = null

  const operacion = accion === 'regenerar-contrasena'
    ? ejecutarRegeneracionContrasena()
    : ejecutarCambioEstado(accion)
  void nextTick().then(() => dialogo.value?.focus())
  void operacion
}

function guardarEstado(accion: 'desactivar' | 'reactivar') {
  solicitarConfirmacion(accion)
}

async function ejecutarCambioEstado(accion: 'desactivar' | 'reactivar') {
  if (procesando.value || operador.value === null) {
    return
  }

  procesando.value = true
  const operadorId = operador.value.id
  emit('action-busy', operadorId, true)
  try {
    if (accion === 'desactivar') {
      await desactivarOperador(operadorId)
      mostrarToast('Operador desactivado.')
    } else {
      await reactivarOperador(operadorId)
      mostrarToast('Operador reactivado.')
    }
    emit('operator-state-changed', operadorId)
    await refresh()
  } catch (errorActual: unknown) {
    await atenderError(errorActual)
    if (obtenerEstadoErrorOperador(errorActual) === 409) {
      emit('operator-state-changed', operadorId)
      await refresh()
    }
  } finally {
    procesando.value = false
    emit('action-busy', operadorId, false)
  }
}

function regenerarContrasena() {
  if (
    procesando.value
    || operador.value === null
    || !puedeRegenerarContrasenaOperador(operador.value)
  ) {
    return
  }

  solicitarConfirmacion('regenerar-contrasena')
}

async function ejecutarRegeneracionContrasena() {
  if (
    procesando.value
    || operador.value === null
    || !puedeRegenerarContrasenaOperador(operador.value)
  ) {
    return
  }

  procesando.value = true
  const operadorId = operador.value.id
  emit('action-busy', operadorId, true)
  try {
    await regenerarContrasenaOperador(operadorId)
    mostrarToast('La contraseña nueva se envió al correo registrado.')
  } catch (errorActual: unknown) {
    await atenderError(errorActual)
  } finally {
    procesando.value = false
    emit('action-busy', operadorId, false)
  }
}

async function reenviarInvitacion() {
  if (
    procesando.value
    || operador.value === null
    || segundosCooldownReenvio.value > 0
    || !puedeReenviarInvitacionOperador(operador.value)
  ) {
    return
  }

  procesando.value = true
  const operadorId = operador.value.id
  emit('action-busy', operadorId, true)
  try {
    await reenviarInvitacionOperador(operadorId, iniciarCooldownReenvio)
    mostrarToast('La invitación se envió al correo registrado.')
  } catch (errorActual: unknown) {
    const codigo = obtenerEstadoErrorOperador(errorActual)
    if (codigo === 429) {
      const segundos = obtenerCooldownDelError(errorActual)
      if (segundos !== null) {
        iniciarCooldownReenvio(segundos)
      }
      await atenderError(errorActual)
    } else if (codigo === 503) {
      mostrarToast('No fue posible enviar el correo. La invitación anterior sigue vigente.', 'error')
    } else {
      await atenderError(errorActual)
    }
  } finally {
    procesando.value = false
    emit('action-busy', operadorId, false)
  }
}

function manejarTeclado(event: KeyboardEvent) {
  if (!props.modelValue) {
    return
  }

  if (event.key === 'Escape') {
    event.preventDefault()
    if (confirmacionPendiente.value !== null) {
      cancelarConfirmacion()
    } else {
      cerrarModal()
    }
    return
  }

  if (event.key !== 'Tab') {
    return
  }

  const contenedorActivo = confirmacionPendiente.value === null
    ? dialogo.value
    : dialogoConfirmacion.value
  if (contenedorActivo === null) {
    return
  }

  const elementosEnfocables = Array.from(
    contenedorActivo.querySelectorAll<HTMLElement>(
      'button:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])',
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

function entrarDialogo() {
  elementoAnterior = document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null
  overflowAnterior = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  dialogoActivo = true
  document.addEventListener('keydown', manejarTeclado)
  void nextTick().then(() => botonCerrar.value?.focus())
}

onMounted(() => {
  if (props.modelValue) {
    entrarDialogo()
    const segundos = detalleOperador.value?.cooldown_reenvio_segundos ?? 0
    if (segundos > 0) {
      iniciarCooldownReenvio(segundos)
    }
  }
  if (error.value && obtenerEstadoErrorOperador(error.value) !== 401) {
    mostrarToast(mapearErrorGestionOperador(obtenerEstadoErrorOperador(error.value)), 'error')
  }
})

onBeforeUnmount(() => {
  detenerTemporizadorCooldownReenvio()
  clearNuxtData(claveDetalle)
  if (import.meta.client && dialogoActivo) {
    document.removeEventListener('keydown', manejarTeclado)
    document.body.style.overflow = overflowAnterior
    if (elementoAnterior?.isConnected) {
      elementoAnterior.focus()
    }
  }
  clearNuxtData(claveDetalle)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue" class="modal-backdrop" @click.self="cerrarModal">
      <section
        ref="dialogo"
        class="operator-dialog"
        role="dialog"
        aria-modal="true"
        :aria-hidden="confirmacionPendiente !== null"
        :inert="confirmacionPendiente !== null"
        aria-labelledby="operator-detail-title"
        tabindex="-1"
      >
        <header class="dialog-header">
          <div>
            <p class="eyebrow">Operadores</p>
            <h2 id="operator-detail-title">Detalle del operador</h2>
          </div>
          <button
            ref="botonCerrar"
            class="icon-button"
            type="button"
            aria-label="Cerrar detalle del operador"
            :disabled="procesando"
            @click="cerrarModal"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <path d="m6 6 12 12M18 6 6 18" />
            </svg>
          </button>
        </header>

        <div v-if="pending && !operador" class="detail-layout detail-layout-skeleton" role="status">
          <span class="sr-only">Cargando información del operador…</span>
          <dl class="operator-details" aria-hidden="true">
            <div>
              <dt>Nombre</dt>
              <dd><span class="skeleton-line skeleton-name" /></dd>
            </div>
            <div>
              <dt>Correo electrónico</dt>
              <dd><span class="skeleton-line skeleton-email" /></dd>
            </div>
            <div>
              <dt>Estado de cuenta</dt>
              <dd><span class="skeleton-pill" /></dd>
            </div>
          </dl>
          <div class="actions" aria-hidden="true">
            <span class="action-skeleton" />
            <span class="action-skeleton" />
          </div>
        </div>
        <template v-else-if="operador">
          <div class="detail-layout" :aria-busy="pending">
            <dl class="operator-details">
              <div>
                <dt>Nombre</dt>
                <dd>{{ [operador.nombre, operador.apellido_paterno, operador.apellido_materno].filter(Boolean).join(' ') }}</dd>
              </div>
              <div>
                <dt>Correo electrónico</dt>
                <dd>{{ operador.correo }}</dd>
              </div>
              <div>
                <dt>Estado de cuenta</dt>
                <dd>
                  <span class="state" :class="operador.esta_activo ? 'active' : 'inactive'">
                    {{ etiquetaEstadoCuentaOperador(operador.estado_cuenta) }}
                  </span>
                </dd>
              </div>
            </dl>

          <div class="actions" role="group" aria-label="Acciones del operador" :aria-busy="procesando">
            <button
              v-if="puedeReenviarInvitacionOperador(operador)"
              class="action-card action-secondary"
              type="button"
              :disabled="procesando || segundosCooldownReenvio > 0"
              @click="reenviarInvitacion"
            >
              <span class="action-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="3.5" y="5" width="17" height="14" rx="2" />
                  <path d="m4.5 7 7.5 6 7.5-6" />
                </svg>
              </span>
              <span class="action-title">{{ etiquetaReenvio }}</span>
              <svg class="action-indicator" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="m9 18 6-6-6-6" />
              </svg>
            </button>
            <span class="sr-only" role="status" aria-live="polite" aria-atomic="true">
              {{ anuncioCooldownReenvio }}
            </span>
            <button
              class="action-card"
              :class="operador.esta_activo ? 'action-danger' : 'action-primary'"
              type="button"
              :disabled="procesando"
              @click="guardarEstado(operador.esta_activo ? 'desactivar' : 'reactivar')"
            >
              <span class="action-icon" aria-hidden="true">
                <svg v-if="operador.esta_activo" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 3v9" />
                  <path d="M7 5.8a8 8 0 1 0 10 0" />
                </svg>
                <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <circle cx="12" cy="12" r="9" />
                  <path d="m8 12 2.5 2.5L16.5 9" />
                </svg>
              </span>
              <span class="action-title">{{ procesando ? 'Procesando…' : operador.esta_activo ? 'Desactivar operador' : 'Reactivar operador' }}</span>
              <svg class="action-indicator" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="m9 18 6-6-6-6" />
              </svg>
            </button>
            <button
              v-if="puedeRegenerarContrasenaOperador(operador)"
              class="action-card action-primary"
              type="button"
              :disabled="procesando"
              @click="regenerarContrasena"
            >
              <span class="action-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <circle cx="8" cy="15" r="4" />
                  <path d="m11 12 8-8 2 2-2 2 2 2-3 3-2-2-2 2" />
                </svg>
              </span>
              <span class="action-title">{{ procesando ? 'Procesando…' : 'Regenerar contraseña' }}</span>
              <svg class="action-indicator" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="m9 18 6-6-6-6" />
              </svg>
            </button>
          </div>
          </div>
        </template>
        <div v-else class="detail-empty-state" role="status">
          No hay información disponible para este operador.
        </div>

      </section>
    </div>
  </Teleport>

  <Teleport to="body">
    <div
      v-if="confirmacionActual"
      class="confirmation-backdrop"
      @click.self="cancelarConfirmacion"
    >
      <section
        ref="dialogoConfirmacion"
        class="confirmation-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="operator-confirmation-title"
        aria-describedby="operator-confirmation-description"
      >
        <p class="eyebrow">Confirmación</p>
        <h3 id="operator-confirmation-title">{{ confirmacionActual.titulo }}</h3>
        <p id="operator-confirmation-description" class="confirmation-description">
          {{ confirmacionActual.mensaje }}
        </p>
        <footer class="confirmation-actions">
          <button
            ref="botonCancelarConfirmacion"
            class="button secondary"
            type="button"
            @click="cancelarConfirmacion"
          >
            Cancelar
          </button>
          <button class="button primary" type="button" @click="confirmarAccion">
            {{ confirmacionActual.etiquetaAccion }}
          </button>
        </footer>
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

.operator-dialog {
  width: min(100%, 46rem);
  max-height: min(92vh, 44rem);
  overflow-y: auto;
  padding: clamp(1.25rem, 3vw, 2rem);
  color: #29252f;
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 1rem;
  box-shadow: 0 1.5rem 4.5rem rgb(15 10 21 / 24%);
}

.confirmation-backdrop {
  position: fixed;
  z-index: 110;
  inset: 0;
  display: grid;
  padding: 1.25rem;
  background: rgb(24 18 31 / 40%);
  place-items: center;
}

.confirmation-dialog {
  width: min(100%, 31rem);
  padding: clamp(1.25rem, 3vw, 1.7rem);
  color: #29252f;
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 1rem;
  box-shadow: 0 1.5rem 4.5rem rgb(15 10 21 / 28%);
}

.confirmation-dialog h3 {
  margin: 0;
  color: #29252f;
  font-size: 1.15rem;
  letter-spacing: -0.025em;
  line-height: 1.4;
}

.confirmation-description {
  margin: 0.7rem 0 0;
  color: #746f7b;
  font-size: 0.9rem;
  line-height: 1.55;
}

.confirmation-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.55rem;
  margin-top: 1.4rem;
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

.detail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(15rem, 0.85fr);
  align-items: stretch;
  gap: 1.1rem;
}

.operator-details {
  display: grid;
  align-content: start;
  gap: 0.55rem;
  margin: 0;
}

.operator-details > div {
  display: grid;
  grid-template-columns: minmax(6.5rem, 0.65fr) minmax(0, 1.35fr);
  align-items: center;
  gap: 0.75rem;
  min-width: 0;
  padding: 0.72rem 0.8rem;
  background: #faf9fb;
  border: 1px solid #ece9ef;
  border-radius: 0.65rem;
}

dt {
  color: #827c89;
  font-size: 0.77rem;
  font-weight: 650;
}

dd {
  min-width: 0;
  margin: 0;
  color: #302b35;
  font-size: 0.87rem;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.state {
  display: inline-block;
  padding: 0.3rem 0.55rem;
  color: #5c3a86;
  background: #f2edf6;
  border: 1px solid #e6dcec;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 700;
}

.state.inactive {
  color: #69636f;
  background: #f3f2f4;
  border-color: #e4e1e7;
}

.actions {
  display: grid;
  align-content: start;
  gap: 0.55rem;
  padding-left: 1.1rem;
  border-left: 1px solid #f0edf2;
}

.action-card {
  display: flex;
  width: 100%;
  min-height: 3.35rem;
  align-items: center;
  gap: 0.7rem;
  padding: 0.55rem 0.65rem;
  color: #42394a;
  background: #ffffff;
  border: 1px solid #e6e1ea;
  border-radius: 0.68rem;
  font: inherit;
  font-size: 0.82rem;
  font-weight: 700;
  text-align: left;
  cursor: pointer;
  transition: background-color 140ms ease, border-color 140ms ease, color 140ms ease;
}

.action-card:hover:not(:disabled) {
  background: #faf8fc;
  border-color: #d7c9e3;
}

.action-card:disabled {
  cursor: wait;
  opacity: 0.65;
}

.action-icon {
  display: grid;
  width: 2.1rem;
  height: 2.1rem;
  flex: 0 0 auto;
  place-items: center;
  color: #5c3a86;
  background: #f4eff8;
  border-radius: 0.55rem;
}

.action-icon svg {
  width: 1.05rem;
  height: 1.05rem;
}

.action-title {
  flex: 1 1 auto;
}

.action-indicator {
  width: 1rem;
  height: 1rem;
  flex: 0 0 auto;
  color: #938a9b;
}

.action-primary {
  color: #4d326f;
  background: #fbf9fd;
  border-color: #e2d8eb;
}

.action-primary:hover:not(:disabled) {
  color: #3f285d;
  background: #f5f0f9;
  border-color: #cdbbdd;
}

.action-danger {
  color: #9c302b;
  background: #fffdfd;
  border-color: #efd9d7;
}

.action-danger .action-icon {
  color: #a23832;
  background: #fff2f1;
}

.action-danger .action-indicator {
  color: #b76b65;
}

.action-danger:hover:not(:disabled) {
  color: #84241f;
  background: #fff8f7;
  border-color: #e6c0bd;
}

.action-secondary {
  color: #514957;
  background: #ffffff;
  border-color: #e6e1ea;
}

.action-secondary .action-icon {
  color: #6b4a89;
  background: #f7f4f9;
}

.action-secondary:hover:not(:disabled) {
  color: #4d326f;
  background: #faf8fc;
  border-color: #d7c9e3;
}

.action-skeleton {
  display: block;
  width: 100%;
  height: 3.35rem;
  background: linear-gradient(100deg, #f2f0f4 20%, #f9f8fa 42%, #f2f0f4 64%);
  background-size: 220% 100%;
  border: 1px solid #ece9ef;
  border-radius: 0.68rem;
  animation: detail-skeleton 1.4s ease-in-out infinite;
}

.skeleton-line {
  display: block;
  height: 0.85rem;
  max-width: 100%;
  background: #e9e6ec;
  border-radius: 0.3rem;
}

.skeleton-name {
  width: 68%;
}

.skeleton-email {
  width: 90%;
}

.skeleton-pill {
  display: inline-block;
  width: 7.6rem;
  height: 1.55rem;
  background: #eeeaf2;
  border-radius: 999px;
}

@keyframes detail-skeleton {
  to {
    background-position: -220% 0;
  }
}

.button {
  display: inline-flex;
  min-height: 2.65rem;
  align-items: center;
  justify-content: center;
  padding: 0.6rem 0.8rem;
  border: 1px solid transparent;
  border-radius: 0.62rem;
  font: inherit;
  font-size: 0.81rem;
  font-weight: 700;
  cursor: pointer;
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

.inline-status {
  padding: 0.5rem 0;
  color: #746f7b;
  font-size: 0.88rem;
}

.detail-empty-state {
  padding: 1rem;
  color: #746f7b;
  background: #faf9fb;
  border: 1px solid #ece9ef;
  border-radius: 0.7rem;
  font-size: 0.88rem;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
  clip-path: inset(50%);
}

.button:focus-visible,
.action-card:focus-visible,
.icon-button:focus-visible {
  outline: 3px solid rgb(92 58 134 / 25%);
  outline-offset: 2px;
}

.operator-dialog:focus-visible,
.confirmation-dialog button:focus-visible {
  outline: 3px solid rgb(92 58 134 / 25%);
  outline-offset: 2px;
}

@media (max-width: 42rem) {
  .modal-backdrop {
    padding: 0.75rem;
  }

  .operator-dialog {
    width: min(100%, 36rem);
    max-height: 92vh;
    padding: 1.15rem;
  }

  .detail-layout {
    grid-template-columns: minmax(0, 1fr);
    gap: 0.85rem;
  }

  .operator-details {
    gap: 0.45rem;
  }

  .actions {
    padding: 0.85rem 0 0;
    border-top: 1px solid #f0edf2;
    border-left: 0;
  }

  .confirmation-backdrop {
    padding: 1rem;
  }

  .confirmation-actions .button {
    flex: 1 1 8rem;
  }
}

@media (max-width: 27rem) {
  .operator-dialog {
    padding: 1rem;
  }

  .operator-details > div {
    grid-template-columns: minmax(0, 1fr);
    gap: 0.28rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .button {
    transition: none;
  }

  .action-card {
    transition: none;
  }

  .action-skeleton {
    animation: none;
  }
}
</style>
