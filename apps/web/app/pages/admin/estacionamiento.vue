<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  aplicarInstantaneaCajon,
  crearSolicitudEstadoOperativo,
  contarCajones,
  ETIQUETAS_ESTADO_EFECTIVO,
  ETIQUETAS_ESTADO_FISICO,
  ETIQUETAS_ESTADO_OPERATIVO,
  esRespuestaMutacionCajon,
  estadoOperativoSinCambios,
  ordenarCajones,
  type RespuestaMutacionCajon,
  type SolicitudEstadoOperativoCajon,
  type RespuestaListaCajones,
} from '~/utils/cajones'
import {
  usarEventosTiempoReal,
  type EstadoEventosTiempoReal,
  type InstantaneaEventoCajon,
} from '~/utils/eventos-tiempo-real'

definePageMeta({
  layout: 'admin',
  middleware: 'sesion-owner',
})

type ResultadoCargaCajones =
  | { tipo: 'exito'; respuesta: RespuestaListaCajones }
  | { tipo: 'error'; codigo: number | null }

const CLAVE_LISTA_CAJONES = 'admin-cajones-lista'
const ESTADOS_RESUMEN = [
  { clave: 'libres', etiqueta: 'Libres' },
  { clave: 'ocupados', etiqueta: 'Ocupados' },
  { clave: 'noDisponibles', etiqueta: 'No disponibles' },
  { clave: 'desconocidos', etiqueta: 'Desconocidos' },
] as const
const ETIQUETAS_ESTADO_CONEXION: Record<EstadoEventosTiempoReal, string> = {
  conectando: 'Reconectando',
  conectado: 'En vivo',
  reconectando: 'Reconectando',
  'verificando-sesion': 'Verificando sesión',
  'sesion-perdida': 'Sesión finalizada',
  detenido: 'Sin conexión en tiempo real',
}

const { limpiarSesion } = useSesion()
const { mostrarToast } = useAdminToasts()
const eventosTiempoReal = usarEventosTiempoReal()
const estadoConexion = eventosTiempoReal.estado
const fetchConCookies = useRequestFetch()
const listaCajones = await useAsyncData<ResultadoCargaCajones>(
  CLAVE_LISTA_CAJONES,
  async (_nuxtApp, { signal }) => {
    try {
      const respuesta = await fetchConCookies<RespuestaListaCajones>(
        '/api/admin/cajones',
        { credentials: 'same-origin', signal },
      )
      return { tipo: 'exito', respuesta }
    } catch (error: unknown) {
      const errorHttp = error !== null && typeof error === 'object'
        ? error as { status?: unknown; statusCode?: unknown }
        : {}
      const codigo = typeof errorHttp.statusCode === 'number'
        ? errorHttp.statusCode
        : typeof errorHttp.status === 'number'
          ? errorHttp.status
          : null

      return { tipo: 'error', codigo }
    }
  },
  {
    dedupe: 'defer',
  },
)

const cajonesConfirmados = ref<RespuestaListaCajones | null>(
  listaCajones.data.value?.tipo === 'exito'
    ? listaCajones.data.value.respuesta
    : null,
)
const errorActualizacion = ref(false)
const cajonesOrdenados = computed(() =>
  ordenarCajones(cajonesConfirmados.value?.cajones ?? []),
)
const contadores = computed(() => cajonesConfirmados.value === null
  ? null
  : contarCajones(cajonesConfirmados.value.cajones))
const reconciliando = ref(false)
const suscripcionActiva = ref(false)
const cajonGestionId = ref<number | null>(null)
const cajonGestionado = computed(() => cajonesConfirmados.value?.cajones.find(
  (cajon) => cajon.id === cajonGestionId.value,
) ?? null)
const errorGestion = ref<string | null>(null)
const mensajeGestion = ref<string | null>(null)
const mutacionEnCurso = ref(false)
const mutacionPendiente = ref(false)
const cargaInicialPendiente = computed(() =>
  cajonesConfirmados.value === null && listaCajones.status.value === 'pending',
)
const cargaInicialFallida = computed(() =>
  cajonesConfirmados.value === null
  && listaCajones.data.value?.tipo === 'error',
)
const actualizando = computed(() =>
  reconciliando.value || listaCajones.status.value === 'pending' || mutacionEnCurso.value,
)
const mostrandoSkeletonActualizacion = computed(() =>
  cajonesConfirmados.value !== null && actualizando.value,
)
const estadoVisualConexion = computed<EstadoEventosTiempoReal>(() => {
  if (reconciliando.value || listaCajones.status.value === 'pending') {
    return estadoConexion.value === 'sesion-perdida'
      ? 'sesion-perdida'
      : 'reconectando'
  }
  if (!suscripcionActiva.value && estadoConexion.value !== 'sesion-perdida') {
    return 'reconectando'
  }
  return estadoConexion.value
})
const etiquetaConexion = computed(() => {
  if (reconciliando.value || listaCajones.status.value === 'pending') {
    return 'Actualizando'
  }
  if (!suscripcionActiva.value && estadoConexion.value !== 'sesion-perdida') {
    return 'Reconectando'
  }
  return ETIQUETAS_ESTADO_CONEXION[estadoConexion.value]
})
let suscripcionCajones: { detener: () => void } | null = null
let recuperacionEnCurso = false

