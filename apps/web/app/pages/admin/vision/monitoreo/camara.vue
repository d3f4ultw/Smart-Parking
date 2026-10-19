<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import {
  puedeMantenerStreamVision,
  puedeMostrarFrameAnotadoVision,
} from '~/utils/vision-monitoring'
import { crearCicloVidaVisor } from '~/utils/vision-viewer-lifecycle'

definePageMeta({
  layout: 'vision-editor',
  middleware: 'sesion-owner',
})

useHead({
  link: [
    { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
    { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: 'anonymous' },
    {
      rel: 'stylesheet',
      href: 'https://fonts.googleapis.com/css2?family=Manrope:wght@400..800&display=swap',
    },
  ],
})

type EstadoMonitoreoVision = {
  mode: 'simulation' | 'camera'
  source_connected: boolean
  processing: boolean
  source_fps: number
  inference_fps: number
  configuration_revision: number
  applied_revision: number | null
  frame_fresh: boolean
  annotated_frame_fresh: boolean
  error_code: string | null
}

const vision = useVisionAuthorization()
const fetchVision = $fetch.create({
  credentials: 'same-origin',
  cache: 'no-store',
  timeout: 10_000,
})
const estadoFuente = ref<EstadoMonitoreoVision | null>(null)
const errorEstado = ref('')
const actualizandoEstado = ref(false)
const anchoFrame = ref(0)
const altoFrame = ref(0)
let temporizadorEstado: number | null = null
let limpiezaStream: Promise<void> | null = null
let controladorEstado: AbortController | null = null
let actualizacionesActivas = false
let cicloVidaDocumento: ReturnType<typeof crearCicloVidaVisor> | null = null

const streamMjpeg = useVisionMjpegStream(
  '/api/admin/vision/monitor/stream?tipo=annotated',
  {
    alFallarAutorizacion: fallo => vision.manejarErrorProtegido(fallo),
  },
)

const puedeMantenerStream = computed(() =>
  puedeMantenerStreamVision(estadoFuente.value),
)
const camaraDisponible = computed(() =>
  puedeMostrarFrameAnotadoVision(estadoFuente.value),
)

const streamEnVivo = computed(() =>
  camaraDisponible.value && streamMjpeg.estado.value === 'en-vivo',
)

const etiquetaEstado = computed(() => {
  if (errorEstado.value) return 'Reconectando…'
  const actual = estadoFuente.value
  if (actual === null) return 'Conectando…'
  if (actual.mode !== 'camera') return 'Cámara no disponible'
  if (!actual.source_connected) return 'Cámara desconectada'
  if (!actual.frame_fresh) return 'Esperando imagen…'
  if (!actual.processing || !actual.annotated_frame_fresh) return 'Preparando imagen…'
  if (actual.applied_revision !== actual.configuration_revision) return 'Actualizando vista…'
  if (streamEnVivo.value) return 'En vivo'
  if (streamMjpeg.estado.value === 'desconectado' || streamMjpeg.estado.value === 'reconectando') {
    return 'Reconectando…'
  }
  return 'Conectando…'
})

const mensajeVista = computed(() => {
  const actual = estadoFuente.value
  if (errorEstado.value) return 'No se pudo actualizar la cámara. Intentaremos de nuevo.'
  if (actual === null) return 'Conectando con la cámara…'
  if (actual.mode !== 'camera') return 'La cámara no está disponible por el momento.'
  if (!actual.source_connected) return 'No hay conexión con la cámara.'
  if (!actual.frame_fresh) return 'Esperando una nueva imagen…'
  if (!actual.processing || !actual.annotated_frame_fresh) return 'Preparando la imagen en vivo…'
  if (actual.applied_revision !== actual.configuration_revision) {
    return 'Actualizando la vista…'
  }
  if (streamMjpeg.estado.value === 'desconectado') {
    return 'No se pudo cargar el video. Intentaremos reconectar.'
  }
  if (streamMjpeg.estado.value === 'reconectando') return 'Reconectando…'
  return 'Conectando con la cámara…'
})

async function cargarEstado() {
  if (!actualizacionesActivas || !vision.autorizado.value || controladorEstado !== null) return
  const controlador = new AbortController()
  controladorEstado = controlador
  actualizandoEstado.value = true
  try {
    const estado = await fetchVision<EstadoMonitoreoVision>(
      '/api/admin/vision/monitor/status',
      { signal: controlador.signal },
    )
    if (controladorEstado !== controlador || !actualizacionesActivas) return
    estadoFuente.value = estado
    errorEstado.value = ''
  } catch (fallo: unknown) {
    if (controlador.signal.aborted || controladorEstado !== controlador || !actualizacionesActivas) return
    estadoFuente.value = null
    errorEstado.value = 'No se pudo consultar el estado de la cámara. Se reintentará automáticamente.'
    await vision.manejarErrorProtegido(fallo)
  } finally {
    if (controladorEstado === controlador) {
      controladorEstado = null
      actualizandoEstado.value = false
    }
  }
}

function detenerStream() {
  if (limpiezaStream !== null) return limpiezaStream
  if (streamMjpeg.estado.value === 'detenido' && streamMjpeg.frameUrl.value === '') {
    return Promise.resolve()
  }
  limpiezaStream = streamMjpeg.detener().finally(() => {
    limpiezaStream = null
  })
  return limpiezaStream
}

async function iniciarStream() {
  if (limpiezaStream !== null) await limpiezaStream
  if (!actualizacionesActivas || !vision.autorizado.value || !puedeMantenerStream.value) return
  streamMjpeg.iniciar()
}

function iniciarActualizaciones() {
  if (!import.meta.client || !vision.autorizado.value) return
  actualizacionesActivas = true
  void cargarEstado()
  if (temporizadorEstado === null) {
    temporizadorEstado = window.setInterval(() => void cargarEstado(), 1000)
  }
}

function detenerActualizaciones() {
  actualizacionesActivas = false
  controladorEstado?.abort()
  controladorEstado = null
  actualizandoEstado.value = false
  if (temporizadorEstado !== null) {
    window.clearInterval(temporizadorEstado)
    temporizadorEstado = null
  }
  estadoFuente.value = null
  errorEstado.value = ''
  return detenerStream()
}

function registrarFrame(evento: Event) {
  const imagen = evento.currentTarget
  if (!(imagen instanceof HTMLImageElement)) return
  anchoFrame.value = imagen.naturalWidth
  altoFrame.value = imagen.naturalHeight
  streamMjpeg.registrarFrameMostrado(imagen.currentSrc || imagen.src)
}

function notificarErrorRender(evento: Event) {
  const imagen = evento.currentTarget
  if (!(imagen instanceof HTMLImageElement)) return
  streamMjpeg.notificarErrorRender(imagen.currentSrc || imagen.src)
}

function alOcultarDocumento() {
  void detenerActualizaciones()
}

function alRestaurarDocumento() {
  iniciarActualizaciones()
}

async function cerrarVisor() {
  await detenerActualizaciones()
  window.close()
  if (!window.closed) {
    await navigateTo('/admin/vision/zonas')
  }
}

watch(vision.autorizado, (autorizado) => {
  if (!import.meta.client) return
  if (!autorizado) {
    void detenerActualizaciones()
    return
  }
  iniciarActualizaciones()
}, { immediate: true })

watch([() => vision.autorizado.value, puedeMantenerStream], ([autorizado, disponible]) => {
  if (!import.meta.client) return
  if (actualizacionesActivas && autorizado && disponible) {
    void iniciarStream()
  } else {
    void detenerStream()
  }
}, { immediate: true })

onMounted(() => {
  if (cicloVidaDocumento !== null) return
  cicloVidaDocumento = crearCicloVidaVisor(
    window,
    alOcultarDocumento,
    alRestaurarDocumento,
  )
  cicloVidaDocumento.registrar()
})

onBeforeRouteLeave(async () => {
  await detenerActualizaciones()
})

onBeforeUnmount(() => {
  cicloVidaDocumento?.liberar()
  cicloVidaDocumento = null
  void detenerActualizaciones()
})
</script>

<template>
  <AdminVisionAuthorizationGate
    pantalla-completa
    titulo="Acceso a cámara en vivo"
    descripcion="Autoriza esta sesión de OWNER para ver el stream protegido de Vision."
  >
    <main
      class="camera-viewer"
      :data-vision-stream-state="streamMjpeg.estado.value"
      :data-vision-stream-received="streamMjpeg.framesRecibidos.value"
      :data-vision-stream-rendered="streamMjpeg.framesMostrados.value"
      :data-vision-stream-receive-fps="streamMjpeg.fpsRecepcion.value"
      :data-vision-stream-render-fps="streamMjpeg.fpsRenderizado.value"
      :data-vision-source-width="anchoFrame || ''"
      :data-vision-source-height="altoFrame || ''"
    >
      <header class="camera-toolbar">
        <div class="camera-title">
          <p class="camera-eyebrow">VISION IA</p>
          <h1>Monitoreo Vision</h1>
        </div>

        <div class="camera-status" role="status" aria-live="polite">
          <span class="camera-status-dot" :class="{ 'is-live': streamEnVivo }" />
          <strong>{{ etiquetaEstado }}</strong>
        </div>

        <button class="close-viewer" type="button" @click="cerrarVisor">
          Cerrar vista
        </button>
      </header>

      <section
        class="camera-stage"
        aria-label="Vista en vivo de la cámara"
      >
        <img
          v-if="vision.autorizado.value && camaraDisponible && streamMjpeg.frameUrl.value"
          :src="streamMjpeg.frameUrl.value"
          alt="Vista en vivo de la cámara"
          @load="registrarFrame"
          @error="notificarErrorRender"
        >

        <div
          v-if="!streamEnVivo || anchoFrame === 0"
          class="camera-overlay"
          role="status"
        >
          <span class="camera-spinner" :class="{ 'is-hidden': streamMjpeg.estado.value === 'desconectado' }" />
          <strong>{{ mensajeVista }}</strong>
        </div>
      </section>
    </main>
  </AdminVisionAuthorizationGate>
</template>

<style scoped>
.camera-viewer {
  box-sizing: border-box;
  display: flex;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  gap: 12px;
  padding: clamp(12px, 2vw, 24px);
  overflow: hidden;
  color: #e9edf4;
  background: #0d1117;
  font-family: Manrope, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.camera-toolbar {
  box-sizing: border-box;
  display: flex;
  min-width: 0;
  min-height: 52px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 clamp(10px, 1.4vw, 18px);
  border: 1px solid #293340;
  border-radius: 12px;
  background: #151b24;
}

.camera-title {
  display: grid;
  min-width: 150px;
  gap: 3px;
}

.camera-eyebrow {
  margin: 0 0 4px;
  color: #72b9f4;
  font-size: .66rem;
  font-weight: 800;
  letter-spacing: .14em;
}

h1 {
  margin: 0;
  color: #f2f5fa;
  font-size: clamp(1.08rem, 2vw, 1.35rem);
  font-weight: 750;
  line-height: 1.2;
  letter-spacing: -.025em;
}

.camera-status {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
  margin-left: auto;
  min-height: 36px;
  padding: 0 12px;
  border: 1px solid #303b49;
  border-radius: 999px;
  background: #10161e;
}

.camera-status strong {
  color: #e9edf4;
  font-size: .82rem;
  font-weight: 750;
}

.camera-status-dot {
  flex: 0 0 8px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #d18348;
  box-shadow: 0 0 0 4px rgb(209 131 72 / 14%);
}

.camera-status-dot.is-live {
  background: #24c18c;
  box-shadow: 0 0 0 4px rgb(36 193 140 / 15%);
}

.close-viewer {
  flex: 0 0 auto;
  min-height: 38px;
  padding: 0 13px;
  border: 1px solid #384454;
  border-radius: 10px;
  color: #e9edf4;
  background: #151b24;
  font: inherit;
  font-size: .76rem;
  font-weight: 700;
  cursor: pointer;
}

.close-viewer:hover {
  border-color: #72b9f4;
  color: #91cbfb;
}

.close-viewer:focus-visible {
  outline: 3px solid rgb(114 185 244 / 36%);
  outline-offset: 2px;
}

.camera-stage {
  position: relative;
  display: grid;
  min-width: 0;
  min-height: 0;
  flex: 1 1 auto;
  place-items: center;
  overflow: hidden;
  border: 1px solid #293340;
  border-radius: 10px;
  background: #070a0f;
}

.camera-stage > img {
  display: block;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  object-fit: contain;
}

.camera-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 9px;
  padding: 24px;
  color: #e9edf4;
  background: rgb(7 10 15 / 94%);
  text-align: center;
}

.camera-overlay > strong {
  max-width: 34rem;
  font-size: .9rem;
}

.camera-spinner {
  width: 22px;
  height: 22px;
  border: 2px solid #455469;
  border-top-color: #72b9f4;
  border-radius: 50%;
  animation: spin .8s linear infinite;
}

.camera-spinner.is-hidden {
  display: none;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 700px) {
  .camera-viewer {
    gap: 9px;
    padding: 10px;
  }

  .camera-toolbar {
    flex-wrap: wrap;
    gap: 9px 12px;
    padding-block: 7px;
  }

  .camera-title {
    min-width: 0;
  }

  .camera-status {
    order: 3;
    width: fit-content;
    max-width: 100%;
    margin-left: 0;
  }

  .close-viewer {
    margin-left: auto;
  }
}
</style>
