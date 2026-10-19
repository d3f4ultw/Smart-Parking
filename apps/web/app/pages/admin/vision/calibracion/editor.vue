<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, computed, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { colorVisionZona, estiloVisionZona } from '~/utils/vision-zone-colors'
import {
  escucharCambioConfiguracionVision,
  esCambioConfiguracionRemoto,
  notificarCambioConfiguracionVision,
} from '~/utils/vision-config-sync'
import type {
  RespuestaConfiguracionVision,
  ZonaVisionBorrador,
} from '~/utils/vision-api'
import {
  agregarPuntoPoligono,
  desplazarPuntoNormalizado,
  motivoPoligonoInvalido,
  puntoDesdePuntero,
  validarPoligono,
  type PuntoNormalizado,
} from '~/utils/vision-calibracion'
import {
  estadoTrasConfirmarGuardado,
  puedeMantenerStreamCrudoVision,
  puedeNavegarDuranteGuardado,
  sincronizacionTrasGuardadoResuelta,
  type EstadoGuardadoCalibracion,
} from '~/utils/vision-calibration-recovery'

definePageMeta({ layout: 'vision-editor', middleware: 'sesion-owner' })

const CLAVE_INSTANCIA_EDITOR_VISION = 'smart-parking:vision-calibration-editor-instance'
const FORMATO_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

type EstadoBorrador = {
  zonas: ZonaVisionBorrador[]
  puntosPendientes: PuntoNormalizado[]
  dibujando: boolean
  seleccion: string | null
}

type ConfirmacionEditor = {
  titulo: string
  descripcion: string
  etiquetaConfirmar: string
  peligrosa?: boolean
}

const { mostrarToast } = useAdminToasts()
const vision = useVisionAuthorization()
const visionAutorizado = vision.autorizado
const route = useRoute()
const lease = useVisionCalibrationLease(perderAccesoLease)
const leaseVigente = lease.vigente
const estadoLease = lease.estado
const instanciaEditorLease = lease.editorInstanceId
const leaseComprobado = ref(false)
const leaseListo = computed(() => leaseVigente.value && leaseComprobado.value)
const zoneIdObjetivo = computed(() => typeof route.query.zoneId === 'string' ? route.query.zoneId : null)
const fetchVision = $fetch.create({
  credentials: 'same-origin',
  cache: 'no-store',
  timeout: 10_000,
})
const streamMjpeg = useVisionMjpegStream('/api/admin/vision/monitor/stream?tipo=raw', {
  alFallarAutorizacion: fallo => vision.manejarErrorProtegido(fallo),
})
const camaraConfigurada = ref(false)
const fuenteConectada = ref(false)
const frameFuenteFresco = ref(false)
const fuenteLista = computed(() => fuenteConectada.value && frameFuenteFresco.value)
const configCanonica = ref<RespuestaConfiguracionVision | null>(null)
const zonas = ref<ZonaVisionBorrador[]>([])
const puntosPendientes = ref<PuntoNormalizado[]>([])
const zonaSeleccionada = ref<string | null>(null)
const flujoVisible = computed(() =>
  streamMjpeg.estado.value !== 'detenido',
)
const dibujando = ref(false)
const hayCajonNuevo = computed(() => dibujando.value || zonas.value.some(zona => zona.numero === null))
const arrastre = ref<{ zonaId: string; indice: number; punteroId: number } | null>(null)
const historial = ref<EstadoBorrador[]>([])
const frameUrl = streamMjpeg.frameUrl
const anchoFrame = ref(0)
const altoFrame = ref(0)
const imagenDisponible = computed(() => streamMjpeg.estado.value === 'en-vivo')
const estadoFlujo = computed(() => {
  if (streamMjpeg.estado.value === 'en-vivo') return 'disponible' as const
  if (streamMjpeg.estado.value === 'reconectando') return 'reintentando' as const
  if (streamMjpeg.estado.value === 'desconectado') return 'desconectado' as const
  if (!camaraConfigurada.value) return 'sin-senal' as const
  return 'conectando' as const
})
const cargando = ref(false)
const estadoGuardado = ref<EstadoGuardadoCalibracion>('editando')
const guardando = computed(() =>
  estadoGuardado.value === 'guardando' || estadoGuardado.value === 'eliminando',
)
const textoOperacion = computed(() =>
  estadoGuardado.value === 'eliminando'
    ? 'Retirando cajón…'
    : hayCajonNuevo.value
      ? 'Guardando cajón…'
      : 'Guardando cambios…',
)
const error = ref('')
const mensajeEstadoLease = computed(() => {
  if (estadoLease.value === 'vigente') return 'Verificando que la calibración siga activa…'
  if (estadoLease.value === 'adquiriendo') return 'Comprobando el acceso exclusivo a la calibración…'
  if (estadoLease.value === 'ocupado') return 'Calibración en uso. Vuelve a intentarlo cuando el editor actual se cierre.'
  if (estadoLease.value === 'perdido') return error.value || 'El acceso exclusivo expiró. Cierra y vuelve a abrir el editor.'
  if (estadoLease.value === 'error') return error.value || 'No se pudo comprobar el acceso exclusivo.'
  return 'Se requiere autorización OWNER para abrir la calibración.'
})
const mensaje = ref('')
const conflicto = ref(false)
const revisionObjetivo = ref<number | null>(null)
const revisionAplicada = ref<number | null>(null)
const idempotencia = ref<{ digest: string; requestId: string } | null>(null)
const stage = ref<HTMLElement | null>(null)
const zoom = ref(1)
const trasladoX = ref(0)
const trasladoY = ref(0)
const transformacionVista = computed(() => ({
  escala: zoom.value,
  trasladoX: trasladoX.value,
  trasladoY: trasladoY.value,
}))
const transformacionCss = computed(() =>
  'translate(' + trasladoX.value * 100 + '%, ' + trasladoY.value * 100 + '%) scale(' + zoom.value + ')',
)
let indiceHistorialDibujo = 0
let temporizadorFuente: number | null = null
let solicitudEstadoFuenteEnCurso = false
let inicioEditorEnCurso: Promise<void> | null = null
let antesDeSalir: ((evento: BeforeUnloadEvent) => void) | null = null
let permitirCerrarEditor = false
let manejadorPaginaOculta: ((evento: PageTransitionEvent) => void) | null = null
let manejadorPaginaMostrada: ((evento: PageTransitionEvent) => void) | null = null
let liberacionBFCache: Promise<boolean> | null = null
let manejadorVisibilidad: (() => void) | null = null
let instanciaEditor = ''
let detenerEscuchaConfiguracion: (() => void) | null = null
let manejadorEnfoque: (() => void) | null = null
let arrastreCanvas: { punteroId: number; inicioX: number; inicioY: number; trasladoX: number; trasladoY: number } | null = null
const nivelZoom = computed(() => Math.round(zoom.value * 100) + '%')
const confirmacionActiva = ref<ConfirmacionEditor | null>(null)
const referenciaDialogoConfirmacion = ref<HTMLElement | null>(null)
const botonCancelarConfirmacion = ref<HTMLButtonElement | null>(null)
let resolverConfirmacionActiva: ((aceptada: boolean) => void) | null = null
let focoAnteriorConfirmacion: HTMLElement | null = null

const aspectRatio = computed(() => anchoFrame.value > 0 && altoFrame.value > 0
  ? `${anchoFrame.value} / ${altoFrame.value}`
  : '16 / 9')
