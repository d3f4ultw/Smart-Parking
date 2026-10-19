<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { RespuestaConfiguracionVision, ZonaVisionWeb } from '~/utils/vision-api'
import { colorVisionZona } from '~/utils/vision-zone-colors'
import {
  escucharCambioConfiguracionVision,
  esCambioConfiguracionRemoto,
  notificarCambioConfiguracionVision,
} from '~/utils/vision-config-sync'
import { crearActualizadorCoalescido, puedeAplicarRevisionVision } from '~/utils/vision-config-refresh'
import { abrirEditorVision, type AbrirEditorVision, type ModoEditorVision } from '~/utils/vision-zone-actions'
import {
  claveReservaEditorVision,
  editorVisionYaAbierto,
  guardarReservaEditorVision,
  liberarReservaEditorVision,
} from '~/utils/vision-editor-tabs'

definePageMeta({ layout: 'admin', middleware: 'sesion-owner' })

type EstadoZona = {
  numero: number
  estado: 'DESCONOCIDO' | 'LIBRE' | 'CANDIDATO_OCUPADO' | 'OCUPADO'
}
type EstadoMonitoreo = {
  configuration_revision: number
  zone_states: EstadoZona[]
}

const vision = useVisionAuthorization()
const fetchVision = $fetch.create({
  credentials: 'same-origin',
  cache: 'no-store',
  timeout: 10_000,
})
const configuracion = ref<RespuestaConfiguracionVision | null>(null)
const estado = ref<EstadoMonitoreo | null>(null)
const cargando = ref(true)
const eliminando = ref(false)
const error = ref('')
const mensaje = ref('')
const zonaPendienteEliminar = ref<ZonaVisionWeb | null>(null)
const abrirEnCurso = ref(false)
const referenciaTituloCajones = ref<HTMLHeadingElement | null>(null)
const botonCancelarRetiro = ref<HTMLButtonElement | null>(null)
const referenciaDialogoRetiro = ref<HTMLElement | null>(null)
let focoAnteriorRetiro: HTMLElement | null = null
let temporizadorActualizacion: number | null = null
let detenerEscuchaConfiguracion: (() => void) | null = null
let manejadorVisibilidad: (() => void) | null = null
let origenSincronizacion = ''
let secuenciaConfiguracion = 0

function obtenerMensaje(errorHttp: unknown): number | null {
  if (errorHttp === null || typeof errorHttp !== 'object') return null
  const valor = errorHttp as { status?: unknown; statusCode?: unknown }
  return typeof valor.statusCode === 'number'
    ? valor.statusCode
    : typeof valor.status === 'number'
      ? valor.status
      : null
}

async function cargarConfiguracion() {
  if (!vision.autorizado.value) return
  const secuencia = ++secuenciaConfiguracion
  try {
    const respuesta = await fetchVision<RespuestaConfiguracionVision>(
      '/api/admin/vision/configuration',
    )
    if (secuencia !== secuenciaConfiguracion) return
    if (!puedeAplicarRevisionVision(configuracion.value?.revision ?? null, respuesta.revision)) return
    configuracion.value = respuesta
  } catch (fallo: unknown) {
    if (secuencia !== secuenciaConfiguracion) return
    error.value = 'No se pudieron cargar los cajones.'
    await vision.manejarErrorProtegido(fallo)
  }
}

async function cargarEstado() {
  if (!vision.autorizado.value) return
  try {
    const respuesta = await fetchVision<EstadoMonitoreo>('/api/admin/vision/monitor/status')
    if (
      estado.value !== null
      && respuesta.configuration_revision < estado.value.configuration_revision
    ) return
    estado.value = respuesta
  } catch (fallo: unknown) {
    estado.value = null
    await vision.manejarErrorProtegido(fallo)
  }
}

const actualizarDatos = crearActualizadorCoalescido(async () => {
  if (!vision.autorizado.value) return
  cargando.value = true
  error.value = ''
  try {
    await Promise.allSettled([cargarConfiguracion(), cargarEstado()])
  } finally {
    cargando.value = false
  }
})

function estadoZona(numero: number): string {
  if (estado.value === null || configuracion.value === null) return 'SIN DATOS'
  if (estado.value.configuration_revision !== configuracion.value.revision) return 'ACTUALIZANDO'
  const actual = estado.value.zone_states.find(zona => zona.numero === numero)?.estado
  if (actual === undefined || actual === 'DESCONOCIDO') return 'SIN DATOS'
  return actual
}

