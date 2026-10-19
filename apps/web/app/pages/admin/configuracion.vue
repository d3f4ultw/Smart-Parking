<script setup lang="ts">
import { computed, ref } from 'vue'

import {
  MODALIDADES_ESTACIONAMIENTO,
  mapearErrorConfiguracion,
  obtenerCodigoErrorHttp,
  puedeGuardarModalidad,
  type ModalidadEstacionamiento,
  type RespuestaModalidadEstacionamiento,
} from '~/utils/configuracion-estacionamiento'

definePageMeta({
  layout: 'admin',
  middleware: 'sesion-owner-operadores',
})

type ResultadoCarga =
  | { tipo: 'exito'; configuracion: RespuestaModalidadEstacionamiento }
  | { tipo: 'error'; mensaje: string }
type AccionConfirmacion = 'modalidad' | 'acceso' | null

const fetchConCookies = useRequestFetch()
const { mostrarToast } = useAdminToasts()
const { usuario } = useSesion()
const carga = await useAsyncData<ResultadoCarga>(
  'admin-configuracion-modalidad',
  async (_nuxtApp, { signal }) => {
    try {
      const configuracion = await fetchConCookies<RespuestaModalidadEstacionamiento>(
        '/api/admin/configuracion/modalidad',
        {
          credentials: 'same-origin',
          cache: 'no-store',
          signal,
        },
      )
      return { tipo: 'exito', configuracion }
    } catch (error: unknown) {
      return { tipo: 'error', mensaje: mapearErrorConfiguracion(error) }
    }
  },
  { dedupe: 'defer' },
)

const configuracionInicial = carga.data.value?.tipo === 'exito'
  ? carga.data.value.configuracion
  : null
const modalidadGuardada = ref<ModalidadEstacionamiento | null>(
  configuracionInicial?.modalidad ?? null,
)
const modalidadSeleccionada = ref<ModalidadEstacionamiento | ''>(
  configuracionInicial?.modalidad ?? '',
)
const revision = ref(configuracionInicial?.revision ?? 0)
const accesoSuspendido = ref(configuracionInicial?.acceso_suspendido ?? false)
const guardando = ref(false)
const accionConfirmacion = ref<AccionConfirmacion>(null)
const estadoAccesoSolicitado = ref<boolean | null>(null)
const dialogoConfirmacion = ref<HTMLDialogElement | null>(null)
const mensajeError = ref(
  carga.data.value?.tipo === 'error' ? carga.data.value.mensaje : '',
)

const configuracionDisponible = computed(
  () => carga.data.value?.tipo === 'exito',
)
const puedeAdministrarHorarios = computed(
  () => usuario.value?.rol === 'OWNER'
    && (modalidadGuardada.value === 'PRIVADO' || modalidadGuardada.value === 'MIXTO'),
)
const puedeGuardar = computed(() =>
  configuracionDisponible.value
  && puedeGuardarModalidad(
    modalidadGuardada.value,
    modalidadSeleccionada.value,
    guardando.value,
    accesoSuspendido.value,
  ),
)
const puedeCambiarAcceso = computed(
  () => configuracionDisponible.value
    && modalidadGuardada.value !== null
    && !guardando.value,
)
const lecturaPendiente = computed(() => carga.status.value === 'pending')
const tituloConfirmacion = computed(() => {
  if (accionConfirmacion.value === 'acceso') {
    return estadoAccesoSolicitado.value
      ? 'Suspender el acceso'
      : 'Reanudar el acceso'
  }
  return 'Actualizar modalidad'
})
const textoConfirmar = computed(() => {
  if (guardando.value) {
    return 'Guardando…'
  }
  return accionConfirmacion.value === 'acceso'
    ? estadoAccesoSolicitado.value ? 'Confirmar suspensión' : 'Reanudar acceso'
    : 'Guardar cambios'
})

function etiquetaModalidad(modalidad: ModalidadEstacionamiento | null): string {
  if (modalidad === null) {
    return 'Sin configurar'
  }

  return MODALIDADES_ESTACIONAMIENTO.find(
    (opcion) => opcion.valor === modalidad,
  )?.etiqueta ?? 'Sin configurar'
}

function sincronizarConfiguracion(configuracion: RespuestaModalidadEstacionamiento) {
  modalidadGuardada.value = configuracion.modalidad
  modalidadSeleccionada.value = configuracion.modalidad ?? ''
  revision.value = configuracion.revision
  accesoSuspendido.value = configuracion.acceso_suspendido
}