function detenerSuscripcionCajones() {
  suscripcionCajones?.detener()
  suscripcionCajones = null
  suscripcionActiva.value = false
}

function suscribirCajones(opciones: { omitirResyncDuranteRegistro?: boolean } = {}) {
  detenerSuscripcionCajones()
  const respuesta = cajonesConfirmados.value
  if (respuesta === null || estadoConexion.value === 'sesion-perdida') {
    return
  }

  let registrando = true
  const suscripcion = eventosTiempoReal.suscribir(respuesta.cursor_eventos, {
    alActualizarOperador: () => {},
    alCrearOperador: () => {},
    alActualizarCajon: aplicarEventoCajon,
    alResync: () => {
      if (registrando && opciones.omitirResyncDuranteRegistro) {
        return
      }
      solicitarReconciliacion()
    },
  })
  registrando = false
  suscripcionCajones = { detener: suscripcion.detener }
  suscripcionActiva.value = true
}

function aplicarEventoCajon(evento: InstantaneaEventoCajon) {
  const respuesta = cajonesConfirmados.value
  if (respuesta === null) {
    return
  }

  const resultado = aplicarInstantaneaCajon(respuesta, evento)
  if (resultado.tipo === 'cajon-desconocido') {
    solicitarReconciliacion('cajon-desconocido')
    return
  }

  cajonesConfirmados.value = resultado.respuesta
}

function solicitarReconciliacion(origen: 'resync' | 'cajon-desconocido' = 'resync') {
  if (
    recuperacionEnCurso
    || estadoConexion.value === 'sesion-perdida'
    || (origen === 'cajon-desconocido' && errorActualizacion.value)
  ) {
    return
  }

  // Defer until suscribir() returns so a replayed event can detach its new subscription.
  void Promise.resolve().then(() => actualizarCajones())
}

async function atenderSesionPerdida() {
  detenerSuscripcionCajones()
  cajonesConfirmados.value = null
  cajonGestionId.value = null
  mutacionPendiente.value = false
  errorActualizacion.value = false
  reconciliando.value = false
  listaCajones.clear()
  limpiarSesion()
  await navigateTo('/login', { replace: true })
}

async function actualizarCajones(
  antesDeLeer?: () => Promise<boolean>,
): Promise<boolean> {
  if (recuperacionEnCurso || listaCajones.status.value === 'pending') {
    return false
  }

  recuperacionEnCurso = true
  reconciliando.value = true
  detenerSuscripcionCajones()
  errorActualizacion.value = false
  let reconciliacionExitosa = false
  try {
    if (antesDeLeer && !(await antesDeLeer())) {
      return false
    }

    await listaCajones.refresh()

    const resultado = listaCajones.data.value
    if (resultado?.tipo === 'exito') {
      cajonesConfirmados.value = resultado.respuesta
      mutacionPendiente.value = false
      if (
        cajonGestionId.value !== null
        && !resultado.respuesta.cajones.some((cajon) => cajon.id === cajonGestionId.value)
      ) {
        cajonGestionId.value = null
        errorGestion.value = 'El cajón dejó de aparecer en la lista actualizada.'
      }
      reconciliacionExitosa = true
      return true
    }

    if (resultado?.tipo === 'error' && resultado.codigo === 401) {
      await atenderSesionPerdida()
      return false
    }

    errorActualizacion.value = true
    return false
  } catch {
    errorActualizacion.value = true
    return false
  } finally {
    recuperacionEnCurso = false
    reconciliando.value = false
    if (
      cajonesConfirmados.value !== null
      && estadoConexion.value !== 'sesion-perdida'
    ) {
      suscribirCajones({ omitirResyncDuranteRegistro: !reconciliacionExitosa })
    }
  }
}