function claseEstado(numero: number): string {
  const valor = estadoZona(numero)
  const clases: Record<string, string> = {
    LIBRE: 'state-free',
    OCUPADO: 'state-occupied',
    CANDIDATO_OCUPADO: 'state-candidate',
    ACTUALIZANDO: 'state-updating',
    'SIN DATOS': 'state-unknown',
  }
  return clases[valor] ?? 'state-unknown'
}

function solicitarAperturaEditor(modo: ModoEditorVision, zoneId?: string) {
  if (abrirEnCurso.value) return
  abrirEnCurso.value = true
  error.value = ''
  mensaje.value = ''
  const clave = claveReservaEditorVision(zoneId)
  const pendiente = 'pending-' + crypto.randomUUID()
  try {
    if (editorVisionYaAbierto(window.localStorage, clave)) {
      error.value = 'Ya hay un editor abierto para esta zona en otra pestaña.'
      abrirEnCurso.value = false
      return
    }
    guardarReservaEditorVision(window.localStorage, clave, pendiente)
  } catch {
    // El editor sigue disponible si el navegador bloquea el almacenamiento local.
  }

  let abierto = false
  const abrir: AbrirEditorVision = (url, destino) => {
    const ventana = window.open(url, destino)
    if (ventana) {
      ventana.opener = null
      abierto = true
    }
    return ventana
  }
  abrirEditorVision(abrir, modo, zoneId)
  if (!abierto) {
    error.value = 'El navegador bloqueó la pestaña nueva. Permite ventanas emergentes e inténtalo otra vez.'
    try {
      liberarReservaEditorVision(window.localStorage, clave, pendiente)
    } catch {
      // No se requiere almacenamiento para el flujo del editor.
    }
    abrirEnCurso.value = false
    return
  }
  window.setTimeout(() => {
    try {
      liberarReservaEditorVision(window.localStorage, clave, pendiente)
    } catch {
      // La pestaña ya mantiene su propia reserva si el almacenamiento está disponible.
    }
    abrirEnCurso.value = false
  }, 600)
}

function solicitarEliminacion(zona: ZonaVisionWeb) {
  if (import.meta.client && document.activeElement instanceof HTMLElement) {
    focoAnteriorRetiro = document.activeElement
  }
  zonaPendienteEliminar.value = zona
  error.value = ''
  mensaje.value = ''
  void nextTick(() => botonCancelarRetiro.value?.focus())
}

function cancelarEliminacion() {
  if (eliminando.value) return
  zonaPendienteEliminar.value = null
  restaurarFocoRetiro()
}

function restaurarFocoRetiro() {
  void nextTick(() => {
    if (focoAnteriorRetiro?.isConnected) focoAnteriorRetiro.focus()
    else referenciaTituloCajones.value?.focus()
    focoAnteriorRetiro = null
  })
}

function mantenerFocoEnDialogo(evento: KeyboardEvent) {
  if (evento.key !== 'Tab' || referenciaDialogoRetiro.value === null) return
  const botones = referenciaDialogoRetiro.value.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')
  if (botones.length === 0) {
    evento.preventDefault()
    referenciaDialogoRetiro.value.focus()
    return
  }
  const primero = botones.item(0)
  const ultimo = botones.item(botones.length - 1)
  if (primero === null || ultimo === null) return
  if (evento.shiftKey && document.activeElement === primero) {
    evento.preventDefault()
    ultimo.focus()
  } else if (!evento.shiftKey && document.activeElement === ultimo) {
    evento.preventDefault()
    primero.focus()
  }
}