async function actualizarConfiguracionAutoritativa(): Promise<boolean> {
  await carga.refresh()
  const resultado = carga.data.value
  if (resultado?.tipo !== 'exito') {
    if (resultado?.tipo === 'error') {
      mensajeError.value = resultado.mensaje
    }
    return false
  }

  sincronizarConfiguracion(resultado.configuracion)
  return true
}

async function mostrarErrorSolicitud(error: unknown) {
  if (obtenerCodigoErrorHttp(error) === 409) {
    const actualizado = await actualizarConfiguracionAutoritativa()
    mensajeError.value = actualizado
      ? 'La configuración cambió en otra sesión. Se actualizó el estado guardado; revísalo antes de continuar.'
      : 'La configuración cambió en otra sesión. Actualiza la página antes de volver a intentarlo.'
    return
  }
  mensajeError.value = mapearErrorConfiguracion(error)
}

async function guardarCambios() {
  const seleccionada = modalidadSeleccionada.value
  if (!puedeGuardar.value || seleccionada === '' || guardando.value) {
    return
  }

  guardando.value = true
  mensajeError.value = ''
  try {
    const configuracion = await fetchConCookies<RespuestaModalidadEstacionamiento>(
      '/api/admin/configuracion/modalidad',
      {
        method: 'PUT',
        credentials: 'same-origin',
        cache: 'no-store',
        body: {
          modalidad: seleccionada,
          revision_esperada: revision.value,
        },
      },
    )

    sincronizarConfiguracion(configuracion)
    mostrarToast('Modalidad '
      + etiquetaModalidad(configuracion.modalidad)
      + ' guardada.')
  } catch (error: unknown) {
    await mostrarErrorSolicitud(error)
  } finally {
    guardando.value = false
    accionConfirmacion.value = null
    dialogoConfirmacion.value?.close()
  }
}

function solicitarConfirmacion() {
  if (!puedeGuardar.value || modalidadSeleccionada.value === '' || guardando.value) {
    return
  }

  accionConfirmacion.value = 'modalidad'
  dialogoConfirmacion.value?.showModal()
}

function solicitarConfirmacionAcceso() {
  if (!puedeCambiarAcceso.value || guardando.value) {
    return
  }

  estadoAccesoSolicitado.value = !accesoSuspendido.value
  accionConfirmacion.value = 'acceso'
  dialogoConfirmacion.value?.showModal()
}

async function cambiarEstadoAcceso() {
  const accesoDeseado = estadoAccesoSolicitado.value
  if (
    !puedeCambiarAcceso.value
    || accesoDeseado === null
    || guardando.value
  ) {
    return
  }

  guardando.value = true
  mensajeError.value = ''
  try {
    const configuracion = await fetchConCookies<RespuestaModalidadEstacionamiento>(
      '/api/admin/configuracion/acceso',
      {
        method: 'PUT',
        credentials: 'same-origin',
        cache: 'no-store',
        body: {
          acceso_suspendido: accesoDeseado,
          revision_esperada: revision.value,
        },
      },
    )

    sincronizarConfiguracion(configuracion)
    mostrarToast(configuracion.acceso_suspendido
      ? 'La política de acceso quedó suspendida.'
      : 'La política de acceso quedó habilitada.')
  } catch (error: unknown) {
    await mostrarErrorSolicitud(error)
  } finally {
    guardando.value = false
    accionConfirmacion.value = null
    estadoAccesoSolicitado.value = null
    dialogoConfirmacion.value?.close()
  }
}

async function confirmarAccion() {
  if (guardando.value) {
    return
  }
  if (accionConfirmacion.value === 'modalidad') {
    await guardarCambios()
  } else if (accionConfirmacion.value === 'acceso') {
    await cambiarEstadoAcceso()
  }
}
</script>