function abrirGestionCajon(cajonId: number) {
  if (mutacionEnCurso.value || mutacionPendiente.value) {
    return
  }
  errorGestion.value = null
  mensajeGestion.value = null
  cajonGestionId.value = cajonId
}

function cerrarGestionCajon(abierto: boolean) {
  if (!abierto) {
    cajonGestionId.value = null
  }
}

function obtenerCodigoHttp(error: unknown): number | null {
  if (typeof error !== 'object' || error === null) {
    return null
  }

  const errorHttp = error as { status?: unknown; statusCode?: unknown }
  if (typeof errorHttp.statusCode === 'number') {
    return errorHttp.statusCode
  }
  return typeof errorHttp.status === 'number' ? errorHttp.status : null
}

async function guardarEstadoOperativo(
  cajonId: number,
  solicitudRecibida: SolicitudEstadoOperativoCajon,
) {
  if (
    mutacionEnCurso.value
    || mutacionPendiente.value
    || cajonGestionId.value !== cajonId
    || cajonGestionado.value === null
  ) {
    return
  }

  const solicitudNormalizada = crearSolicitudEstadoOperativo(
    solicitudRecibida.estado,
    solicitudRecibida.motivo ?? '',
  )
  if (solicitudNormalizada.tipo !== 'valida') {
    errorGestion.value = solicitudNormalizada.mensaje
    return
  }

  if (estadoOperativoSinCambios(cajonGestionado.value, solicitudNormalizada.solicitud)) {
    mensajeGestion.value = 'El estado operativo ya coincide. No se envió ningún cambio.'
    cajonGestionId.value = null
    return
  }

  mutacionEnCurso.value = true
  errorGestion.value = null
  mensajeGestion.value = null
  let respuestaMutacionValida: RespuestaMutacionCajon | null = null
  let patchAceptado = false
  let respuestaConCambio = false
  let respuestaMalformada = false
  let cajonNoEncontrado = false

  try {
    const reconciliacionExitosa = await actualizarCajones(async () => {
      try {
        const respuesta = await fetchConCookies<unknown>(
          `/api/admin/cajones/${cajonId}/estado-operativo`,
          {
            method: 'PATCH',
            credentials: 'same-origin',
            body: solicitudNormalizada.solicitud,
          },
        )
        patchAceptado = true
        mutacionPendiente.value = true

        if (!esRespuestaMutacionCajon(respuesta, cajonId)) {
          respuestaMalformada = true
          errorGestion.value = 'El servidor aceptó la solicitud, pero no se pudo validar su respuesta. Se consultará la lista actual.'
          return true
        }

        respuestaMutacionValida = respuesta
        respuestaConCambio = respuesta.cambio_aplicado
        return true
      } catch (error: unknown) {
        const codigo = obtenerCodigoHttp(error)
        if (codigo === 401) {
          await atenderSesionPerdida()
          return false
        }
        if (codigo === 404) {
          cajonNoEncontrado = true
          errorGestion.value = 'El cajón ya no existe. Se actualizará la lista antes de continuar.'
          return true
        }
        if (codigo === null || codigo >= 500) {
          mutacionPendiente.value = true
          errorGestion.value = 'No se pudo confirmar la respuesta del servidor. Se conserva la información y puedes reintentar solo la sincronización.'
          return false
        }
        if (codigo === 422) {
          errorGestion.value = 'El servidor rechazó el estado o el motivo. Revisa los datos e inténtalo de nuevo.'
        } else if (codigo === 403) {
          errorGestion.value = 'Tu sesión no tiene permiso para cambiar este estado.'
        } else {
          errorGestion.value = 'No fue posible guardar el estado. Se conserva la información confirmada.'
        }
        return false
      }
    })

    if (!reconciliacionExitosa) {
      if (patchAceptado) {
        errorGestion.value = 'El cambio pudo aplicarse, pero la lista todavía no está sincronizada. Reintenta la sincronización; no se repetirá el PATCH.'
      }
      return
    }

    const cajonActual = cajonesConfirmados.value?.cajones.find(
      (cajon) => cajon.id === cajonId,
    )
    if (cajonActual === undefined) {
      cajonGestionId.value = null
      errorGestion.value = cajonNoEncontrado
        ? 'El cajón dejó de estar disponible y ya no aparece en la lista.'
        : 'El cajón ya no aparece en la lista actualizada.'
      return
    }

    if (cajonNoEncontrado) {
      return
    }
    if (respuestaMalformada) {
      return
    }
    if (patchAceptado && respuestaMutacionValida !== null) {
      if (respuestaConCambio) {
        mostrarToast('Cambio operativo confirmado.')
      } else {
        mensajeGestion.value = 'El servidor confirmó que no hubo cambios; la lista actual se sincronizó.'
      }
      cajonGestionId.value = null
    }
  } finally {
    mutacionEnCurso.value = false
  }
}