const zonaSeleccionadaActual = computed(() =>
  zonas.value.find((zona) => zona.vision_zone_id === zonaSeleccionada.value) ?? null,
)
const modoEdicion = computed(() => {
  if (zonaSeleccionadaActual.value?.numero === null) return 'Nuevo cajón en borrador'
  if (zonaSeleccionadaActual.value?.numero) return 'Editando C' + zonaSeleccionadaActual.value.numero
  return 'Selecciona un cajón'
})
const hayCambios = computed(() => configCanonica.value !== null && (
  JSON.stringify(zonas.value) !== JSON.stringify(configCanonica.value.zones.map((zona) => ({
    vision_zone_id: zona.vision_zone_id,
    numero: zona.numero,
    polygon: zona.polygon,
  }))) || puntosPendientes.value.length > 0 || dibujando.value
))
const motivoDibujo = computed(() => dibujando.value ? motivoPoligonoInvalido(puntosPendientes.value) : null)
const mensajeGuiado = computed(() => {
  if (guardando.value) return textoOperacion.value
  if (estadoGuardado.value === 'aplicando' || estadoGuardado.value === 'recuperando') {
    return 'Actualizando el estacionamiento…'
  }
  if (estadoGuardado.value === 'listo' && mensaje.value === 'Cajón guardado correctamente.') {
    return mensaje.value
  }
  if (dibujando.value) {
    if (puntosPendientes.value.length === 0) return 'Marca los puntos que delimitan el cajón.'
    return motivoDibujo.value ?? 'El área está lista para guardar.'
  }
  if (arrastre.value !== null) return 'Suelta el punto para ajustar el cajón.'
  if (zonaSeleccionadaActual.value !== null) return 'Arrastra los puntos para ajustar el cajón. Usa las flechas del teclado para mover un punto seleccionado.'
  if (zonas.value.length === 0) return 'Selecciona “Nuevo cajón” para comenzar a dibujar.'
  return 'Selecciona un cajón para editar o elige “Nuevo cajón”.'
})
const etiquetaFlujo = computed(() => {
  if (estadoFlujo.value === 'sin-senal') return 'SIN SEÑAL'
  if (estadoFlujo.value === 'desconectado') return 'CÁMARA DESCONECTADA'
  if (estadoFlujo.value === 'reintentando') return 'RECONECTANDO'
  if (estadoFlujo.value === 'disponible') return 'CÁMARA EN VIVO'
  return 'CONECTANDO'
})
const mensajeEstadoFlujo = computed(() => {
  if (estadoFlujo.value === 'sin-senal') return 'La cámara no está enviando imagen. Reconectando…'
  if (estadoFlujo.value === 'desconectado') return 'No llega imagen de la cámara. Se volverá a intentar automáticamente.'
  if (estadoFlujo.value === 'reintentando') return 'Reconectando la cámara…'
  if (imagenDisponible.value) return ''
  return 'Conectando con la cámara…'
})
const imagenLista = computed(() =>
  imagenDisponible.value
  && estadoFlujo.value === 'disponible'
  && anchoFrame.value > 0
  && altoFrame.value > 0,
)

function confirmarEnEditor(opciones: ConfirmacionEditor): Promise<boolean> {
  if (resolverConfirmacionActiva !== null) return Promise.resolve(false)
  if (import.meta.client && document.activeElement instanceof HTMLElement) {
    focoAnteriorConfirmacion = document.activeElement
  }
  return new Promise((resolver) => {
    resolverConfirmacionActiva = resolver
    confirmacionActiva.value = opciones
    void nextTick(() => botonCancelarConfirmacion.value?.focus())
  })
}

function resolverDialogoConfirmacion(aceptada: boolean) {
  const resolver = resolverConfirmacionActiva
  if (resolver === null) return
  resolverConfirmacionActiva = null
  confirmacionActiva.value = null
  resolver(aceptada)
  void nextTick(() => {
    if (focoAnteriorConfirmacion?.isConnected) focoAnteriorConfirmacion.focus()
    focoAnteriorConfirmacion = null
  })
}