async function confirmarEliminacion() {
  const zona = zonaPendienteEliminar.value
  const actual = configuracion.value
  if (zona === null || actual === null || eliminando.value) return
  eliminando.value = true
  error.value = ''
  mensaje.value = ''
  try {
    const requestId = crypto.randomUUID()
    const respuesta = await fetchVision<RespuestaConfiguracionVision>(
      '/api/admin/vision/configuration',
      {
        method: 'PUT',
        body: {
          request_id: requestId,
          expected_revision: actual.revision,
          zones: actual.zones
            .filter(elemento => elemento.vision_zone_id !== zona.vision_zone_id)
            .map(elemento => ({
              vision_zone_id: elemento.vision_zone_id,
              numero: elemento.numero,
              polygon: elemento.polygon,
            })),
        },
      },
    )
    if (puedeAplicarRevisionVision(configuracion.value?.revision ?? null, respuesta.revision)) {
      configuracion.value = respuesta
    }
    zonaPendienteEliminar.value = null
    mensaje.value = 'El cajón C' + zona.numero + ' fue retirado; su historial se conservó.'
    restaurarFocoRetiro()
    notificarCambioConfiguracionVision(origenSincronizacion)
    await cargarEstado()
  } catch (fallo: unknown) {
    if (obtenerMensaje(fallo) === 409) {
      error.value = 'La configuración cambió en otra pestaña. No se retiró ningún cajón; se cargaron los cambios recientes.'
      zonaPendienteEliminar.value = null
      restaurarFocoRetiro()
      await cargarConfiguracion()
      await cargarEstado()
    } else {
      error.value = 'No se pudo retirar el cajón. La configuración guardada permanece sin cambios.'
    }
    await vision.manejarErrorProtegido(fallo)
  } finally {
    eliminando.value = false
  }
}

function abrirNuevoEditor() {
  solicitarAperturaEditor('nuevo')
}

function abrirEditorZona(zona: ZonaVisionWeb) {
  solicitarAperturaEditor('editar', zona.vision_zone_id)
}

function alCambiarConfiguracion(origenMensaje: string | null) {
  if (!esCambioConfiguracionRemoto(origenSincronizacion, origenMensaje)) return
  void actualizarDatos()
}

function alVolverVisible() {
  if (document.visibilityState === 'visible') void actualizarDatos()
}

watch(vision.autorizado, (autorizado) => {
  if (autorizado) void actualizarDatos()
  else {
    configuracion.value = null
    estado.value = null
  }
}, { immediate: true })

onMounted(() => {
  origenSincronizacion = crypto.randomUUID()
  detenerEscuchaConfiguracion = escucharCambioConfiguracionVision(alCambiarConfiguracion)
  manejadorVisibilidad = alVolverVisible
  document.addEventListener('visibilitychange', manejadorVisibilidad)
  temporizadorActualizacion = window.setInterval(() => {
    if (document.visibilityState === 'visible') void cargarEstado()
  }, 5_000)
})

onBeforeUnmount(() => {
  if (temporizadorActualizacion !== null) window.clearInterval(temporizadorActualizacion)
  if (manejadorVisibilidad !== null) document.removeEventListener('visibilitychange', manejadorVisibilidad)
  detenerEscuchaConfiguracion?.()
})
</script>