function limpiarErrorGestion() {
  errorGestion.value = null
}

function reintentarActualizacion() {
  void actualizarCajones()
}

watch(estadoConexion, (estado) => {
  if (estado !== 'sesion-perdida') {
    return
  }

  detenerSuscripcionCajones()
  cajonesConfirmados.value = null
  errorActualizacion.value = false
  reconciliando.value = false
  listaCajones.clear()
})

if (
  listaCajones.data.value?.tipo === 'error'
  && listaCajones.data.value.codigo === 401
) {
  await atenderSesionPerdida()
}

onMounted(() => suscribirCajones())
onBeforeUnmount(detenerSuscripcionCajones)
</script>

<template>
  <main class="parking-page" aria-labelledby="parking-title">
    <header class="page-heading">
      <div>
        <p class="eyebrow">Smart Parking · Administración</p>
        <h1 id="parking-title">Estacionamiento</h1>
        <p class="heading-copy">Monitoreo y administración de lugares de estacionamiento.</p>
      </div>
      <button
        v-if="cajonesConfirmados !== null"
        class="refresh-button"
        type="button"
        :aria-label="mutacionPendiente ? 'Reintentar sincronización' : actualizando ? 'Actualizando cajones' : 'Actualizar cajones'"
        :disabled="actualizando"
        @click="reintentarActualizacion"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M20 11a8.1 8.1 0 0 0-14.9-4L3 9" />
          <path d="M3 4v5h5" />
          <path d="M4 13a8.1 8.1 0 0 0 14.9 4L21 15" />
          <path d="M21 20v-5h-5" />
        </svg>
      </button>
    </header>

    <p v-if="mensajeGestion" class="management-feedback" role="status" aria-live="polite">
      {{ mensajeGestion }}
    </p>
    <p
      v-if="errorGestion && cajonGestionado === null"
      class="management-feedback management-feedback-error"
      role="alert"
    >
      {{ errorGestion }}
    </p>

    <section
      v-if="cargaInicialPendiente"
      class="loading-state"
      role="status"
      aria-live="polite"
    >
      <span class="loading-mark" aria-hidden="true" />
      <div>
        <h2>Cargando lugares</h2>
        <p>Consultando el estado actual del estacionamiento.</p>
      </div>
    </section>

    <section
      v-else-if="cargaInicialFallida"
      class="feedback-panel error-panel"
      role="alert"
    >
      <div>
        <h2>No fue posible cargar los lugares</h2>
        <p>Intenta actualizar la información en unos momentos.</p>
      </div>
      <button
        class="retry-button"
        type="button"
        :disabled="actualizando"
        @click="reintentarActualizacion"
      >
        Reintentar
      </button>
    </section>

    <section v-else-if="cajonesConfirmados !== null" class="parking-content">
      <div v-if="errorActualizacion" class="feedback-panel refresh-error" role="alert">
        <div>
          <h2>{{ mutacionPendiente ? 'El cambio pudo aplicarse, pero falta sincronizar la lista' : 'No se pudo completar la actualización' }}</h2>
          <p>{{ mutacionPendiente
            ? 'Se conserva la última información confirmada. Reintenta la consulta; el PATCH no se repetirá.'
            : 'Se conserva la última información confirmada; puede estar desactualizada.' }}</p>
        </div>
        <button
          class="retry-button"
          type="button"
          :disabled="actualizando"
          @click="reintentarActualizacion"
        >
          {{ mutacionPendiente ? 'Reintentar sincronización' : 'Reintentar' }}
        </button>
      </div>

      <section class="summary-panel" aria-labelledby="summary-title">
        <header class="summary-panel-heading">
          <h2 id="summary-title">Resumen de lugares</h2>
          <p
            class="connection-status"
            :data-connection-state="estadoVisualConexion"
            role="status"
            aria-live="polite"
          >
            <span class="connection-indicator" aria-hidden="true" />
            {{ etiquetaConexion }}
          </p>
        </header>
        <div class="summary-grid">
          <article
            v-for="estado in ESTADOS_RESUMEN"
            :key="estado.clave"
            class="summary-card"
            :data-summary-state="estado.clave"
            :aria-busy="mostrandoSkeletonActualizacion"
          >
            <span class="summary-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <template v-if="estado.clave === 'libres'">
                  <circle cx="12" cy="12" r="9" />
                  <path d="m8 12 2.5 2.5L16 9" />
                </template>
                <template v-else-if="estado.clave === 'ocupados'">
                  <path d="M5 17h14l-1.1-5.1a2 2 0 0 0-2-1.6H8.1a2 2 0 0 0-2 1.6L5 17Z" />
                  <path d="M5 17v2m14-2v2M7 17v1m10-1v1M6 14h.01M18 14h.01" />
                </template>
                <template v-else-if="estado.clave === 'noDisponibles'">
                  <circle cx="12" cy="12" r="9" />
                  <path d="m9 9 6 6m0-6-6 6" />
                </template>
                <template v-else>
                  <circle cx="12" cy="12" r="9" />
                  <path d="M9.8 9a2.3 2.3 0 1 1 3.8 1.7c-.9.8-1.6 1.1-1.6 2.3M12 16.5h.01" />
                </template>
              </svg>
            </span>
            <div class="summary-copy">
              <h3>{{ estado.etiqueta }}</h3>
              <p
                v-if="mostrandoSkeletonActualizacion"
                class="refresh-skeleton summary-value-skeleton"
                aria-hidden="true"
              />
              <p v-else>{{ contadores?.[estado.clave] ?? 0 }}</p>
            </div>
          </article>
        </div>
      </section>

      <section v-if="cajonesOrdenados.length === 0" class="empty-state">
        <span class="empty-mark" aria-hidden="true">P</span>
        <h2>No hay lugares registrados</h2>
        <p>Cuando se registren lugares de estacionamiento, aparecerán aquí con su estado actual.</p>
      </section>

      <section v-else class="parking-grid" aria-label="Lugares de estacionamiento">
        <article
          v-for="cajon in cajonesOrdenados"
          :key="cajon.id"
          class="parking-card"
          :aria-busy="mostrandoSkeletonActualizacion"
        >
          <header class="card-heading">
            <h2>Lugar {{ cajon.numero }}</h2>
            <span
              class="effective-state"
              :data-effective-state="cajon.estado_efectivo"
              :class="{ 'is-refreshing': mostrandoSkeletonActualizacion }"
            >
              <span
                v-if="mostrandoSkeletonActualizacion"
                class="refresh-skeleton state-badge-skeleton"
                aria-hidden="true"
              />
              <template v-else>
                <span class="state-indicator" aria-hidden="true" />
                {{ ETIQUETAS_ESTADO_EFECTIVO[cajon.estado_efectivo] }}
              </template>
            </span>
          </header>

          <dl class="state-details">
            <div>
              <dt>Estado físico</dt>
              <dd>
                <span
                  v-if="mostrandoSkeletonActualizacion"
                  class="refresh-skeleton state-value-skeleton"
                  aria-hidden="true"
                />
                <template v-else>{{ ETIQUETAS_ESTADO_FISICO[cajon.estado_fisico] }}</template>
              </dd>
            </div>
            <div class="operational-state-row">
              <dt class="operational-state-label">Estado operativo</dt>
              <dd
                class="operational-state-value"
                :data-operational-state="mostrandoSkeletonActualizacion ? undefined : cajon.estado_operativo"
              >
                <span
                  v-if="mostrandoSkeletonActualizacion"
                  class="refresh-skeleton state-value-skeleton"
                  aria-hidden="true"
                />
                <template v-else>{{ ETIQUETAS_ESTADO_OPERATIVO[cajon.estado_operativo] }}</template>
              </dd>
            </div>
            <div
              v-if="cajon.motivo_operativo !== null && cajon.estado_operativo !== 'DISPONIBLE'"
              class="operational-reason"
            >
              <dt>Motivo operativo</dt>
              <dd>
                <span
                  v-if="mostrandoSkeletonActualizacion"
                  class="refresh-skeleton state-value-skeleton"
                  aria-hidden="true"
                />
                <template v-else>{{ cajon.motivo_operativo }}</template>
              </dd>
            </div>
          </dl>
          <button
            class="manage-button"
            type="button"
            :disabled="mutacionEnCurso || mutacionPendiente || reconciliando"
            :aria-label="`Administrar el lugar ${cajon.numero}`"
            @click="abrirGestionCajon(cajon.id)"
          >
            Administrar
          </button>
        </article>
      </section>
    </section>

    <AdminGestionarCajonModal
      v-if="cajonGestionado !== null"
      :key="cajonGestionado.id"
      :model-value="true"
      :cajon="cajonGestionado"
      :procesando="mutacionEnCurso || reconciliando"
      :reconciliacion-pendiente="mutacionPendiente"
      :error-guardado="errorGestion"
      @update:model-value="cerrarGestionCajon"
      @guardar="guardarEstadoOperativo"
      @reintentar-sincronizacion="reintentarActualizacion"
      @limpiar-error="limpiarErrorGestion"
    />
  </main>