function mantenerFocoEnConfirmacion(evento: KeyboardEvent) {
  if (evento.key !== 'Tab' || referenciaDialogoConfirmacion.value === null) return
  const botones = referenciaDialogoConfirmacion.value.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')
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

function confirmarCalibracionAplicada() {
  const debeNotificar = estadoGuardado.value !== 'listo'
  estadoGuardado.value = 'listo'
  mensaje.value = 'Cajón guardado correctamente.'
  if (debeNotificar) mostrarToast(mensaje.value, 'success')
}

function numeroVisualZona(zona: ZonaVisionBorrador): number {
  if (zona.numero !== null) return zona.numero
  return (configCanonica.value?.next_c_number ?? 1) + zonas.value.filter(
    elemento => elemento.numero === null
      && zonas.value.indexOf(elemento) < zonas.value.findIndex(actual => actual.vision_zone_id === zona.vision_zone_id),
  ).length
}

function colorZona(zona: ZonaVisionBorrador): string {
  return colorVisionZona(numeroVisualZona(zona))
}

function estiloZona(zona: ZonaVisionBorrador): Record<string, string> {
  return estiloVisionZona(numeroVisualZona(zona))
}

function copiarEstado(): EstadoBorrador {
  return {
    zonas: zonas.value.map((zona) => ({
      ...zona,
      polygon: zona.polygon.map(([x, y]) => [x, y] as [number, number]),
    })),
    puntosPendientes: puntosPendientes.value.map(([x, y]) => [x, y]),
    dibujando: dibujando.value,
    seleccion: zonaSeleccionada.value,
  }
}

function registrarUndo() {
  historial.value.push(copiarEstado())
  if (historial.value.length > 40) historial.value.shift()
}

function aplicarEstado(estado: EstadoBorrador) {
  zonas.value = estado.zonas.map((zona) => ({
    ...zona,
    polygon: zona.polygon.map(([x, y]) => [x, y] as [number, number]),
  }))
  puntosPendientes.value = estado.puntosPendientes.map(([x, y]) => [x, y])
  dibujando.value = estado.dibujando
  zonaSeleccionada.value = estado.seleccion
}

function deshacer() {
  const anterior = historial.value.pop()
  if (anterior) aplicarEstado(anterior)
  error.value = ''
  mensaje.value = ''
}

function limpiarDatos() {
  if (resolverConfirmacionActiva !== null) resolverDialogoConfirmacion(false)
  if (temporizadorFuente !== null) window.clearInterval(temporizadorFuente)
  void streamMjpeg.detener()
  temporizadorFuente = null
  configCanonica.value = null
  zonas.value = []
  puntosPendientes.value = []
  zonaSeleccionada.value = null
  historial.value = []
  fuenteConectada.value = false
  frameFuenteFresco.value = false
  camaraConfigurada.value = false
  anchoFrame.value = 0
  altoFrame.value = 0
  error.value = ''
  mensaje.value = ''
  conflicto.value = false
  idempotencia.value = null
  arrastreCanvas = null
  restablecerZoom()
  revisionObjetivo.value = null
  revisionAplicada.value = null
  estadoGuardado.value = 'editando'
  leaseComprobado.value = false
}

async function cargarCanonico(solicitarImagen = true) {
  if (!vision.autorizado.value || !leaseListo.value) return
  cargando.value = true
  error.value = ''
  mensaje.value = ''
  try {
    const respuesta = await fetchVision<RespuestaConfiguracionVision>('/api/admin/vision/configuration')
    if (!leaseListo.value) return
    configCanonica.value = respuesta
    zonas.value = respuesta.zones.map((zona) => ({
      vision_zone_id: zona.vision_zone_id,
      numero: zona.numero,
      polygon: zona.polygon.map(([x, y]) => [x, y] as [number, number]),
    }))
    puntosPendientes.value = []
    const zonaObjetivo = zonas.value.find(zona => zona.vision_zone_id === zoneIdObjetivo.value)
    zonaSeleccionada.value = zoneIdObjetivo.value
      ? zonaObjetivo?.vision_zone_id ?? null
      : null
    if (zoneIdObjetivo.value && zonaObjetivo === undefined) {
      error.value = 'El cajón ya no está activo. Regresa a la lista y selecciona otro.'
    }
    historial.value = []
    conflicto.value = false
    idempotencia.value = null
    if (solicitarImagen && camaraConfigurada.value && leaseListo.value) streamMjpeg.iniciar()
  } catch (fallo: unknown) {
    error.value = 'No se pudo cargar la configuración protegida. Vuelve a intentarlo.'
    await vision.manejarErrorProtegido(fallo)
  } finally {
    cargando.value = false
  }
}

async function cargarEstadoFuente() {
  if (!vision.autorizado.value || !leaseListo.value || solicitudEstadoFuenteEnCurso) return
  solicitudEstadoFuenteEnCurso = true
  try {
    const estado = await fetchVision<{
      mode: 'simulation' | 'camera'
      source_connected: boolean
      frame_fresh: boolean
      source_sequence: number
      configuration_revision: number
      applied_revision: number | null
    }>('/api/admin/vision/monitor/status')
    const camaraVigente = puedeMantenerStreamCrudoVision(estado)
    camaraConfigurada.value = camaraVigente
    fuenteConectada.value = camaraVigente && estado.source_connected
    frameFuenteFresco.value = camaraVigente && estado.frame_fresh
    revisionAplicada.value = estado.applied_revision
    if (
      revisionObjetivo.value !== null
      && (estadoGuardado.value === 'aplicando' || estadoGuardado.value === 'recuperando')
    ) {
      const siguiente = estadoTrasConfirmarGuardado(
        revisionObjetivo.value,
        estado.applied_revision,
        fuenteConectada.value && frameFuenteFresco.value,
      )
      if (siguiente === 'listo') {
        confirmarCalibracionAplicada()
      } else if (siguiente === 'recuperando') {
        estadoGuardado.value = 'recuperando'
        mensaje.value = 'Configuración aplicada. Restableciendo video…'
      } else {
        estadoGuardado.value = 'aplicando'
        mensaje.value = 'Calibración guardada. Actualizando configuración…'
      }
    }
  } catch (fallo: unknown) {
    fuenteConectada.value = false
    frameFuenteFresco.value = false
    await vision.manejarErrorProtegido(fallo)
  } finally {
    solicitudEstadoFuenteEnCurso = false
  }
}

function registrarFrame(evento: Event) {
  const imagen = evento.currentTarget
  if (!(imagen instanceof HTMLImageElement)) return
  const url = imagen.currentSrc || imagen.src
  if (
    url !== frameUrl.value
    || imagen.naturalWidth <= 0
    || imagen.naturalHeight <= 0
    || !streamMjpeg.registrarFrameMostrado(url)
  ) return
  anchoFrame.value = imagen.naturalWidth
  altoFrame.value = imagen.naturalHeight
  if (
    revisionObjetivo.value !== null
    && sincronizacionTrasGuardadoResuelta(
      estadoGuardado.value,
      revisionObjetivo.value,
      revisionAplicada.value,
      camaraConfigurada.value,
      true,
    )
  ) {
    confirmarCalibracionAplicada()
  }
}

function manejarErrorImagen(evento: Event) {
  const imagen = evento.currentTarget
  if (
    !(imagen instanceof HTMLImageElement)
    || (imagen.currentSrc || imagen.src) !== frameUrl.value
    || !camaraConfigurada.value
  ) return
  streamMjpeg.notificarErrorRender(imagen.currentSrc || imagen.src)
}

async function actualizarConfiguracion() {
  if (hayCambios.value && !(await confirmarEnEditor({
    titulo: 'Actualizar configuración',
    descripcion: 'Se descartará el borrador local para cargar la configuración vigente.',
    etiquetaConfirmar: 'Descartar y actualizar',
    peligrosa: true,
  }))) return
  await cargarCanonico()
}
function limitarTraslado(valor: number, escala: number): number {
  const limite = Math.max(0, (escala - 1) / 2)
  return Math.min(limite, Math.max(-limite, valor))
}

function cambiarZoom(cambio: number) {
  const siguiente = Math.min(3, Math.max(1, Number((zoom.value + cambio).toFixed(2))))
  zoom.value = siguiente
  if (siguiente === 1) {
    trasladoX.value = 0
    trasladoY.value = 0
  } else {
    trasladoX.value = limitarTraslado(trasladoX.value, siguiente)
    trasladoY.value = limitarTraslado(trasladoY.value, siguiente)
  }
}

function restablecerZoom() {
  zoom.value = 1
  trasladoX.value = 0
  trasladoY.value = 0
}

function iniciarPan(evento: PointerEvent) {
  if (zoom.value <= 1 || dibujando.value || evento.button !== 0) return
  const destino = evento.target
  if (destino instanceof Element && ['circle', 'polygon'].includes(destino.tagName.toLowerCase())) return
  if (stage.value === null) return
  arrastreCanvas = {
    punteroId: evento.pointerId,
    inicioX: evento.clientX,
    inicioY: evento.clientY,
    trasladoX: trasladoX.value,
    trasladoY: trasladoY.value,
  }
  stage.value.setPointerCapture(evento.pointerId)
}

function moverCanvas(evento: PointerEvent) {
  if (arrastreCanvas === null || arrastreCanvas.punteroId !== evento.pointerId || stage.value === null) return
  const bounds = stage.value.getBoundingClientRect()
  if (bounds.width <= 0 || bounds.height <= 0) return
  trasladoX.value = limitarTraslado(
    arrastreCanvas.trasladoX + (evento.clientX - arrastreCanvas.inicioX) / bounds.width,
    zoom.value,
  )
  trasladoY.value = limitarTraslado(
    arrastreCanvas.trasladoY + (evento.clientY - arrastreCanvas.inicioY) / bounds.height,
    zoom.value,
  )
}

function terminarPan(evento: PointerEvent) {
  if (arrastreCanvas?.punteroId === evento.pointerId) arrastreCanvas = null
}

function iniciarDibujo() {
  if (!leaseListo.value || guardando.value || !imagenLista.value) return
  indiceHistorialDibujo = historial.value.length
  registrarUndo()
  puntosPendientes.value = []
  dibujando.value = true
  zonaSeleccionada.value = null
  estadoGuardado.value = 'editando'
  error.value = ''
  mensaje.value = 'Marca los puntos que delimitan el cajón.'
}

function cancelarDibujo() {
  if (!dibujando.value) return
  historial.value = historial.value.slice(0, indiceHistorialDibujo)
  puntosPendientes.value = []
  dibujando.value = false
  zonaSeleccionada.value = zonas.value[0]?.vision_zone_id ?? null
  error.value = ''
  mensaje.value = 'Se canceló el dibujo. Los demás cambios siguen en el borrador.'
}

function obtenerPunto(evento: PointerEvent | MouseEvent): PuntoNormalizado | null {
  if (stage.value === null || anchoFrame.value <= 0 || altoFrame.value <= 0) return null
  return puntoDesdePuntero(
    evento.clientX,
    evento.clientY,
    stage.value.getBoundingClientRect(),
    anchoFrame.value,
    altoFrame.value,
    transformacionVista.value,
  )
}

function agregarVertice(evento: MouseEvent) {
  if (!leaseListo.value || !dibujando.value) return
  const punto = obtenerPunto(evento)
  if (punto === null) return
  const siguientes = agregarPuntoPoligono(puntosPendientes.value, punto)
  if (siguientes === null) {
    error.value = 'El cajón admite hasta 128 puntos. Deshaz un punto para continuar.'
    return
  }
  registrarUndo()
  puntosPendientes.value = siguientes
  error.value = ''
}

function incorporarDibujo(): boolean {
  if (!leaseListo.value) return false
  const motivo = motivoPoligonoInvalido(puntosPendientes.value)
  if (motivo !== null) {
    error.value = motivo
    return false
  }
  registrarUndo()
  const id = crypto.randomUUID()
  zonas.value = [...zonas.value, {
    vision_zone_id: id,
    numero: null,
    polygon: puntosPendientes.value.map(([x, y]) => [x, y]),
  }]
  zonaSeleccionada.value = id
  puntosPendientes.value = []
  dibujando.value = false
  mensaje.value = 'El área está lista para guardar.'
  error.value = ''
  return true
}

function terminarDibujo() {
  incorporarDibujo()
}

function seleccionarZona(id: string) {
  if (!dibujando.value) zonaSeleccionada.value = id
}

function iniciarArrastre(evento: PointerEvent) {
  if (!leaseListo.value || guardando.value || !imagenLista.value) return
  const destino = evento.target
  if (!(destino instanceof SVGEllipseElement) || !destino.classList.contains('vertex-hit-target') || dibujando.value) return
  const zonaId = destino.dataset.zoneId
  const indice = Number(destino.dataset.vertexIndex)
  if (zonaId === undefined || !Number.isInteger(indice)) return
  registrarUndo()
  zonaSeleccionada.value = zonaId
  arrastre.value = { zonaId, indice, punteroId: evento.pointerId }
  const svg = destino.ownerSVGElement
  if (svg?.setPointerCapture) svg.setPointerCapture(evento.pointerId)
  evento.preventDefault()
}

function moverVertice(evento: PointerEvent) {
  if (!leaseListo.value || guardando.value || !imagenLista.value) return
  const activo = arrastre.value
  if (activo === null || activo.punteroId !== evento.pointerId) return
  const punto = obtenerPunto(evento)
  if (punto === null) return
  zonas.value = zonas.value.map((zona) => {
    if (zona.vision_zone_id !== activo.zonaId) return zona
    const polygon = zona.polygon.map(([x, y], indice) => indice === activo.indice ? [punto[0], punto[1]] as [number, number] : [x, y] as [number, number])
    return { ...zona, polygon }
  })
}

function moverVerticeConTeclado(evento: KeyboardEvent, zonaId: string, indice: number) {
  if (!leaseListo.value || guardando.value || !imagenLista.value) return
  if (evento.key === 'Enter' || evento.key === ' ') {
    evento.preventDefault()
    seleccionarZona(zonaId)
    return
  }
  const paso = (evento.shiftKey ? 10 : 1)
  let deltaX = 0
  let deltaY = 0
  if (evento.key === 'ArrowLeft') deltaX = -paso / anchoFrame.value
  else if (evento.key === 'ArrowRight') deltaX = paso / anchoFrame.value
  else if (evento.key === 'ArrowUp') deltaY = -paso / altoFrame.value
  else if (evento.key === 'ArrowDown') deltaY = paso / altoFrame.value
  else return

  const zona = zonas.value.find(elemento => elemento.vision_zone_id === zonaId)
  const punto = zona?.polygon[indice]
  if (zona === undefined || punto === undefined) return
  const siguiente = desplazarPuntoNormalizado(punto, deltaX, deltaY)
  if (siguiente[0] === punto[0] && siguiente[1] === punto[1]) return
  evento.preventDefault()
  registrarUndo()
  zonaSeleccionada.value = zonaId
  zonas.value = zonas.value.map(elemento => {
    if (elemento.vision_zone_id !== zonaId) return elemento
    const polygon = elemento.polygon.map(([x, y], puntoIndice) =>
      puntoIndice === indice ? [siguiente[0], siguiente[1]] as [number, number] : [x, y] as [number, number],
    )
    return { ...elemento, polygon }
  })
}

function terminarArrastre() {
  arrastre.value = null
}

async function borrarZona(zona: ZonaVisionBorrador) {
  if (!leaseListo.value || guardando.value) return
  const etiqueta = zona.numero === null ? 'este cajón nuevo' : `el cajón C${zona.numero}`
  if (!(await confirmarEnEditor({
    titulo: 'Quitar cajón del borrador',
    descripcion: `Se quitará ${etiqueta} del estacionamiento al guardar. Su historial se conservará.`,
    etiquetaConfirmar: 'Quitar cajón',
    peligrosa: true,
  }))) return
  registrarUndo()
  zonas.value = zonas.value.filter((elemento) => elemento.vision_zone_id !== zona.vision_zone_id)
  zonaSeleccionada.value = zonas.value[0]?.vision_zone_id ?? null
  mensaje.value = 'El cajón se quitará del estacionamiento cuando guardes.'
  mostrarToast(mensaje.value, 'warning')
}

async function cancelarCambios() {
  if (guardando.value) return
  if (configCanonica.value === null) return
  if (hayCambios.value && !(await confirmarEnEditor({
    titulo: 'Descartar cambios',
    descripcion: 'Se restaurará la configuración vigente y se perderán los cambios sin guardar.',
    etiquetaConfirmar: 'Descartar cambios',
    peligrosa: true,
  }))) return
  zonas.value = configCanonica.value.zones.map((zona) => ({
    vision_zone_id: zona.vision_zone_id,
    numero: zona.numero,
    polygon: zona.polygon.map(([x, y]) => [x, y] as [number, number]),
  }))
  puntosPendientes.value = []
  dibujando.value = false
  historial.value = []
  zonaSeleccionada.value = zoneIdObjetivo.value
    ? zonas.value.find(zona => zona.vision_zone_id === zoneIdObjetivo.value)?.vision_zone_id ?? zonas.value[0]?.vision_zone_id ?? null
    : zonas.value[0]?.vision_zone_id ?? null
  idempotencia.value = null
  error.value = ''
  mensaje.value = 'Se descartaron los cambios locales.'
  mostrarToast(mensaje.value, 'success')
}

function estadoHttp(errorHttp: unknown) {
  if (errorHttp === null || typeof errorHttp !== 'object') return null
  const valor = errorHttp as { status?: unknown; statusCode?: unknown }
  return typeof valor.statusCode === 'number' ? valor.statusCode : typeof valor.status === 'number' ? valor.status : null
}

async function guardarCambios() {
  if (!leaseListo.value || configCanonica.value === null || guardando.value || cargando.value) return
  if (dibujando.value && !incorporarDibujo()) return
  if (!hayCambios.value) return
  const zonaInvalida = zonas.value.find(zona => !validarPoligono(zona.polygon))
  if (zonaInvalida !== undefined) {
    const motivo = motivoPoligonoInvalido(zonaInvalida.polygon)
    const etiqueta = zonaInvalida.numero === null ? 'El cajón nuevo' : `El cajón C${zonaInvalida.numero}`
    error.value = `${etiqueta}: ${motivo ?? 'ajusta sus puntos antes de guardar.'}`
    return
  }
  const hayEliminaciones = configCanonica.value.zones.some(
    zona => !zonas.value.some(borrador => borrador.vision_zone_id === zona.vision_zone_id),
  )
  estadoGuardado.value = hayEliminaciones ? 'eliminando' : 'guardando'
  error.value = ''
  mensaje.value = ''
  conflicto.value = false
  try {
    await nextTick()
    const revision = configCanonica.value.revision
    const zonasSolicitud = zonas.value.map((zona) => ({
      vision_zone_id: zona.vision_zone_id,
      numero: zona.numero,
      polygon: zona.polygon.map(([x, y]) => [Number(x.toFixed(8)), Number(y.toFixed(8))]),
    }))
    const digest = JSON.stringify({ expected_revision: revision, zones: zonasSolicitud })
    if (idempotencia.value?.digest !== digest) {
      idempotencia.value = { digest, requestId: crypto.randomUUID() }
    }
    const respuesta = await fetchVision<RespuestaConfiguracionVision>(
      '/api/admin/vision/configuration',
      {
        method: 'PUT',
        headers: {
          'X-Vision-Editor-Instance': instanciaEditorLease.value ?? '',
        },
        body: {
          request_id: idempotencia.value.requestId,
          expected_revision: revision,
          zones: zonasSolicitud,
        },
      },
    )
    const seleccionAnterior = zonaSeleccionada.value
    configCanonica.value = respuesta
    zonas.value = respuesta.zones.map((zona) => ({
      vision_zone_id: zona.vision_zone_id,
      numero: zona.numero,
      polygon: zona.polygon.map(([x, y]) => [x, y] as [number, number]),
    }))
    zonaSeleccionada.value = zonas.value.some(zona => zona.vision_zone_id === seleccionAnterior)
      ? seleccionAnterior
      : zonas.value.find(zona => zona.numero === respuesta.next_c_number - 1)?.vision_zone_id
        ?? zonas.value[0]?.vision_zone_id ?? null
    historial.value = []
    puntosPendientes.value = []
    idempotencia.value = null
    revisionObjetivo.value = respuesta.revision
    estadoGuardado.value = estadoTrasConfirmarGuardado(
      respuesta.revision,
      revisionAplicada.value,
      fuenteLista.value,
    )
    mensaje.value = estadoGuardado.value === 'aplicando'
      ? 'Actualizando el estacionamiento…'
      : estadoGuardado.value === 'recuperando'
        ? 'Actualizando el estacionamiento…'
        : 'Cajón guardado correctamente.'
    mostrarToast(
      estadoGuardado.value === 'listo'
        ? mensaje.value
        : 'Actualizando el estacionamiento…',
      estadoGuardado.value === 'listo' ? 'success' : 'warning',
    )
    notificarCambioConfiguracionVision(instanciaEditor)
    void cargarEstadoFuente()
  } catch (fallo: unknown) {
    estadoGuardado.value = 'error'
    const codigo = estadoHttp(fallo)
    if (codigo === 409) {
      if (await lease.renovar()) {
        conflicto.value = true
        error.value = 'La configuración cambió en otra pestaña. Tu borrador sigue aquí; recarga la configuración cuando estés lista.'
      }
    } else if (codigo === 422) {
      error.value = 'No se pudo guardar el cajón. Revisa que los puntos estén dentro de la imagen y que los lados no se crucen.'
    } else {
      error.value = 'No se confirmó el guardado. Puedes reintentar el mismo cambio sin duplicar cajones.'
    }
    mostrarToast(error.value, 'error')
    await vision.manejarErrorProtegido(fallo)
  } finally {
    if (guardando.value) estadoGuardado.value = 'editando'
  }
}

async function revisarConfiguracionRemota() {
  if (!vision.autorizado.value || !leaseListo.value || configCanonica.value === null) return
  try {
    const remota = await fetchVision<RespuestaConfiguracionVision>('/api/admin/vision/configuration')
    if (remota.revision === configCanonica.value.revision) return
    if (hayCambios.value) {
      conflicto.value = true
      error.value = 'Otra pestaña guardó cambios. Tu borrador se conservó; recarga cuando estés lista.'
      return
    }
    await cargarCanonico(false)
  } catch (fallo: unknown) {
    await vision.manejarErrorProtegido(fallo)
  }
}

function perderAccesoLease(fallo: unknown) {
  const codigo = estadoHttp(fallo)
  limpiarDatos()
  error.value = codigo === 409
    ? 'Se perdió el acceso exclusivo. Cierra este editor y vuelve a abrir la calibración.'
    : 'Se perdió la autorización de calibración. Vuelve a verificar tu sesión OWNER.'
  mostrarToast(error.value, 'error')
  if (codigo === 401 || codigo === 403) void vision.manejarErrorProtegido(fallo)
}

function crearInstanciaDeNavegacion(): string {
  let instancia: string | null = null
  try {
    const navegacion = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
    if (navegacion?.type === 'reload') {
      const guardada = window.sessionStorage.getItem(CLAVE_INSTANCIA_EDITOR_VISION)
      if (guardada !== null && FORMATO_UUID.test(guardada)) instancia = guardada
    }
  } catch {
    // La continuidad tras una recarga es opcional; el servidor sigue siendo la autoridad.
  }
  instancia ??= crypto.randomUUID()
  try {
    window.sessionStorage.setItem(CLAVE_INSTANCIA_EDITOR_VISION, instancia)
  } catch {
    // Sin almacenamiento de pestaña, una recarga nueva espera a que expire el lease anterior.
  }
  return instancia
}

function reintentarAccesoLease() {
  if (!vision.autorizado.value) return
  const instancia = crypto.randomUUID()
  try {
    window.sessionStorage.setItem(CLAVE_INSTANCIA_EDITOR_VISION, instancia)
  } catch {
    // La identidad del lease permanece en memoria y en PostgreSQL.
  }
  void iniciarEditorConLease(instancia)
}

function volverAListaCajones() {
  void navigateTo('/admin/vision/zonas')
}

async function iniciarEditorConLease(instanciaSolicitada?: string): Promise<void> {
  if (!import.meta.client || !vision.autorizado.value) return
  if (inicioEditorEnCurso !== null) return inicioEditorEnCurso

  inicioEditorEnCurso = (async () => {
    const instancia = instanciaSolicitada ?? crearInstanciaDeNavegacion()
    instanciaEditor = instancia
    const adquirido = await lease.adquirir({ editorInstanceId: instancia })
    if (!adquirido) {
      if (estadoLease.value === 'ocupado') {
        error.value = 'Calibración en uso. Regresa a Cajones del estacionamiento y vuelve a intentarlo cuando esté disponible.'
      } else if (estadoLease.value === 'perdido') {
        error.value = 'Esta instancia perdió el lease. Cierra y vuelve a abrir el editor.'
      } else if (estadoLease.value === 'error') {
        error.value = 'No se pudo comprobar el acceso exclusivo. Vuelve a intentarlo.'
      }
      return
    }
    if (!vision.autorizado.value || !leaseVigente.value) return

    leaseComprobado.value = true
    error.value = ''
    await Promise.allSettled([cargarCanonico(), cargarEstadoFuente()])
    if (leaseVigente.value && temporizadorFuente === null) {
      temporizadorFuente = window.setInterval(() => void cargarEstadoFuente(), 500)
    }
  })().finally(() => {
    inicioEditorEnCurso = null
  })
  return inicioEditorEnCurso
}

async function cerrarEditor() {
  if (guardando.value) return
  if (hayCambios.value && !(await confirmarEnEditor({
    titulo: 'Cerrar editor',
    descripcion: 'Se descartarán los cambios sin guardar antes de cerrar el editor.',
    etiquetaConfirmar: 'Cerrar y descartar',
    peligrosa: true,
  }))) return
  const liberado = await lease.liberar()
  if (!liberado) lease.liberarAlSalir()
  await streamMjpeg.detener()
  permitirCerrarEditor = true
  window.close()
  if (!window.closed) window.location.assign('/admin/vision/zonas')
}

onBeforeRouteLeave(async () => {
  if (!puedeNavegarDuranteGuardado(estadoGuardado.value)) return false
  if (vision.autorizado.value && hayCambios.value && !permitirCerrarEditor && import.meta.client) {
    const confirmado = await confirmarEnEditor({
      titulo: 'Salir del editor',
      descripcion: 'Hay cambios sin guardar. Se descartarán si sales del editor.',
      etiquetaConfirmar: 'Salir y descartar',
      peligrosa: true,
    })
    if (!confirmado) return false
  }
  if (leaseVigente.value) {
    const liberado = await lease.liberar()
    if (!liberado) lease.liberarAlSalir()
  }
  return true
})

watch(vision.autorizado, (autorizado) => {
  if (!autorizado) {
    void lease.liberar()
    limpiarDatos()
    return
  }
  void iniciarEditorConLease()
}, { immediate: true })

watch([() => vision.autorizado.value, camaraConfigurada, leaseListo], ([autorizado, camaraVigente, leaseActivo]) => {
  if (autorizado && camaraVigente && leaseActivo) {
    streamMjpeg.iniciar()
  } else {
    void streamMjpeg.detener()
  }
}, { immediate: true })

onMounted(() => {
  antesDeSalir = (evento: BeforeUnloadEvent) => {
    if (permitirCerrarEditor || (!hayCambios.value && puedeNavegarDuranteGuardado(estadoGuardado.value))) return
    evento.preventDefault()
    evento.returnValue = ''
  }
  window.addEventListener('beforeunload', antesDeSalir)
  manejadorPaginaOculta = (evento) => {
    liberacionBFCache = lease.liberarAlSalir()
    if (evento.persisted) {
      leaseComprobado.value = false
    }
  }
  window.addEventListener('pagehide', manejadorPaginaOculta)
  manejadorPaginaMostrada = (evento) => {
    if (!evento.persisted || !vision.autorizado.value) return
    void (async () => {
      if (liberacionBFCache !== null) await liberacionBFCache
      liberacionBFCache = null
      limpiarDatos()
      const instancia = instanciaEditorLease.value ?? crypto.randomUUID()
      try {
        window.sessionStorage.setItem(CLAVE_INSTANCIA_EDITOR_VISION, instancia)
      } catch {
        // El editor podrá reabrirse con una identidad nueva sin almacenamiento de pestaña.
      }
      await iniciarEditorConLease(instancia)
    })()
  }
  window.addEventListener('pageshow', manejadorPaginaMostrada)
  manejadorVisibilidad = () => {
    if (document.visibilityState === 'hidden') {
      leaseComprobado.value = false
      return
    }
    if (document.visibilityState !== 'visible' || !leaseVigente.value) return
    void (async () => {
      if (await lease.renovar()) {
        leaseComprobado.value = true
        await revisarConfiguracionRemota()
      }
    })()
  }
  document.addEventListener('visibilitychange', manejadorVisibilidad)
  detenerEscuchaConfiguracion = escucharCambioConfiguracionVision((origenMensaje) => {
    if (esCambioConfiguracionRemoto(instanciaEditor, origenMensaje)) {
      void revisarConfiguracionRemota()
    }
  })
  manejadorEnfoque = () => { void revisarConfiguracionRemota() }
  window.addEventListener('focus', manejadorEnfoque)
  if (vision.autorizado.value) void iniciarEditorConLease()
})

onBeforeUnmount(() => {
  if (resolverConfirmacionActiva !== null) resolverDialogoConfirmacion(false)
  if (antesDeSalir !== null) window.removeEventListener('beforeunload', antesDeSalir)
  if (manejadorVisibilidad !== null) document.removeEventListener('visibilitychange', manejadorVisibilidad)
  if (manejadorPaginaOculta !== null) window.removeEventListener('pagehide', manejadorPaginaOculta)
  if (manejadorPaginaMostrada !== null) window.removeEventListener('pageshow', manejadorPaginaMostrada)
  if (manejadorEnfoque !== null) window.removeEventListener('focus', manejadorEnfoque)
  detenerEscuchaConfiguracion?.()
  if (leaseVigente.value) void lease.liberar()
  limpiarDatos()
})
</script>

<template>
  <AdminVisionAuthorizationGate
    pantalla-completa
    titulo="Cajones del estacionamiento"
    descripcion="Ingresa la contraseña administrativa para editar los cajones."
  >
    <AdminToastNotifications />
    <main
      v-if="leaseVigente"
      class="editor-page"
      :data-vision-stream-state="streamMjpeg.estado.value"
      :data-vision-stream-received="streamMjpeg.framesRecibidos.value"
      :data-vision-stream-rendered="streamMjpeg.framesMostrados.value"
      :data-vision-stream-receive-fps="streamMjpeg.fpsRecepcion.value"
      :data-vision-stream-render-fps="streamMjpeg.fpsRenderizado.value"
      :data-vision-stream-last-received-at="streamMjpeg.ultimoFrameRecibido.value"
      :data-vision-stream-last-rendered-at="streamMjpeg.ultimoFrameMostrado.value"
    >
      <header class="editor-toolbar">
        <div class="editor-title">
          <span class="vision-mark" aria-hidden="true">V</span>
          <div>
            <p>CAJONES DEL ESTACIONAMIENTO</p>
            <h1>{{ modoEdicion }}</h1>
          </div>
        </div>
        <div class="toolbar-controls">
          <div class="editing-controls" role="group" aria-label="Acciones del cajón">
            <button
              v-if="!dibujando"
              class="tool-button tool-primary"
              type="button"
              title="Empieza a marcar un cajón nuevo sobre la imagen."
              :disabled="cargando || !imagenLista || guardando"
              @click="iniciarDibujo"
            >＋ Nuevo cajón</button>
            <button
              v-else
              class="tool-button"
              type="button"
              title="Quita el último punto marcado."
              :disabled="historial.length <= indiceHistorialDibujo + 1 || guardando"
              @click="deshacer"
            >Deshacer punto</button>
            <button
              v-if="dibujando"
              class="tool-button"
              type="button"
              title="Termina el área para revisarla antes de guardar."
              :aria-describedby="motivoDibujo ? 'editor-guidance' : undefined"
              :disabled="motivoDibujo !== null || guardando || cargando"
              @click="terminarDibujo"
            >Terminar área</button>
            <button
              v-if="dibujando"
              class="tool-button"
              type="button"
              title="Descarta únicamente este dibujo sin terminar."
              :disabled="guardando"
              @click="cancelarDibujo"
            >Cancelar dibujo</button>
            <button
              v-if="!dibujando && historial.length > 0"
              class="tool-button"
              type="button"
              title="Deshace el último cambio del borrador."
              :disabled="guardando"
              @click="deshacer"
            >Deshacer cambio</button>
            <button
              v-if="!dibujando && hayCambios"
              class="tool-button"
              type="button"
              title="Restaura los cajones guardados y descarta este borrador."
              :disabled="guardando"
              @click="cancelarCambios"
            >Descartar cambios</button>
            <button
              class="tool-button tool-save"
              type="button"
              :title="hayCambios ? (motivoDibujo ?? 'Guarda los cambios del estacionamiento.') : 'No hay cambios por guardar.'"
              :aria-describedby="motivoDibujo ? 'editor-guidance' : undefined"
              :disabled="!hayCambios || guardando || cargando"
              @click="guardarCambios"
            >{{ guardando ? textoOperacion : hayCajonNuevo ? 'Guardar cajón' : 'Guardar cambios' }}</button>
            <button
              class="tool-close"
              type="button"
              title="Cierra el editor. Si hay cambios sin guardar, podrás decidir si descartarlos."
              :disabled="guardando"
              @click="cerrarEditor"
            >Cerrar editor</button>
          </div>
          <div class="view-controls" role="group" aria-label="Vista de la imagen">
            <button class="tool-button zoom-button" type="button" aria-label="Alejar imagen" title="Alejar imagen" :disabled="zoom <= 1 || guardando" @click="cambiarZoom(-0.25)">−</button>
            <span class="zoom-level" aria-live="polite">{{ nivelZoom }}</span>
            <button class="tool-button zoom-button" type="button" aria-label="Acercar imagen" title="Acercar imagen" :disabled="zoom >= 3 || guardando" @click="cambiarZoom(0.25)">＋</button>
            <button class="tool-button reset-zoom" type="button" title="Vuelve al tamaño original de la imagen." :disabled="zoom === 1 && trasladoX === 0 && trasladoY === 0" @click="restablecerZoom">Tamaño original</button>
          </div>
        </div>
      </header>

      <div class="editor-status" role="status" aria-live="polite">
        <span class="connection-indicator" :class="'state-' + estadoFlujo" />
        <strong>{{ etiquetaFlujo }}</strong>
        <span id="editor-guidance">{{ mensajeGuiado }}</span>
        <span v-if="error" class="status-error" role="alert">{{ error }}</span>
      </div>

      <div v-if="conflicto" class="conflict-notice" role="alert">
        <span>La configuración cambió en otra pestaña. Tu borrador sigue en este editor.</span>
        <button class="tool-button" type="button" @click="actualizarConfiguracion">Recargar configuración</button>
      </div>

      <section class="editor-workspace">
        <div class="canvas-area">
          <div
            ref="stage"
            class="canvas-stage"
            :style="{ aspectRatio }"
            :class="{ 'is-zoomed': zoom > 1, 'is-drawing': dibujando }"
            @click="agregarVertice"
            @pointerdown="iniciarPan"
            @pointermove="moverCanvas"
            @pointerup="terminarPan"
            @pointercancel="terminarPan"
          >
            <div class="visual-layer" :style="{ transform: transformacionCss }">
              <img
                v-if="frameUrl && flujoVisible"
                :src="frameUrl"
                alt="Imagen de la cámara para ajustar los cajones"
                @load="registrarFrame"
                @error="manejarErrorImagen"
              >
              <svg
                v-if="frameUrl && flujoVisible && imagenLista"
                class="calibration-overlay"
                viewBox="0 0 1 1"
                preserveAspectRatio="none"
                aria-label="Áreas de los cajones"
                @pointerdown="iniciarArrastre"
                @pointermove="moverVertice"
                @pointerup="terminarArrastre"
                @pointercancel="terminarArrastre"
              >
                <g
                  v-for="zona in zonas"
                  :key="zona.vision_zone_id"
                  :style="estiloZona(zona)"
                >
                  <polygon
                    :points="zona.polygon.map(([x, y]) => x + ',' + y).join(' ')"
                    :class="{
                      'is-selected': zona.vision_zone_id === zonaSeleccionada,
                      'is-new': zona.numero === null,
                    }"
                    @click.stop="seleccionarZona(zona.vision_zone_id)"
                  />
                  <text
                    v-if="zona.polygon.length > 0"
                    :x="zona.polygon[0]![0]"
                    :y="zona.polygon[0]![1]"
                    class="zone-label"
                    font-size="0.035"
                    @click.stop="seleccionarZona(zona.vision_zone_id)"
                  >{{ zona.numero === null ? 'C' + numeroVisualZona(zona) + ' · NUEVO' : 'C' + zona.numero }}</text>
                  <ellipse
                    v-for="(punto, indice) in zonaSeleccionada === zona.vision_zone_id ? zona.polygon : []"
                    :key="zona.vision_zone_id + '-' + indice"
                    :cx="punto[0]"
                    :cy="punto[1]"
                    rx="0.032"
                    ry="0.06"
                    :data-zone-id="zona.vision_zone_id"
                    :data-vertex-index="indice"
                    :aria-label="'Punto ' + (indice + 1) + ' del cajón C' + numeroVisualZona(zona) + '. Usa las flechas para moverlo.'"
                    role="button"
                    tabindex="0"
                    class="vertex-hit-target"
                    @keydown="moverVerticeConTeclado($event, zona.vision_zone_id, indice)"
                    @pointerdown.stop="iniciarArrastre"
                    @click.stop
                  />
                  <ellipse
                    v-for="(punto, indice) in zonaSeleccionada === zona.vision_zone_id ? zona.polygon : []"
                    :key="zona.vision_zone_id + '-' + indice + '-visible'"
                    :cx="punto[0]"
                    :cy="punto[1]"
                    rx="0.012"
                    ry="0.022"
                    aria-hidden="true"
                    class="vertex-handle"
                  />
                </g>
                <g v-if="puntosPendientes.length > 0" class="draft-polygon">
                  <polyline :points="puntosPendientes.map(([x, y]) => x + ',' + y).join(' ')" />
                  <circle v-for="(punto, indice) in puntosPendientes" :key="indice" :cx="punto[0]" :cy="punto[1]" r="0.01" />
                </g>
              </svg>
            </div>
            <div v-if="!imagenLista" class="stage-placeholder" :class="{ 'is-offline': estadoFlujo === 'sin-senal' || estadoFlujo === 'desconectado' }" role="status" aria-live="polite">
              <span>{{ mensajeEstadoFlujo }}</span>
              <button
                v-if="estadoFlujo === 'desconectado' && fuenteConectada"
                class="tool-button"
                type="button"
                @click.stop="streamMjpeg.reintentar()"
              >Reintentar conexión</button>
            </div>
            <div v-else-if="estadoFlujo === 'reintentando'" class="stage-status-overlay" role="status" aria-live="polite">
              La cámara se está reconectando…
            </div>
            <span v-if="zoom > 1" class="pan-hint">Arrastra el fondo para mover la imagen</span>
          </div>
          <div class="canvas-actions">
            <span v-if="dibujando">{{ puntosPendientes.length }} puntos marcados</span>
            <span v-else>{{ zonas.length }} cajones</span>
            <span class="canvas-help">{{ dibujando ? 'Puedes guardar el cajón cuando el área sea válida.' : 'Selecciona un cajón para ajustar sus puntos.' }}</span>
          </div>
        </div>

        <aside class="zones-panel" aria-label="Cajones del estacionamiento">
          <div class="panel-heading">
            <div><span>ESTACIONAMIENTO</span><h2>Cajones activos</h2></div>
            <strong>{{ zonas.length }}</strong>
          </div>
          <ul v-if="zonas.length" class="zone-list">
            <li v-for="zona in zonas" :key="zona.vision_zone_id" :class="{ 'is-selected': zonaSeleccionada === zona.vision_zone_id }">
              <button class="zone-select" type="button" :disabled="guardando" @click="seleccionarZona(zona.vision_zone_id)">
                <span class="zone-swatch" :style="{ backgroundColor: colorZona(zona) }" />
                <span class="zone-details">
                  <strong>{{ zona.numero === null ? 'C' + numeroVisualZona(zona) + ' · nuevo' : 'C' + zona.numero }}</strong>
                  <small>{{ zona.polygon.length }} puntos</small>
                </span>
              </button>
              <button
                class="zone-delete"
                type="button"
                :disabled="guardando"
                :aria-label="'Quitar cajón ' + (zona.numero === null ? 'nuevo' : 'C' + zona.numero) + ' del borrador'"
                @click="borrarZona(zona)"
              >×</button>
            </li>
          </ul>
          <p v-else class="empty-zones">Todavía no hay cajones. Selecciona “Nuevo cajón” para marcar el primero.</p>
          <div v-if="zonaSeleccionadaActual" class="selection-note">
            <span class="zone-swatch large" :style="{ backgroundColor: colorZona(zonaSeleccionadaActual) }" />
            <div>
              <strong>{{ zonaSeleccionadaActual.numero === null ? 'Cajón C' + numeroVisualZona(zonaSeleccionadaActual) + ' · nuevo' : 'Cajón C' + zonaSeleccionadaActual.numero }}</strong>
              <small>{{ motivoPoligonoInvalido(zonaSeleccionadaActual.polygon) ?? 'Área lista' }}</small>
            </div>
          </div>
          <div v-if="guardando" class="saving-note" role="status">
            <span class="save-spinner" aria-hidden="true" />
            <span>{{ textoOperacion }}</span>
          </div>
        </aside>
      </section>
    </main>
    <main v-else-if="visionAutorizado" class="editor-lease-waiting" role="status" aria-live="polite">
      <span class="vision-mark" aria-hidden="true">V</span>
      <h1>{{ estadoLease === 'ocupado' ? 'Calibración en uso' : 'Acceso al editor' }}</h1>
      <p>{{ mensajeEstadoLease }}</p>
      <div class="lease-waiting-actions">
        <button
          v-if="estadoLease === 'error' || estadoLease === 'perdido'"
          class="tool-button tool-primary"
          type="button"
          @click="reintentarAccesoLease"
        >Reintentar acceso</button>
        <button class="tool-button" type="button" @click="volverAListaCajones">Volver a cajones</button>
      </div>
    </main>
    <div
      v-if="confirmacionActiva"
      class="confirmation-backdrop"
      @click.self="resolverDialogoConfirmacion(false)"
      @keydown.esc.prevent.stop="resolverDialogoConfirmacion(false)"
      @keydown.tab="mantenerFocoEnConfirmacion"
    >
      <section
        id="editor-confirmation-dialog"
        ref="referenciaDialogoConfirmacion"
        class="confirmation-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="editor-confirmation-title"
        aria-describedby="editor-confirmation-description"
        tabindex="-1"
      >
        <span class="confirmation-icon" aria-hidden="true">!</span>
        <h2 id="editor-confirmation-title">{{ confirmacionActiva.titulo }}</h2>
        <p id="editor-confirmation-description">{{ confirmacionActiva.descripcion }}</p>
        <div class="confirmation-actions">
          <button
            ref="botonCancelarConfirmacion"
            class="tool-button"
            type="button"
            @click="resolverDialogoConfirmacion(false)"
          >Cancelar</button>
          <button
            class="tool-button"
            :class="{ 'confirmation-danger': confirmacionActiva.peligrosa }"
            type="button"
            @click="resolverDialogoConfirmacion(true)"
          >{{ confirmacionActiva.etiquetaConfirmar }}</button>
        </div>
      </section>
    </div>
  </AdminVisionAuthorizationGate>