<template>
  <main class="configuration-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">Smart Parking · Administración</p>
        <h1>Configuración del estacionamiento</h1>
        <p class="heading-copy">
          Consulta y actualiza la modalidad guardada.
        </p>
      </div>
    </header>

    <section class="configuration-panel" aria-labelledby="modality-title">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Estacionamiento</p>
          <h2 id="modality-title">Modalidad del estacionamiento</h2>
        </div>
      </div>

      <p class="saved-value">
        Modalidad actual:
        <strong>{{ etiquetaModalidad(modalidadGuardada) }}</strong>
      </p>
      <p class="behavior-note">
        La modalidad clasifica el estacionamiento; no cambia las operaciones de
        acceso ni el estado de los cajones.
      </p>

      <p v-if="accesoSuspendido" class="feedback" role="status">
        La modalidad guardada se conserva mientras el acceso está suspendido.
      </p>

      <p v-if="lecturaPendiente" class="feedback" role="status" aria-live="polite">
        Cargando la modalidad guardada…
      </p>
      <p v-else-if="mensajeError && !configuracionDisponible" class="feedback feedback--error" role="alert">
        {{ mensajeError }}
      </p>

      <fieldset
        class="modality-options"
        :disabled="!configuracionDisponible || guardando || accesoSuspendido"
        aria-describedby="modality-help"
      >
        <legend class="sr-only">Elige una modalidad</legend>
        <label
          v-for="opcion in MODALIDADES_ESTACIONAMIENTO"
          :key="opcion.valor"
          class="modality-option"
          :class="{ 'modality-option--selected': modalidadSeleccionada === opcion.valor }"
        >
          <input
            v-model="modalidadSeleccionada"
            type="radio"
            name="modalidad"
            :value="opcion.valor"
          >
          <span class="option-copy">
            <span class="option-title">{{ opcion.etiqueta }}</span>
            <span class="option-description">{{ opcion.descripcion }}</span>
          </span>
        </label>
      </fieldset>
      <p id="modality-help" class="screen-reader-note">
        El cambio guarda una clasificación y conserva su historial.
      </p>

      <div class="form-footer">
        <div class="form-messages" aria-live="polite">
          <p v-if="mensajeError && configuracionDisponible" class="feedback feedback--error" role="alert">
            {{ mensajeError }}
          </p>
        </div>
        <button
          class="primary-button"
          type="button"
          :disabled="!puedeGuardar"
          @click="solicitarConfirmacion"
        >
          Guardar cambios
        </button>
      </div>
    </section>

    <section class="configuration-panel" aria-labelledby="access-title">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Control independiente</p>
          <h2 id="access-title">Acceso del estacionamiento</h2>
        </div>
      </div>

      <p class="saved-value" role="status" aria-live="polite">
        Estado actual:
        <strong>{{ !configuracionDisponible
          ? 'Estado no disponible'
          : accesoSuspendido ? 'Acceso suspendido' : 'Acceso habilitado' }}</strong>
      </p>
      <p class="behavior-note">
        «Fuera de servicio» guarda la política de acceso. La autorización RFID y
        las barreras físicas todavía no están integradas con esta configuración.
      </p>
      <div class="form-footer">
        <div class="form-messages" aria-live="polite">
          <p v-if="configuracionDisponible && !modalidadGuardada" class="feedback">
            Configura primero una modalidad para poder cambiar el estado del acceso.
          </p>
        </div>
        <button
          class="primary-button"
          type="button"
          :disabled="!puedeCambiarAcceso"
          :aria-busy="guardando"
          @click="solicitarConfirmacionAcceso"
        >
          {{ accesoSuspendido ? 'Reanudar acceso' : 'Fuera de servicio' }}
        </button>
      </div>
    </section>

    <AdminHorariosEmpleadosPanel v-if="puedeAdministrarHorarios" />

    <dialog
      ref="dialogoConfirmacion"
      class="confirmation-dialog"
      aria-labelledby="confirmation-title"
      aria-describedby="confirmation-description"
    >
      <div class="confirmation-content">
        <div>
          <p class="eyebrow">Confirmar cambio</p>
          <h2 id="confirmation-title">{{ tituloConfirmacion }}</h2>
        </div>
        <p
          v-if="accionConfirmacion === 'modalidad'"
          id="confirmation-description"
          class="confirmation-copy"
        >
          ¿Confirmas cambiar la modalidad de
          <strong>{{ etiquetaModalidad(modalidadGuardada) }}</strong> a
          <strong>{{ etiquetaModalidad(modalidadSeleccionada === '' ? null : modalidadSeleccionada) }}</strong>?
        </p>
        <p
          v-else
          id="confirmation-description"
          class="confirmation-copy"
        >
          ¿Confirmas {{ estadoAccesoSolicitado ? 'suspender' : 'reanudar' }} el acceso
          del estacionamiento? Se conservará la modalidad guardada y esta acción no
          enviará órdenes a la barrera física.
        </p>
        <div class="confirmation-actions">
          <button
            class="secondary-button"
            type="button"
            :disabled="guardando"
            @click="dialogoConfirmacion?.close()"
          >
            Cancelar
          </button>
          <button
            class="primary-button"
            type="button"
            :disabled="guardando"
            :aria-busy="guardando"
            @click="confirmarAccion"
          >
            {{ textoConfirmar }}
          </button>
        </div>
      </div>
    </dialog>
  </main>
</template>

<style scoped>
.configuration-page {
  display: grid;
  gap: 1.5rem;
  min-width: 0;
}

