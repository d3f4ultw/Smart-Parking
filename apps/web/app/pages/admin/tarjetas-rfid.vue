<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import type {
  EstadoConexionRfid1 as TipoEstadoConexionRfid1,
  FiltroTipoEntidadRfid1,
  TipoEstacionamientoRfid1,
  TarjetaRfid1,
} from '~/types/rfid1'
import DirectorioTarjetasRfid1 from '~/components/admin/tarjetas-rfid/DirectorioTarjetasRfid1.vue'
import EstadoConexionRfid1 from '~/components/admin/tarjetas-rfid/EstadoConexionRfid1.vue'
import ModalAsociacionTarjetaRfid1 from '~/components/admin/tarjetas-rfid/ModalAsociacionTarjetaRfid1.vue'
import ModalDetalleTarjetaRfid1 from '~/components/admin/tarjetas-rfid/ModalDetalleTarjetaRfid1.vue'
import { useDirectorioTarjetasRfid1 } from '~/composables/useDirectorioTarjetasRfid1'
import { useFlujoAsociacionRfid1 } from '~/composables/useFlujoAsociacionRfid1'
import { ErrorRfid1Api, useClienteRfid1 } from '~/utils/rfid1-api'

definePageMeta({
  layout: 'admin',
  middleware: ['sesion', 'modulo-administracion'],
  alias: '/operador/tarjetas',
})
useSeoMeta({ title: 'Tarjetas | SmartParking' })

const sesion = useSesion()
const api = useClienteRfid1()
const modalidad = ref<TipoEstacionamientoRfid1 | null>(null)
const tipoInicial = ref<FiltroTipoEntidadRfid1>('CLIENTE')
const tipoDirectorioInicial = ref<FiltroTipoEntidadRfid1>('MIXTO')
const directorioHabilitado = ref(true)
const modalidadLista = ref(false)
const cargandoModalidad = ref(false)
const errorModalidad = ref('')
const asociacionIdDetalle = ref<number | null>(null)
const conexionRfid1 = ref({
  estado: 'DESCONOCIDO' as TipoEstadoConexionRfid1,
  etiqueta: 'Comprobando',
})
const directorio = useDirectorioTarjetasRfid1(tipoDirectorioInicial, directorioHabilitado)
const flujo = useFlujoAsociacionRfid1(tipoInicial)

const {
  tipoEntidad: tipoEntidadDirectorio,
  estado,
  pagina,
  busqueda: busquedaDirectorio,
  busquedaAplicada,
  tarjetas,
  total,
  totalPaginas,
  cargando,
  mensajeError,
  cargar,
  actualizar,
  cambiarTipo: cambiarTipoDirectorio,
  cambiarEstado,
  cambiarPagina,
  cambiarBusqueda: cambiarBusquedaDirectorio,
} = directorio
const {
  abierta,
  paso,
  tipoEntidad,
  busqueda,
  candidatos,
  candidatosPendientes,
  errorBusqueda,
  seleccionada,
  personaCaptura,
  captura,
  vistaPrevia,
  fase,
  mensajeError: errorFlujo,
  mensajeCaptura,
  segundosRestantes,
  ocupado,
  abrir,
  cambiarTipo: cambiarTipoPersona,
  seleccionar,
  iniciarLectura,
  confirmarAsociacion,
  cancelarCaptura,
  volverASeleccion,
  escanearOtraTarjeta,
  cerrar,
  actualizarBusqueda: actualizarBusquedaFlujo,
  cambiarPersona,
} = flujo

const modalidadEtiqueta = computed(() => {
  if (modalidad.value === 'PUBLICO') return 'Público'
  if (modalidad.value === 'PRIVADO') return 'Privado'
  if (modalidad.value === 'MIXTO') return 'Mixto'
  return errorModalidad.value ? 'No disponible' : 'Consultando…'
})
const tiposEntidadAsociacion = computed<FiltroTipoEntidadRfid1[]>(() => {
  if (modalidad.value === 'PUBLICO') return ['CLIENTE']
  if (modalidad.value === 'PRIVADO') return ['EMPLEADO']
  if (modalidad.value === 'MIXTO') return ['CLIENTE', 'EMPLEADO', 'MIXTO']
  return []
})
const detalleAbierto = computed(() => asociacionIdDetalle.value !== null)
const mostrarUid = computed(
  () =>
    sesion.sesion.value.estado === 'autenticada' && sesion.sesion.value.identidad.rol === 'DUENO',
)

async function cargarModalidad() {
  if (cargandoModalidad.value) return
  cargandoModalidad.value = true
  errorModalidad.value = ''
  try {
    const respuesta = await api.consultarModalidad()
    const tipoModalidad = respuesta.tipoEstacionamiento
    if (tipoModalidad !== 'PUBLICO' && tipoModalidad !== 'PRIVADO' && tipoModalidad !== 'MIXTO') {
      errorModalidad.value = 'No pudimos determinar la modalidad.'
      return
    }
    modalidad.value = tipoModalidad
    tipoInicial.value =
      tipoModalidad === 'PUBLICO' ? 'CLIENTE' : tipoModalidad === 'PRIVADO' ? 'EMPLEADO' : 'MIXTO'
    cambiarTipoPersona(tipoInicial.value)
    await nextTick()
    modalidadLista.value = true
  } catch (fallo) {
    if (fallo instanceof ErrorRfid1Api && fallo.estado === 401) {
      await sesion.limpiar()
      await navigateTo('/panel')
    } else {
      errorModalidad.value = 'No pudimos consultar la modalidad del estacionamiento.'
    }
  } finally {
    cargandoModalidad.value = false
  }
}

