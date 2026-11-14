<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref } from 'vue'
import type { EstadoConexionRfid1 } from '~/types/rfid1'
import { etiquetaEstadoConexionRfid1 } from '~/utils/estado-conexion-rfid1'
import { ErrorRfid1Api, useClienteRfid1 } from '~/utils/rfid1-api'

const emit = defineEmits<{
  actualizado: [valor: { estado: EstadoConexionRfid1; etiqueta: string }]
}>()

const api = useClienteRfid1()
const sesion = useSesion()
const estado = ref<EstadoConexionRfid1>('DESCONOCIDO')
const consultada = ref(false)
const errorConsulta = ref(false)
const actualizadoEn = ref<string | null>(null)
const etiqueta = computed(() =>
  etiquetaEstadoConexionRfid1(estado.value, consultada.value, errorConsulta.value),
)

let temporizador: ReturnType<typeof setInterval> | null = null
let controlador: AbortController | null = null
let desmontado = false
let redirigiendo = false

async function consultar() {
  if (!import.meta.client || desmontado || redirigiendo || controlador) return
  const actual = new AbortController()
  controlador = actual
  try {
    const respuesta = await api.consultarEstadoConexion(actual.signal)
    if (actual.signal.aborted || desmontado) return
    estado.value = ['CONECTADO', 'DESCONECTADO', 'DESCONOCIDO'].includes(respuesta.estado)
      ? respuesta.estado
      : 'DESCONOCIDO'
    consultada.value = true
    errorConsulta.value = false
    actualizadoEn.value = respuesta.actualizadoEn
    emit('actualizado', { estado: estado.value, etiqueta: etiqueta.value })
  } catch (fallo) {
    if (actual.signal.aborted || desmontado) return
    if (fallo instanceof ErrorRfid1Api && fallo.estado === 401) {
      redirigiendo = true
      await sesion.limpiar()
      await navigateTo('/panel')
      return
    }
    estado.value = 'DESCONOCIDO'
    consultada.value = true
    errorConsulta.value = true
    actualizadoEn.value = null
    emit('actualizado', { estado: estado.value, etiqueta: etiqueta.value })
  } finally {
    if (controlador === actual) controlador = null
  }
}

onMounted(() => {
  void consultar()
  temporizador = setInterval(() => void consultar(), 5000)
})

onScopeDispose(() => {
  desmontado = true
  if (temporizador) clearInterval(temporizador)
  temporizador = null
  controlador?.abort()
  controlador = null
})
</script>

<template>
  <p
    class="estado-conexion-rfid1"
    :class="`estado-conexion-rfid1--${estado.toLowerCase()}`"
    role="status"
    aria-live="polite"
    aria-atomic="true"
    :aria-label="`Estado de conexión del ESP32 RFID 1 según el último PONG conocido: ${etiqueta}. No indica una lectura activa.`"
    :title="
      actualizadoEn
        ? `PONG del bridge. Actualizado: ${actualizadoEn}. No indica una lectura activa.`
        : 'Estado del ESP32 por PONG del bridge; no indica una lectura activa.'
    "
  >
    <span class="estado-conexion-rfid1__punto" aria-hidden="true"></span>
    <span
      >Conexión RFID 1: <strong>{{ etiqueta }}</strong></span
    >
  </p>
</template>

<style scoped>
.estado-conexion-rfid1 {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: fit-content;
  margin: 0;
  border: 1px solid var(--app-border);
  border-radius: 999px;
  padding: 6px 10px;
  color: var(--app-muted);
  font-size: 0.875rem;
}
.estado-conexion-rfid1 strong {
  color: var(--app-foreground);
  font-weight: 600;
}
.estado-conexion-rfid1__punto {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: currentColor;
}
.estado-conexion-rfid1--conectado .estado-conexion-rfid1__punto {
  color: var(--app-success);
}
.estado-conexion-rfid1--desconectado .estado-conexion-rfid1__punto {
  color: var(--app-error);
}
</style>