.page-heading,
.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.eyebrow {
  margin: 0 0 0.45rem;
  color: #6b4a89;
  font-size: 0.7rem;
  font-weight: 750;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h1,
h2 {
  margin: 0;
  color: #29252f;
  letter-spacing: -0.035em;
}

h1 {
  font-size: clamp(1.65rem, 3vw, 2.25rem);
  line-height: 1.2;
}

h2 {
  font-size: 1.12rem;
  line-height: 1.35;
}

.heading-copy {
  margin: 0.55rem 0 0;
  color: #746f7b;
  font-size: 0.95rem;
}

.configuration-panel {
  display: grid;
  gap: 1.1rem;
  min-width: 0;
  padding: clamp(1.1rem, 2.5vw, 1.8rem);
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 1rem;
  box-shadow: 0 0.75rem 2rem rgb(37 28 47 / 4%);
}

.saved-value,
.behavior-note,
.screen-reader-note {
  margin: 0;
  color: #625d68;
  font-size: 0.9rem;
  line-height: 1.55;
}

.saved-value strong {
  color: #29252f;
}

.behavior-note {
  margin-top: -0.8rem;
  color: #746f7b;
}

.modality-options {
  display: grid;
  gap: 0.65rem;
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}

.modality-options:disabled {
  opacity: 0.68;
}

.modality-option {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  gap: 0.8rem;
  padding: 0.9rem 1rem;
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 0.75rem;
  cursor: pointer;
  transition: border-color 140ms ease, background-color 140ms ease;
}

.modality-option--selected {
  background: #f7f3fa;
  border-color: #7955a0;
}

.modality-option input {
  width: 1rem;
  height: 1rem;
  flex: 0 0 auto;
  margin: 0.15rem 0 0;
  accent-color: #5c3a86;
}

.option-copy {
  display: grid;
  gap: 0.2rem;
  min-width: 0;
}

.option-title {
  color: #29252f;
  font-size: 0.92rem;
  font-weight: 700;
}

.option-description {
  color: #746f7b;
  font-size: 0.82rem;
  line-height: 1.45;
}

.screen-reader-note,
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  clip-path: inset(50%);
}

.form-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding-top: 0.25rem;
  border-top: 1px solid #efedf1;
}

.form-messages {
  min-width: 0;
}

.feedback {
  margin: 0;
  color: #625d68;
  font-size: 0.88rem;
  line-height: 1.5;
}

.feedback--error {
  color: #a12636;
}

.feedback--success {
  color: #246b43;
}

.primary-button {
  display: inline-flex;
  min-height: 2.75rem;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  padding: 0.65rem 1rem;
  color: #ffffff;
  font: inherit;
  font-size: 0.88rem;
  font-weight: 700;
  background: #5c3a86;
  border: 1px solid #5c3a86;
  border-radius: 0.65rem;
  cursor: pointer;
}

.primary-button:disabled {
  background: #a79aaf;
  border-color: #a79aaf;
  cursor: not-allowed;
}

.primary-button:focus-visible,
.secondary-button:focus-visible,
.modality-option:focus-within {
  outline: 3px solid rgb(92 58 134 / 25%);
  outline-offset: 2px;
}

.confirmation-dialog {
  width: min(32rem, calc(100% - 2rem));
  max-width: calc(100% - 2rem);
  padding: 0;
  color: #29252f;
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 1rem;
  box-shadow: 0 1.25rem 3.5rem rgb(25 18 34 / 22%);
}

.confirmation-dialog::backdrop {
  background: rgb(31 25 37 / 48%);
  backdrop-filter: blur(2px);
}

.confirmation-content {
  display: grid;
  gap: 1.25rem;
  padding: clamp(1.2rem, 4vw, 1.65rem);
}

.confirmation-copy {
  margin: 0;
  color: #625d68;
  font-size: 0.95rem;
  line-height: 1.6;
}

.confirmation-copy strong {
  color: #29252f;
}

.confirmation-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.7rem;
  padding-top: 0.25rem;
}

.secondary-button {
  display: inline-flex;
  min-height: 2.75rem;
  align-items: center;
  justify-content: center;
  padding: 0.65rem 1rem;
  color: #5c3a86;
  font: inherit;
  font-size: 0.88rem;
  font-weight: 700;
  background: #ffffff;
  border: 1px solid #d9cde3;
  border-radius: 0.65rem;
  cursor: pointer;
}

.secondary-button:disabled {
  cursor: not-allowed;
  opacity: 0.65;
}

@media (max-width: 600px) {
  .form-footer {
    align-items: stretch;
    flex-direction: column;
  }

  .primary-button {
    width: 100%;
  }

  .confirmation-actions {
    flex-direction: column-reverse;
  }

  .confirmation-actions .secondary-button {
    width: 100%;
  }
}
</style>