</template>

<style scoped>
.parking-page {
  min-width: 0;
  container-type: inline-size;
}

.page-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1.25rem;
  margin-bottom: 1.65rem;
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
h2,
p {
  overflow-wrap: anywhere;
}

h1 {
  margin: 0;
  color: #29252f;
  font-size: clamp(1.8rem, 3cqi, 2.35rem);
  letter-spacing: -0.035em;
  line-height: 1.2;
}

.heading-copy {
  margin: 0.55rem 0 0;
  color: #746f7b;
  font-size: 0.95rem;
  line-height: 1.5;
}

.refresh-button,
.retry-button,
.manage-button {
  display: inline-flex;
  min-height: 2.75rem;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  gap: 0.55rem;
  padding: 0.65rem 0.95rem;
  color: #ffffff;
  background: #5c3a86;
  border: 1px solid #5c3a86;
  border-radius: 0.65rem;
  font: inherit;
  font-size: 0.84rem;
  font-weight: 700;
  cursor: pointer;
  transition: background-color 150ms ease, border-color 150ms ease;
}

.refresh-button:hover:not(:disabled),
.retry-button:hover:not(:disabled),
.manage-button:hover:not(:disabled) {
  background: #6c4a97;
  border-color: #6c4a97;
}

.refresh-button {
  width: 2.25rem;
  min-height: 2.25rem;
  padding: 0;
  color: #57377e;
  background: #e9e0f0;
  border-color: #d4c2e4;
  border-radius: 50%;
  transition: color 150ms ease, background-color 150ms ease;
}