onMounted(() => void cargarModalidad())

function continuar() {
  if (seleccionada.value?.elegible) paso.value = 2
}

function mostrarDetalle(tarjeta: TarjetaRfid1) {
  asociacionIdDetalle.value = tarjeta.asociacionId
}

function actualizarDetalle(abierta: boolean) {
  if (!abierta) asociacionIdDetalle.value = null
}

function actualizarBusqueda(valor: string) {
  actualizarBusquedaFlujo(valor)
}

function actualizarEstadoConexion(valor: { estado: TipoEstadoConexionRfid1; etiqueta: string }) {
  conexionRfid1.value = valor
}
</script>

<template>
  <section class="pagina-tarjetas-rfid" aria-label="Tarjetas">
    <header class="encabezado-tarjetas-rfid">
      <div class="resumen-tarjetas-rfid">
        <p class="descripcion-tarjetas-rfid">Asocia tarjetas y consulta su historial.</p>
        <div class="indicadores-tarjetas-rfid">
          <EstadoConexionRfid1 @actualizado="actualizarEstadoConexion" />
          <UBadge color="neutral" variant="subtle" class="etiqueta-modalidad-rfid">
            Modalidad: {{ modalidadEtiqueta }}
          </UBadge>
        </div>
      </div>
      <UButton
        id="rfid-abrir-asociacion"
        class="accion-asociar-rfid"
        icon="i-lucide-plus"
        :loading="cargandoModalidad"
        :disabled="!modalidadLista || cargandoModalidad"
        @click="abrir"
      >
        Asociar tarjeta
      </UButton>
    </header>

    <div v-if="errorModalidad" class="estado-modalidad-rfid">
      <p class="mensaje-error-rfid" role="alert">{{ errorModalidad }}</p>
      <UButton
        color="neutral"
        variant="outline"
        :loading="cargandoModalidad"
        :disabled="cargandoModalidad"
        @click="cargarModalidad"
      >
        Reintentar
      </UButton>
    </div>
    <DirectorioTarjetasRfid1
      :tipo-entidad="tipoEntidadDirectorio"
      :estado="estado"
      :pagina="pagina"
      :busqueda="busquedaDirectorio"
      :busqueda-aplicada="busquedaAplicada"
      :tarjetas="tarjetas"
      :total="total"
      :total-paginas="totalPaginas"
      :cargando="cargando"
      :error="mensajeError"
      :mostrar-uid="mostrarUid"
      @actualizar="actualizar"
      @cambiar-tipo="cambiarTipoDirectorio"
      @cambiar-estado="cambiarEstado"
      @cambiar-pagina="cambiarPagina"
      @cambiar-busqueda="cambiarBusquedaDirectorio"
      @detalle="mostrarDetalle"
    />

    <ModalAsociacionTarjetaRfid1
      v-if="modalidadLista"
      :open="abierta"
      :paso="paso"
      :tipo-entidad="tipoEntidad"
      :tipos-entidad-disponibles="tiposEntidadAsociacion"
      :busqueda="busqueda"
      :candidatos="candidatos"
      :seleccionada="seleccionada"
      :persona="personaCaptura"
      :captura="captura"
      :vista-previa="vistaPrevia"
      :candidatos-pendientes="candidatosPendientes"
      :error-busqueda="errorBusqueda"
      :fase="fase"
      :mensaje-error="errorFlujo"
      :mensaje-captura="mensajeCaptura"
      :segundos-restantes="segundosRestantes"
      :ocupado="ocupado"
      :estado-conexion="conexionRfid1.estado"
      :etiqueta-conexion="conexionRfid1.etiqueta"
      @update:tipo-entidad="cambiarTipoPersona"
      @update:busqueda="actualizarBusqueda"
      @seleccionar="seleccionar"
      @cambiar-persona="cambiarPersona"
      @continuar="continuar"
      @iniciar="iniciarLectura"
      @confirmar="confirmarAsociacion"
      @cancelar-captura="cancelarCaptura"
      @volver="volverASeleccion"
      @escanear-otra="escanearOtraTarjeta"
      @cerrar="cerrar"
    />

    <ModalDetalleTarjetaRfid1
      :open="detalleAbierto"
      :asociacion-id="asociacionIdDetalle"
      :mostrar-uid="mostrarUid"
      @update:open="actualizarDetalle"
      @actualizada="cargar"
    />
  </section>
</template>

<style scoped>
.pagina-tarjetas-rfid {
  display: grid;
  gap: 24px;
}
.encabezado-tarjetas-rfid {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.descripcion-tarjetas-rfid {
  margin: 0;
  color: var(--app-muted);
}
.resumen-tarjetas-rfid {
  display: grid;
  gap: 12px;
}
.indicadores-tarjetas-rfid {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.etiqueta-modalidad-rfid {
  border-radius: 999px;
  padding: 6px 10px;
}
.mensaje-error-rfid {
  margin: 0;
  color: var(--app-error);
}
.estado-modalidad-rfid {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}
@media (max-width: 44rem) {
  .encabezado-tarjetas-rfid {
    align-items: stretch;
    flex-direction: column;
  }
  .accion-asociar-rfid {
    width: 100%;
    justify-content: center;
  }
}
</style>