<template>
  <AdminVisionAuthorizationGate
    titulo="Cajones del estacionamiento"
    descripcion="Ingresa la contraseña administrativa para consultar y editar los cajones."
  >
    <main class="zones-page">
      <header class="page-heading">
        <div>
          <p class="eyebrow">ESTACIONAMIENTO</p>
          <h1 ref="referenciaTituloCajones" tabindex="-1">Cajones del estacionamiento</h1>
          <p class="page-subtitle">Crea, edita o retira cajones. La cámara se activa al abrir el editor.</p>
        </div>
        <div class="heading-actions">
          <button class="secondary-button" type="button" :disabled="cargando" @click="actualizarDatos">Actualizar</button>
          <button class="primary-button" type="button" :disabled="cargando || abrirEnCurso" @click="abrirNuevoEditor">Nuevo cajón</button>
        </div>
      </header>

      <p v-if="mensaje" class="notice-success" role="status">{{ mensaje }}</p>
      <p v-if="error" class="notice-error" role="alert">{{ error }}</p>

      <section class="zones-panel" aria-labelledby="zones-title">
        <div class="panel-heading">
          <div>
            <h2 id="zones-title">Cajones registrados</h2>
            <p>{{ configuracion?.zones.length ?? 0 }} activos</p>
          </div>
        </div>

        <div v-if="cargando && configuracion === null" class="loading-state" role="status">
          Cargando configuración protegida…
        </div>
        <div v-else-if="(configuracion?.zones.length ?? 0) === 0" class="empty-state">
          <span class="empty-icon" aria-hidden="true">⌑</span>
          <h3>Todavía no hay cajones</h3>
          <p>Selecciona Nuevo cajón y marca los puntos sobre la imagen.</p>
          <button class="primary-button" type="button" :disabled="abrirEnCurso" @click="abrirNuevoEditor">Nuevo cajón</button>
        </div>
        <ul v-else class="zone-list">
          <li v-for="zona in configuracion?.zones" :key="zona.vision_zone_id" class="zone-row">
            <span class="zone-swatch" :style="{ backgroundColor: colorVisionZona(zona.numero) }" aria-hidden="true" />
            <div class="zone-identity">
              <strong>C{{ zona.numero }}</strong>
              <small>Cajón activo · {{ zona.polygon.length }} puntos</small>
            </div>
            <span class="occupancy-state" :class="claseEstado(zona.numero)">
              <span class="state-dot" />
              {{ estadoZona(zona.numero) }}
            </span>
            <div class="zone-actions">
              <button class="edit-button" type="button" :disabled="abrirEnCurso" :aria-label="'Editar cajón C' + zona.numero" @click="abrirEditorZona(zona)">Editar</button>
              <button class="delete-button" type="button" :disabled="eliminando" :aria-label="'Retirar cajón C' + zona.numero" @click="solicitarEliminacion(zona)">Retirar</button>
            </div>
          </li>
        </ul>
      </section>

      <div v-if="zonaPendienteEliminar" class="dialog-backdrop" @click.self="cancelarEliminacion">
        <section
          ref="referenciaDialogoRetiro"
          class="delete-dialog"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="delete-title"
          aria-describedby="delete-description"
          tabindex="-1"
          @keydown.esc.prevent.stop="cancelarEliminacion"
          @keydown.tab="mantenerFocoEnDialogo"
        >
          <span class="dialog-icon" aria-hidden="true">!</span>
          <h2 id="delete-title">Retirar cajón C{{ zonaPendienteEliminar.numero }}?</h2>
          <p id="delete-description">El cajón dejará de participar en el estacionamiento activo. Su historial se conservará y su número no se reutilizará.</p>
          <p v-if="error" class="dialog-error" role="alert">{{ error }}</p>
          <div class="dialog-actions">
            <button ref="botonCancelarRetiro" class="secondary-button" type="button" :disabled="eliminando" @click="cancelarEliminacion">Cancelar</button>
            <button class="delete-confirm-button" type="button" :disabled="eliminando" @click="confirmarEliminacion">
              {{ eliminando ? 'Retirando cajón…' : 'Retirar cajón' }}
            </button>
          </div>
        </section>
      </div>
    </main>
  </AdminVisionAuthorizationGate>
</template>