.refresh-button:hover:not(:disabled) {
  color: #482b6b;
  background: #ddd0ea;
  border-color: #c4add8;
}

.refresh-button svg {
  width: 1.2rem;
  height: 1.2rem;
}

.refresh-button:focus-visible,
.retry-button:focus-visible,
.manage-button:focus-visible {
  outline: 3px solid rgb(92 58 134 / 27%);
  outline-offset: 3px;
}

.refresh-button:disabled,
.retry-button:disabled,
.manage-button:disabled {
  cursor: wait;
  opacity: 0.72;
}

.parking-content {
  display: grid;
  gap: 1.25rem;
  min-width: 0;
}

.summary-panel {
  min-width: 0;
  padding: 1rem 1.2rem;
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 0.9rem;
  box-shadow: 0 0.55rem 1.5rem rgb(37 28 47 / 3%);
}

.summary-panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.55rem;
}

.summary-panel-heading h2 {
  margin: 0;
  color: #746f7b;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.035em;
}

.connection-status {
  display: inline-flex;
  min-height: 1.55rem;
  align-items: center;
  gap: 0.4rem;
  margin: 0;
  padding: 0.2rem 0.55rem;
  color: #655e6c;
  background: #f4f2f6;
  border: 1px solid #e9e5ed;
  border-radius: 99rem;
  font-size: 0.7rem;
  font-weight: 700;
  line-height: 1.2;
}

.connection-indicator {
  width: 0.42rem;
  height: 0.42rem;
  flex: 0 0 auto;
  background: currentColor;
  border-radius: 50%;
}

.connection-status[data-connection-state='conectado'] {
  color: #285b48;
  background: #edf5f0;
  border-color: #d4e7dc;
}

.connection-status[data-connection-state='reconectando'],
.connection-status[data-connection-state='conectando'],
.connection-status[data-connection-state='verificando-sesion'] {
  color: #745126;
  background: #faf3e8;
  border-color: #efe1c8;
}

.connection-status[data-connection-state='sesion-perdida'] {
  color: #8a3d3d;
  background: #fbefef;
  border-color: #efd9d9;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  min-width: 0;
}

.summary-card {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 0.8rem;
  min-width: 0;
  padding: 0.75rem 0.9rem;
}

