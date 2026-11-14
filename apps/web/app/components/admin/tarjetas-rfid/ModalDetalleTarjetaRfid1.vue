<script setup lang="ts">
import { nextTick, onScopeDispose, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { crearRetornoFocoRfid1 } from '~/composables/useRetornoFocoRfid1'
import type { TarjetaRfid1 } from '~/types/rfid1'
import { ErrorRfid1Api, useClienteRfid1 } from '~/utils/rfid1-api'

const props = defineProps<{
  open: boolean
  asociacionId: number | null
  mostrarUid: boolean
}>()
const emit = defineEmits<{
  'update:open': [valor: boolean]
  actualizada: []
}>()

const api = useClienteRfid1()
const csrf = useCsrf()
const sesion = useSesion()
const tarjeta = ref<TarjetaRfid1 | null>(null)
const cargando = ref(false)
const confirmacionAbierta = ref(false)
const ocupada = ref(false)
const mensajeError = ref('')
const mensajeEstado = ref('')
const encabezadoConfirmacion = ref<HTMLElement | null>(null)
let secuenciaConsulta = 0
let controladorConsulta: AbortController | null = null
let asociacionIdDisparadora: number | null = null
const uiModal = {
  overlay: 'bg-black/55',
  content:
    'w-[calc(100vw-2rem)] max-w-xl rounded-2xl border border-[var(--app-border)] bg-white shadow-xl',
  header: 'px-5 py-4 sm:px-6',
  title: 'text-lg font-semibold',
  body: 'px-5 pb-5 sm:px-6 sm:pb-6',
}

function crearConsultaTarjeta(id: number) {
  controladorConsulta?.abort()
  const controlador = new AbortController()
  const solicitud = ++secuenciaConsulta
  controladorConsulta = controlador
  return {
    controlador,
    vigente: () =>
      !controlador.signal.aborted &&
      solicitud === secuenciaConsulta &&
      props.open &&
      props.asociacionId === id,
  }
}

async function leerTarjeta(id: number, consulta: ReturnType<typeof crearConsultaTarjeta>) {
  const respuesta = await api.consultarTarjeta(id, consulta.controlador.signal)
  if (!consulta.vigente()) return null
  tarjeta.value = respuesta
  return respuesta
}

function invalidarConsulta() {
  secuenciaConsulta += 1
  controladorConsulta?.abort()
  controladorConsulta = null
  cargando.value = false
}

async function cargar() {
  const id = props.asociacionId
  if (!import.meta.client || !props.open || !id) return
  const consulta = crearConsultaTarjeta(id)
  tarjeta.value = null
  cargando.value = true
  mensajeError.value = ''
  try {
    await leerTarjeta(id, consulta)
  } catch (fallo) {
    if (!consulta.vigente()) return
    if (fallo instanceof ErrorRfid1Api && fallo.estado === 401) {
      await manejarSesionExpirada()
    } else {
      mensajeError.value =
        fallo instanceof ErrorRfid1Api ? fallo.message : 'No pudimos cargar la tarjeta.'
    }
  } finally {
    if (consulta.vigente()) {
      cargando.value = false
      controladorConsulta = null
    }
  }
}

function limpiar() {
  invalidarConsulta()
  tarjeta.value = null
  confirmacionAbierta.value = false
  mensajeError.value = ''
  mensajeEstado.value = ''
}

async function manejarSesionExpirada() {
  ocupada.value = false
  limpiar()
  await sesion.limpiar()
  await navigateTo('/panel')
}

function cerrar() {
  if (ocupada.value) return
  limpiar()
  emit('update:open', false)
}

const devolverFoco = crearRetornoFocoRfid1(
  () =>
    (asociacionIdDisparadora === null
      ? null
      : document.getElementById(`rfid-detalle-${asociacionIdDisparadora}`)) ??
    document.getElementById('titulo-contenido-tarjetas'),
)

function fecha(valor: string | null) {
  if (!valor) return '—'
  const instante = new Date(valor)
  if (!Number.isFinite(instante.getTime())) return '—'
  return new Intl.DateTimeFormat('es-MX', {
    dateStyle: 'medium',
  }).format(instante)
}

async function abrirConfirmacion() {
  if (tarjeta.value?.estado !== 'ACTIVA' || ocupada.value) return
  confirmacionAbierta.value = true
  await nextTick()
  encabezadoConfirmacion.value?.focus()
}

async function volverADetalle() {
  if (ocupada.value) return
  confirmacionAbierta.value = false
  await nextTick()
  document.getElementById('accion-cancelar-tarjeta')?.focus()
}

async function confirmarCancelacion() {
  const actual = tarjeta.value
  if (!actual || actual.estado !== 'ACTIVA' || ocupada.value) return
  const consulta = crearConsultaTarjeta(actual.asociacionId)
  ocupada.value = true
  mensajeError.value = ''
  mensajeEstado.value = ''
  try {
    await api.cancelarTarjeta(actual.asociacionId, await csrf.obtener())
    if (!consulta.vigente()) return
    const actualizada = await leerTarjeta(actual.asociacionId, consulta)
    if (!actualizada || !consulta.vigente()) return
    if (actualizada.estado !== 'CANCELADA') {
      mensajeError.value =
        'La tarjeta sigue activa. Consulta el estado antes de volver a intentarlo.'
      return
    }
    confirmacionAbierta.value = false
    mensajeEstado.value = 'Tarjeta cancelada permanentemente.'
    emit('actualizada')
  } catch (fallo) {
    if (!consulta.vigente()) return
    if (fallo instanceof ErrorRfid1Api && fallo.estado === 401) {
      await manejarSesionExpirada()
      return
    }
    try {
      const actualizada = await leerTarjeta(actual.asociacionId, consulta)
      if (!consulta.vigente()) return
      if (actualizada?.estado === 'CANCELADA') {
        confirmacionAbierta.value = false
        mensajeEstado.value = 'Tarjeta cancelada permanentemente.'
        emit('actualizada')
        return
      }
    } catch (reconciliacion) {
      if (!consulta.vigente()) return
      if (reconciliacion instanceof ErrorRfid1Api && reconciliacion.estado === 401) {
        await manejarSesionExpirada()
        return
      }
    }
    mensajeError.value =
      fallo instanceof ErrorRfid1Api
        ? fallo.message
        : 'No se pudo confirmar la cancelación. Consulta el estado antes de reintentar.'
  } finally {
    ocupada.value = false
    if (consulta.vigente()) controladorConsulta = null
  }
}

watch(
  () => [props.open, props.asociacionId] as const,
  ([abierta]) => {
    if (abierta) {
      asociacionIdDisparadora = props.asociacionId
      tarjeta.value = null
      void cargar()
    } else limpiar()
  },
)

onBeforeRouteLeave(() => !ocupada.value)

onScopeDispose(() => {
  invalidarConsulta()
  tarjeta.value = null
})
</script>

<template>
  <UModal
    :open="props.open"
    :close="false"
    :dismissible="!ocupada"
    :ui="uiModal"
    title="Detalles de tarjeta"
    :content="{ onCloseAutoFocus: devolverFoco }"
    @update:open="(abierta) => !abierta && cerrar()"
  >
    <template #body>
      <div class="detalle-tarjeta-rfid" :aria-busy="cargando || ocupada">
        <p v-if="cargando" class="estado-detalle-rfid" role="status">Cargando…</p>
        <div v-else-if="mensajeError && !tarjeta" class="error-carga-detalle-rfid">
          <p class="mensaje-error-detalle-rfid" role="alert">{{ mensajeError }}</p>
          <UButton color="neutral" variant="outline" @click="cargar">Reintentar</UButton>
        </div>
        <template v-else-if="tarjeta">
          <div class="resumen-tarjeta-rfid">
            <div v-if="props.mostrarUid && tarjeta.uid !== null" class="uid-tarjeta-rfid">
              <span>UID</span>
              <code>{{ tarjeta.uid }}</code>
            </div>
            <UBadge :color="tarjeta.estado === 'ACTIVA' ? 'success' : 'neutral'" variant="soft">
              {{ tarjeta.estado === 'ACTIVA' ? 'Activa' : 'Cancelada' }}
            </UBadge>
          </div>

          <section class="persona-tarjeta-rfid" aria-labelledby="titulo-persona-tarjeta">
            <h2 id="titulo-persona-tarjeta">Persona asociada</h2>
            <p class="nombre-persona-rfid">{{ tarjeta.nombreCompleto || '—' }}</p>
            <p class="referencia-persona-rfid">
              <span>{{ tarjeta.tipoEntidad === 'CLIENTE' ? 'Cliente' : 'Empleado' }}</span>
              <span aria-hidden="true">·</span>
              <span>{{ tarjeta.codigoPersona || '—' }}</span>
            </p>
          </section>

          <dl class="fecha-asociacion-rfid">
            <div>
              <dt>Fecha de asociación</dt>
              <dd>{{ fecha(tarjeta.asociadaEn) }}</dd>
            </div>
          </dl>
        </template>

        <UAlert
          v-if="mensajeEstado"
          color="success"
          variant="soft"
          icon="i-lucide-circle-check"
          :title="mensajeEstado"
          role="status"
        />
        <p v-if="mensajeError && tarjeta" class="mensaje-error-detalle-rfid" role="alert">
          {{ mensajeError }}
        </p>

        <section
          v-if="confirmacionAbierta && tarjeta?.estado === 'ACTIVA'"
          class="confirmacion-cancelacion-rfid"
          aria-labelledby="titulo-confirmacion-tarjeta"
        >
          <h2 id="titulo-confirmacion-tarjeta" ref="encabezadoConfirmacion" tabindex="-1">
            ¿Cancelar esta tarjeta?
          </h2>
          <p>
            La cancelación es permanente. No podrás reactivar ni reasignar esta tarjeta. Se
            {{
              props.mostrarUid
                ? 'conservarán su UID y su historial.'
                : 'conservará el historial de esta asociación.'
            }}
          </p>
          <div class="acciones-confirmacion-rfid">
            <UButton color="neutral" variant="outline" :disabled="ocupada" @click="volverADetalle">
              Volver
            </UButton>
            <UButton
              color="error"
              :loading="ocupada"
              :disabled="ocupada"
              @click="confirmarCancelacion"
            >
              Confirmar cancelación
            </UButton>
          </div>
        </section>

        <footer class="acciones-detalle-rfid">
          <UButton color="neutral" variant="ghost" :disabled="ocupada" @click="cerrar">
            Cerrar
          </UButton>
          <UButton
            v-if="tarjeta?.estado === 'ACTIVA' && !confirmacionAbierta"
            id="accion-cancelar-tarjeta"
            color="error"
            variant="outline"
            :disabled="ocupada"
            @click="abrirConfirmacion"
          >
            Cancelar tarjeta
          </UButton>
        </footer>
      </div>
    </template>
  </UModal>
</template>

<style scoped>
.detalle-tarjeta-rfid {
  display: grid;
  gap: 16px;
}
.resumen-tarjeta-rfid {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  background: #f9fafb;
  padding: 16px;
}
.uid-tarjeta-rfid {
  display: grid;
  min-width: 0;
  gap: 6px;
}
.uid-tarjeta-rfid span,
.persona-tarjeta-rfid h2,
.fecha-asociacion-rfid dt {
  color: var(--app-muted);
  font-size: 0.8125rem;
}
.uid-tarjeta-rfid code {
  color: var(--app-foreground);
  font-size: 1.125rem;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.persona-tarjeta-rfid {
  display: grid;
  gap: 4px;
  border-bottom: 1px solid var(--app-border);
  padding-bottom: 14px;
}
.persona-tarjeta-rfid h2,
.persona-tarjeta-rfid p {
  margin: 0;
}
.nombre-persona-rfid {
  color: var(--app-foreground);
  font-weight: 600;
  overflow-wrap: anywhere;
}
.referencia-persona-rfid {
  color: var(--app-muted);
  font-size: 0.875rem;
}
.fecha-asociacion-rfid {
  margin: 0;
}
.fecha-asociacion-rfid > div {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px 16px;
}
.fecha-asociacion-rfid dd {
  margin: 0;
  color: var(--app-foreground);
  overflow-wrap: anywhere;
}
.estado-detalle-rfid {
  color: var(--app-muted);
}
.error-carga-detalle-rfid {
  display: grid;
  justify-items: start;
  gap: 12px;
}
.confirmacion-cancelacion-rfid {
  display: grid;
  gap: 12px;
  border: 1px solid color-mix(in srgb, var(--app-error) 40%, white);
  border-radius: 12px;
  padding: 16px;
  background: color-mix(in srgb, var(--app-error) 4%, white);
}
.confirmacion-cancelacion-rfid h2,
.confirmacion-cancelacion-rfid p {
  margin: 0;
}
.confirmacion-cancelacion-rfid h2 {
  font-size: 1rem;
}
.confirmacion-cancelacion-rfid p {
  color: var(--app-muted);
  line-height: 1.5;
}
.acciones-confirmacion-rfid,
.acciones-detalle-rfid {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}
.acciones-detalle-rfid {
  border-top: 1px solid var(--app-border);
  padding-top: 16px;
}
.mensaje-error-detalle-rfid {
  margin: 0;
  color: var(--app-error);
}
@media (max-width: 38rem) {
  .resumen-tarjeta-rfid {
    padding: 14px;
  }
  .fecha-asociacion-rfid > div {
    display: grid;
    gap: 4px;
  }
  .acciones-confirmacion-rfid,
  .acciones-detalle-rfid {
    flex-direction: column-reverse;
  }
  .acciones-confirmacion-rfid :deep(button),
  .acciones-detalle-rfid :deep(button) {
    width: 100%;
    justify-content: center;
  }
}
</style>