<style scoped>
.zones-page { width: 100%; min-width: 0; min-height: 0; margin: 0; padding: 0; color: var(--admin-foreground); }
.page-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 26px; }
.eyebrow { margin: 0 0 7px; color: var(--admin-accent); font-size: .69rem; font-weight: 800; letter-spacing: .15em; }
h1 { margin: 0; font-size: clamp(1.7rem, 3vw, 2.25rem); letter-spacing: -.04em; }
h1:focus { outline: 2px solid var(--admin-focus); outline-offset: 4px; }
.page-subtitle { max-width: 680px; margin: 9px 0 0; color: var(--admin-muted); font-size: .9rem; line-height: 1.55; }
.heading-actions,.zone-actions,.dialog-actions { display: flex; align-items: center; gap: 9px; }
.primary-button,.secondary-button,.edit-button,.delete-button,.delete-confirm-button { min-height: 44px; padding: 0 13px; border-radius: 10px; font: inherit; font-size: .8rem; font-weight: 700; cursor: pointer; }
.primary-button { border: 0; color: #fff; background: var(--admin-accent); }
.primary-button:hover:not(:disabled) { background: var(--admin-accent-hover); }
.secondary-button { border: 1px solid var(--admin-border); color: var(--admin-foreground); background: var(--admin-surface); }
.secondary-button:hover:not(:disabled) { border-color: var(--admin-accent); }
.primary-button:disabled,.secondary-button:disabled,.edit-button:disabled,.delete-button:disabled,.delete-confirm-button:disabled { opacity: .5; cursor: not-allowed; }
.zones-panel { overflow: hidden; border: 1px solid var(--admin-border); border-radius: 14px; background: var(--admin-surface); }
.panel-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 19px 20px; border-bottom: 1px solid var(--admin-border); }
.panel-heading h2 { margin: 0; color: var(--admin-foreground); font-size: 1rem; }
.panel-heading p { margin: 5px 0 0; color: var(--admin-muted); font-size: .76rem; }
.zone-list { overflow: hidden; padding: 0; margin: 12px 14px 14px; list-style: none; border: 1px solid var(--admin-border); border-radius: 10px; background: var(--admin-surface-soft); }
.zone-row { display: grid; grid-template-columns: 15px minmax(110px,1fr) minmax(125px,.7fr) auto; align-items: center; gap: 15px; min-height: 72px; padding: 12px 18px; transition: background-color 150ms ease; }
.zone-row + .zone-row { border-top: 1px solid var(--admin-border); }
.zone-row:hover { background: var(--admin-surface); }
.zone-swatch { width: 13px; height: 13px; border: 1px solid #0002; border-radius: 50%; box-shadow: 0 0 0 3px color-mix(in srgb,var(--admin-surface) 80%,white); }
.zone-identity { display: grid; gap: 4px; }
.zone-identity strong { color: var(--admin-foreground); font-size: .9rem; }
.zone-identity small { color: var(--admin-muted); font-size: .72rem; }
.occupancy-state { display: inline-flex; align-items: center; gap: 7px; color: var(--admin-muted); font-size: .71rem; font-weight: 750; letter-spacing: .035em; }
.state-dot { width: 7px; height: 7px; border-radius: 50%; background: #8b96a2; }
.state-free { color: #258064; }
.state-free .state-dot { background: #2fa67f; }
.state-occupied { color: #b24d46; }
.state-occupied .state-dot { background: #d65b52; }
.state-candidate { color: #a8781d; }
.state-candidate .state-dot { background: #daa73b; }
.state-updating { color: #7a6a9b; }
.edit-button { border: 1px solid var(--admin-border); color: var(--admin-accent); background: transparent; }
.edit-button:hover:not(:disabled) { border-color: var(--admin-accent); background: var(--admin-surface-soft); }
.delete-button { border: 1px solid transparent; color: #a14d4d; background: transparent; }
.delete-button:hover:not(:disabled) { border-color: #e7bebe; background: #fff4f4; }
.loading-state,.empty-state { padding: 44px 20px; color: var(--admin-muted); text-align: center; }
.empty-icon { display: grid; place-items: center; width: 48px; height: 48px; margin: 0 auto 13px; border-radius: 13px; color: var(--admin-accent); background: var(--admin-surface-soft); font-size: 1.8rem; }
.empty-state h3 { margin: 0; color: var(--admin-foreground); font-size: 1rem; }
.empty-state p { margin: 7px 0 17px; font-size: .82rem; }
.notice-error,.notice-success { margin: 0 0 14px; padding: 11px 13px; border-radius: 8px; font-size: .8rem; }
.notice-error { color: #9a343f; background: #fff0f0; }
.notice-success { color: #18745e; background: #e8f7f1; }
.dialog-backdrop { position: fixed; z-index: 1000; inset: 0; display: grid; place-items: center; padding: 18px; background: rgb(12 16 22 / 55%); backdrop-filter: blur(2px); }
.delete-dialog { width: min(100%, 410px); padding: 24px; border: 1px solid var(--admin-border); border-radius: 14px; background: var(--admin-surface); box-shadow: 0 24px 70px #0003; }
.dialog-icon { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 9px; color: #a14d4d; background: #faeaea; font-weight: 900; }
.delete-dialog h2 { margin: 15px 0 7px; color: var(--admin-foreground); font-size: 1.12rem; }
.delete-dialog p { margin: 0; color: var(--admin-muted); font-size: .82rem; line-height: 1.55; }
.delete-dialog .dialog-error { margin-top: 12px; color: #9a343f; font-weight: 700; }
.dialog-actions { justify-content: end; margin-top: 22px; }
.delete-confirm-button { border: 0; color: #fff; background: #aa4545; }
.delete-confirm-button:hover:not(:disabled) { background: #8f3535; }
.primary-button:focus-visible,.secondary-button:focus-visible,.edit-button:focus-visible,.delete-button:focus-visible,.delete-confirm-button:focus-visible { outline: 3px solid var(--admin-focus); outline-offset: 2px; }
.delete-dialog:focus { outline: 2px solid var(--admin-focus); outline-offset: 3px; }
@media (max-width: 760px) { .page-heading { align-items: start; flex-direction: column; } .heading-actions { width: 100%; justify-content: space-between; } .zone-row { grid-template-columns: 14px minmax(80px,1fr) auto; gap: 10px; padding: 12px; } .occupancy-state { grid-column: 2; grid-row: 2; } .zone-actions { grid-column: 3; grid-row: 1 / span 2; } .panel-heading { align-items: start; flex-direction: column; padding: 15px; } }
</style>