.summary-card + .summary-card {
  border-left: 1px solid #eeebf0;
}

.summary-icon {
  display: grid;
  width: 2.5rem;
  height: 2.5rem;
  flex: 0 0 auto;
  place-items: center;
  color: #55515c;
  background: #f1f0f2;
  border-radius: 0.75rem;
}

.summary-icon svg {
  width: 1.25rem;
  height: 1.25rem;
}

.summary-card[data-summary-state='libres'] .summary-icon {
  color: #285b48;
  background: #edf5f0;
}

.summary-card[data-summary-state='ocupados'] .summary-icon {
  color: #4b4e73;
  background: #f0f0f8;
}

.summary-card[data-summary-state='noDisponibles'] .summary-icon {
  color: #745126;
  background: #faf3e8;
}

.summary-copy {
  min-width: 0;
}

.summary-copy h3 {
  margin: 0;
  color: #746f7b;
  font-size: 0.8rem;
  font-weight: 650;
  line-height: 1.4;
}

.summary-copy p {
  margin: 0.5rem 0 0;
  color: #302b35;
  font-size: clamp(1.5rem, 2.2cqi, 1.9rem);
  font-weight: 750;
  letter-spacing: -0.04em;
  line-height: 1.1;
}

.refresh-skeleton {
  display: block;
  background: linear-gradient(90deg, #eeeaf1 25%, #f7f5f8 50%, #eeeaf1 75%);
  background-size: 200% 100%;
  animation: parking-data-skeleton 1.35s ease-in-out infinite;
}

.summary-value-skeleton {
  width: 2.2rem;
  height: 1.7rem;
  margin-top: 0.5rem;
  border-radius: 0.35rem;
}

.state-badge-skeleton {
  width: 4.5rem;
  height: 0.72rem;
  border-radius: 99rem;
}

.state-value-skeleton {
  display: inline-block;
  width: 70%;
  min-width: 2.8rem;
  height: 0.75rem;
  border-radius: 0.25rem;
  vertical-align: middle;
}

.parking-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.9rem;
  min-width: 0;
}

.parking-card {
  display: grid;
  min-width: 0;
  align-content: start;
  gap: 1rem;
  padding: 1.1rem;
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 0.9rem;
  box-shadow: 0 0.65rem 1.8rem rgb(37 28 47 / 3.5%);
}

.card-heading {
  position: relative;
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 0.35rem;
  padding-bottom: 0.95rem;
  border-bottom: 1px solid #eeebf0;
}

.card-heading h2 {
  white-space: nowrap;
  margin: 0;
  color: #302b35;
  font-size: 1.1rem;
  font-weight: 750;
  letter-spacing: -0.02em;
}