</template>

<style scoped>
.editor-page { display: grid; grid-template-rows: auto auto minmax(0,1fr) auto; width: 100%; height: 100dvh; overflow: hidden; color: #e9edf4; background: #0d1118; font-family: Manrope, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
.editor-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 66px; padding: 8px 14px; border-bottom: 1px solid #252d39; background: #151b24; }
.editor-title { display: flex; align-items: center; gap: 10px; min-width: 170px; }
.vision-mark { display: grid; place-items: center; width: 34px; height: 34px; border: 1px solid #3a485a; border-radius: 10px; color: #90c8ff; background: #1c2b3b; font-weight: 850; }
.editor-title p,.panel-heading span { margin: 0 0 3px; color: #8c9aab; font-size: .62rem; font-weight: 800; letter-spacing: .13em; }
.editor-title h1 { margin: 0; color: #f2f5fa; font-size: .97rem; line-height: 1.2; }
.toolbar-controls { display: flex; align-items: center; justify-content: end; flex-wrap: wrap; gap: 6px; }
.tool-button,.tool-close { min-height: 34px; padding: 0 10px; border: 1px solid #384454; border-radius: 7px; color: #d8e0eb; background: #202833; font: inherit; font-size: .73rem; font-weight: 700; white-space: nowrap; cursor: pointer; }
.tool-button:hover:not(:disabled),.tool-close:hover:not(:disabled) { border-color: #83b9ed; color: #fff; background: #293849; }
.tool-button:disabled,.tool-close:disabled { opacity: .45; cursor: not-allowed; }
.tool-primary { border-color: #376b9f; color: #f4f8fc; background: #26517d; }
.tool-save { border-color: #1c8369; color: #fff; background: #15735c; }
.tool-close { border-color: #574753; color: #f2d5d6; background: #30252d; }
.tool-separator { width: 1px; height: 24px; margin: 0 3px; background: #384454; }
.zoom-button { width: 34px; padding: 0; font-size: 1rem; }
.zoom-level { min-width: 39px; color: #d9e2ed; font-size: .72rem; font-variant-numeric: tabular-nums; text-align: center; }
.editor-status { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; min-height: 35px; padding: 5px 16px; border-bottom: 1px solid #202834; color: #9dabbc; font-size: .69rem; }
.editor-status strong { color: #dce6f2; font-size: .67rem; letter-spacing: .05em; }
.connection-indicator { width: 8px; height: 8px; border-radius: 50%; background: #d59042; box-shadow: 0 0 0 3px #d5904222; }
.connection-indicator.state-disponible { background: #38c391; box-shadow: 0 0 0 3px #38c39122; }
.connection-indicator.state-desconectado,.connection-indicator.state-sin-senal { background: #df6666; box-shadow: 0 0 0 3px #df666622; }
.status-error { color: #ff9999; }
.conflict-notice { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 14px; color: #ffd889; background: #493718; font-size: .75rem; }
.editor-workspace { display: grid; grid-template-columns: minmax(0,1fr) 236px; gap: 12px; min-height: 0; padding: 12px; }
.canvas-area { display: flex; flex-direction: column; align-items: stretch; justify-content: center; min-width: 0; min-height: 0; }
.canvas-stage { position: relative; width: min(100%, calc((100dvh - 180px) * 16 / 9)); max-width: 100%; margin: auto; overflow: hidden; border: 1px solid #303b49; border-radius: 8px; background: #070a0f; box-shadow: 0 16px 50px #0007; touch-action: none; user-select: none; }
.canvas-stage.is-zoomed { cursor: grab; }
.canvas-stage.is-zoomed:active { cursor: grabbing; }
.canvas-stage.is-drawing { cursor: crosshair; }
.visual-layer { position: absolute; inset: 0; overflow: hidden; transform-origin: center; will-change: transform; }
.visual-layer > img { position: absolute; inset: 0; display: block; width: 100%; height: 100%; object-fit: contain; user-select: none; -webkit-user-drag: none; pointer-events: none; }
.calibration-overlay { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; touch-action: none; }
.calibration-overlay polygon { fill: var(--zone-fill, rgb(90 180 245 / 16%)); stroke: var(--zone-color, #70c6ff); stroke-width: .004; vector-effect: non-scaling-stroke; cursor: pointer; filter: drop-shadow(0 0 2px #000); pointer-events: all; }
.calibration-overlay polygon.is-selected { fill: var(--zone-fill, rgb(90 180 245 / 16%)); stroke-width: .007; filter: drop-shadow(0 0 4px #fff8); }
.calibration-overlay polygon.is-new { stroke-dasharray: .015 .01; }
.zone-label { fill: #fff; paint-order: stroke; stroke: #10151b; stroke-width: .006; font-weight: 900; cursor: pointer; pointer-events: all; }
.vertex-handle { fill: #fff; stroke: var(--zone-color, #70c6ff); stroke-width: .005; vector-effect: non-scaling-stroke; cursor: grab; pointer-events: all; filter: drop-shadow(0 0 2px #000); }
.draft-polygon polyline { fill: none; stroke: #ffd16a; stroke-width: .006; stroke-dasharray: .018 .012; vector-effect: non-scaling-stroke; }
.draft-polygon circle { fill: #fff2bd; stroke: #b27b10; stroke-width: .005; vector-effect: non-scaling-stroke; }
.stage-placeholder,.stage-status-overlay { position: absolute; z-index: 3; inset: 0; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 10px; padding: 22px; color: #e6edf7; background: #10151dd9; text-align: center; font-size: .86rem; }
.stage-placeholder.is-offline { background: #21191dde; }
.resolution-badge,.pan-hint { position: absolute; z-index: 4; right: 9px; padding: 4px 7px; border: 1px solid #d8e5f229; border-radius: 5px; color: #f0f5fa; background: #0b1018c7; font-size: .62rem; font-variant-numeric: tabular-nums; }
.resolution-badge { top: 9px; }
.pan-hint { right: auto; bottom: 9px; left: 9px; color: #d4e5f5; }
.canvas-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; min-height: 39px; padding: 6px 3px 0; color: #9caabd; font-size: .7rem; }
.canvas-help { margin-left: auto; }
.zones-panel { display: flex; flex-direction: column; min-width: 0; min-height: 0; padding: 11px; overflow-y: auto; border: 1px solid #293340; border-radius: 8px; background: #151b24; }
.panel-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 2px 3px 9px; border-bottom: 1px solid #293340; }
.panel-heading h2 { margin: 0; color: #e8edf5; font-size: .87rem; }
.panel-heading > strong { display: grid; place-items: center; min-width: 24px; height: 24px; border-radius: 6px; color: #c6d2e0; background: #252f3b; font-size: .7rem; }
.zone-list { display: grid; gap: 5px; padding: 8px 0; margin: 0; list-style: none; }
.zone-list li { display: flex; align-items: center; gap: 4px; min-height: 43px; border: 1px solid transparent; border-radius: 7px; }
.zone-list li.is-selected { border-color: #527596; background: #1d2a37; }
.zone-select { display: flex; align-items: center; gap: 9px; flex: 1; min-width: 0; height: 42px; padding: 4px 6px; border: 0; color: inherit; background: transparent; text-align: left; cursor: pointer; }
.zone-select:disabled { cursor: not-allowed; }
.zone-swatch { flex: 0 0 10px; width: 10px; height: 10px; border: 1px solid #ffffff99; border-radius: 50%; box-shadow: 0 0 0 2px #0007; }
.zone-swatch.large { width: 13px; height: 13px; }
.zone-details,.selection-note > div { display: grid; gap: 3px; min-width: 0; }
.zone-details strong,.selection-note strong { color: #e5edf7; font-size: .74rem; }
.zone-details small,.selection-note small { color: #94a3b4; font-size: .64rem; }
.zone-delete { width: 27px; height: 27px; border: 0; border-radius: 5px; color: #e58c8c; background: transparent; font-size: 1.1rem; cursor: pointer; }
.zone-delete:hover:not(:disabled) { background: #482a31; }
.zone-delete:disabled { opacity: .45; cursor: not-allowed; }
.empty-zones { margin: 14px 2px; color: #9aa9ba; font-size: .75rem; line-height: 1.5; }
.selection-note { display: flex; align-items: center; gap: 9px; margin-top: auto; padding: 10px 7px; border-top: 1px solid #293340; }
.saving-note { display: flex; align-items: center; gap: 8px; padding: 8px; color: #b5e5d7; font-size: .69rem; }
.save-spinner { width: 15px; height: 15px; border: 2px solid #55786f; border-top-color: #64d2af; border-radius: 50%; animation: spin .8s linear infinite; }
.confirmation-backdrop { position: fixed; z-index: 180; inset: 0; display: grid; place-items: center; padding: 20px; background: #05080dcc; }
.confirmation-dialog { width: min(440px, 100%); padding: 21px; border: 1px solid #465466; border-radius: 12px; color: #e9edf4; background: #151b24; box-shadow: 0 22px 70px #0009; }
.confirmation-dialog:focus { outline: 2px solid #72b9f4; outline-offset: 3px; }
.confirmation-icon { display: grid; place-items: center; width: 29px; height: 29px; border: 1px solid #8d6b36; border-radius: 50%; color: #ffd889; background: #493718; font-weight: 900; }
.confirmation-dialog h2 { margin: 14px 0 7px; color: #f2f5fa; font-size: 1rem; }
.confirmation-dialog p { margin: 0; color: #b7c1ce; font-size: .82rem; line-height: 1.55; }
.confirmation-actions { display: flex; justify-content: end; flex-wrap: wrap; gap: 8px; margin-top: 20px; }
.confirmation-danger { border-color: #8b4d55; color: #fff; background: #71343d; }
.confirmation-danger:hover:not(:disabled) { border-color: #bf6b76; background: #86404b; }
.editor-toolbar { align-items: center; gap: 10px; }
.editor-lease-waiting { display: grid; align-content: center; justify-items: center; gap: 12px; min-height: 100dvh; padding: 24px; color: #e9edf4; background: #0b0e13; text-align: center; }
.editor-lease-waiting h1 { margin: 0; font-size: 1.4rem; }
.editor-lease-waiting p { max-width: 440px; margin: 0; color: #b7c1ce; line-height: 1.55; }
.lease-waiting-actions { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; }
.toolbar-controls { flex: 1; min-width: 0; gap: 8px; }
.editing-controls,.view-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.view-controls { flex: 0 0 auto; padding-left: 8px; border-left: 1px solid #384454; }
.tool-button,.tool-close { min-height: 44px; padding: 0 12px; border-radius: 10px; font-size: .75rem; }
.tool-save { border-width: 2px; }
.tool-button:disabled,.tool-close:disabled { border-style: dashed; color: #aab5c2; background: #171d25; opacity: .82; }
.tool-button:focus-visible,.tool-close:focus-visible,.zone-select:focus-visible,.zone-delete:focus-visible { outline: 3px solid #a4d4ff; outline-offset: 2px; }
.zoom-button { width: 44px; min-width: 44px; padding: 0; }
.vertex-hit-target { fill: transparent; stroke: transparent; pointer-events: all; cursor: grab; outline: none; }
.vertex-hit-target:focus-visible + .vertex-handle { stroke: #fff; stroke-width: 3px; filter: drop-shadow(0 0 5px #fff); }
.vertex-handle { pointer-events: none; }
.editor-guidance { min-width: 0; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 980px) { .editor-toolbar { align-items: start; flex-direction: column; } .toolbar-controls { justify-content: start; width: 100%; } .editor-workspace { grid-template-columns: minmax(0,1fr) 205px; } .canvas-stage { width: min(100%, calc((100dvh - 220px) * 16 / 9)); } }
@media (max-width: 700px) { .editor-page { height: 100svh; grid-template-rows: auto auto minmax(0,1fr); } .editor-toolbar { min-height: 0; padding: 8px; } .editor-title { min-height: 34px; } .toolbar-controls { align-items: stretch; flex-direction: column; gap: 5px; } .editing-controls { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); width: 100%; gap: 5px; } .view-controls { justify-content: flex-end; padding: 5px 0 0; border-top: 1px solid #384454; border-left: 0; } .tool-button,.tool-close { min-height: 44px; padding: 4px 6px; font-size: .68rem; white-space: normal; line-height: 1.1; } .zoom-button { width: 44px; min-width: 44px; } .editor-status { align-items: flex-start; padding: 6px 9px; font-size: .68rem; } .editor-status strong { flex: 0 0 auto; } .editor-status > span:nth-child(3) { flex: 1 1 100%; } .editor-workspace { grid-template-columns: minmax(0,1fr); grid-template-rows: minmax(0,1fr) auto; gap: 7px; padding: 7px; } .canvas-stage { width: min(100%, calc((100svh - 390px) * 16 / 9)); } .zones-panel { max-height: 132px; } .zone-list { grid-template-columns: repeat(auto-fit,minmax(120px,1fr)); } .selection-note { display: none; } .canvas-actions { min-height: 32px; font-size: .66rem; } .canvas-help { display: none; } }
</style>