.effective-state {
  display: inline-flex;
  min-height: 1.8rem;
  max-width: 100%;
  align-items: center;
  gap: 0.45rem;
  padding: 0.3rem 0.6rem;
  color: #4b4452;
  background: #f2f0f4;
  border: 1px solid #e8e4ec;
  border-radius: 99rem;
  font-size: 0.76rem;
  font-weight: 700;
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.card-heading .effective-state {
  flex: 0 1 auto;
  gap: 0.3rem;
  padding: 0.25rem 0.42rem;
  font-size: 0.7rem;
  white-space: nowrap;
}

.state-indicator {
  width: 0.48rem;
  height: 0.48rem;
  flex: 0 0 auto;
  background: currentColor;
  border-radius: 50%;
}

.effective-state[data-effective-state='LIBRE'] {
  color: #285b48;
  background: #edf5f0;
  border-color: #d4e7dc;
}

.effective-state[data-effective-state='OCUPADO'] {
  color: #9f1239;
  background: #fff1f4;
  border-color: #f8b4c8;
}

.effective-state[data-effective-state='NO_DISPONIBLE'] {
  color: #745126;
  background: #faf3e8;
  border-color: #efe1c8;
}

.effective-state[data-effective-state='DESCONOCIDO'] {
  color: #55515c;
  background: #f1f0f2;
  border-color: #e2e0e5;
}

.effective-state.is-refreshing {
  background: #f2f0f4;
  border-color: #e8e4ec;
}

.state-details {
  display: grid;
  gap: 0.72rem;
  margin: 0;
}

.manage-button {
  width: 100%;
  min-height: 2.6rem;
  margin-top: 0.1rem;
  color: #5c3a86;
  background: #ffffff;
  border-color: #d9cde3;
}

.manage-button:hover:not(:disabled) {
  color: #ffffff;
}

.management-feedback {
  margin: 0 0 1rem;
  padding: 0.8rem 0.95rem;
  color: #285b48;
  background: #edf5f0;
  border: 1px solid #d4e7dc;
  border-radius: 0.7rem;
  font-size: 0.85rem;
  line-height: 1.5;
}

.management-feedback-error {
  color: #8a3d3d;
  background: #fbefef;
  border-color: #efd9d9;
}

.state-details > div {
  display: grid;
  grid-template-columns: minmax(6.7rem, 0.85fr) minmax(0, 1.15fr);
  align-items: start;
  gap: 0.55rem;
}

.state-details > .operational-state-row {
  position: relative;
  display: flex;
  min-width: 0;
  align-items: flex-start;
}

.operational-state-label {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.state-details dt {
  color: #746f7b;
  font-size: 0.74rem;
  font-weight: 600;
  line-height: 1.45;
}

.state-details dd {
  min-width: 0;
  margin: 0;
  color: #302b35;
  font-size: 0.78rem;
  font-weight: 650;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.operational-state-value {
  display: inline-flex;
  min-height: 1.5rem;
  align-items: center;
  padding: 0.2rem 0.5rem;
  color: #55515c;
  background: #f1f0f2;
  border: 1px solid #e2e0e5;
  border-radius: 99rem;
  font-size: 0.7rem;
  font-weight: 700;
  line-height: 1.25;
}

.operational-state-value[data-operational-state='DISPONIBLE'] {
  color: #285b48;
  background: #edf5f0;
  border-color: #d4e7dc;
}

.operational-state-value[data-operational-state='MANTENIMIENTO'] {
  color: #745126;
  background: #faf3e8;
  border-color: #efe1c8;
}

.operational-state-value[data-operational-state='FUERA_DE_SERVICIO'] {
  color: #9f1239;
  background: #fff1f4;
  border-color: #f8b4c8;
}

.operational-reason dd {
  font-weight: 550;
}

.loading-state,
.feedback-panel,
.empty-state {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 1rem;
  padding: clamp(1.1rem, 2.5cqi, 1.6rem);
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 0.9rem;
  box-shadow: 0 0.65rem 1.8rem rgb(37 28 47 / 3.5%);
}

.loading-state h2,
.feedback-panel h2,
.empty-state h2 {
  margin: 0;
  color: #302b35;
  font-size: 1rem;
  font-weight: 750;
  line-height: 1.4;
}

.loading-state p,
.feedback-panel p,
.empty-state p {
  margin: 0.35rem 0 0;
  color: #746f7b;
  font-size: 0.86rem;
  line-height: 1.55;
}

.loading-mark {
  width: 1.1rem;
  height: 1.1rem;
  flex: 0 0 auto;
  border: 2px solid #e4ddeb;
  border-top-color: #5c3a86;
  border-radius: 50%;
  animation: spin 750ms linear infinite;
}

.feedback-panel {
  justify-content: space-between;
  border-color: #eadbd8;
}

.refresh-error {
  box-shadow: none;
}

@keyframes parking-data-skeleton {
  to {
    background-position: -200% 0;
  }
}

.empty-state {
  flex-direction: column;
  align-items: flex-start;
  padding: clamp(1.4rem, 3cqi, 2rem);
}

.empty-mark {
  display: grid;
  width: 2.7rem;
  height: 2.7rem;
  place-items: center;
  color: #5c3a86;
  background: #f1edf5;
  border: 1px solid #e5dceb;
  border-radius: 0.8rem;
  font-size: 1.15rem;
  font-weight: 750;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@container (max-width: 52rem) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .summary-card:nth-child(odd) {
    border-left: 0;
  }

  .summary-card:nth-child(n + 3) {
    border-top: 1px solid #eeebf0;
  }

  .parking-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@container (max-width: 34rem) {
  .page-heading {
    align-items: flex-start;
  }

  .summary-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .summary-card + .summary-card {
    border-top: 1px solid #eeebf0;
    border-left: 0;
  }

  .summary-card:nth-child(n + 3) {
    border-top: 1px solid #eeebf0;
  }

  .parking-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .state-details > div {
    grid-template-columns: minmax(6.7rem, 0.85fr) minmax(0, 1.15fr);
  }
}

@media (prefers-reduced-motion: reduce) {
  .loading-mark {
    animation: none;
  }

  .refresh-skeleton {
    animation: none;
  }

  .refresh-button,
  .retry-button,
  .manage-button {
    transition: none;
  }
}
</style>
