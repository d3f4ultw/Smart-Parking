<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import DentroEstacionamiento from '~/components/admin/accesos/DentroEstacionamiento.vue'
import type {
  EventoAcceso,
  FiltroLectorAccesos,
  FiltroResultadoAccesos,
  PeriodoHistorialAccesos,
} from '~/types/acceso'

definePageMeta({
  layout: 'admin',
  middleware: ['sesion', 'modulo-administracion'],
  alias: '/operador/accesos',
})
useSeoMeta({ title: 'Historial de accesos | Smart Parking' })

const { sesion } = useSesion()
const historial = await useHistorialAccesos()
const vista = ref<'HISTORIAL' | 'DENTRO'>('HISTORIAL')
const {
  datos: entradasDentro,
  pendiente: pendienteDentro,
  mensajeError: errorDentro,
  desactualizado: dentroDesactualizado,
  busqueda: busquedaDentro,
  actualizar: actualizarDentro,
  cambiarPagina: cambiarPaginaDentro,
  buscar: buscarDentro,
} = await useEntradasActivas(vista)
const {
  disponible: dispositivoSalidaDisponible,
  comprobando: comprobandoDispositivoSalida,
  disponibleAhora: dispositivoSalidaDisponibleAhora,
} = useDisponibilidadSalidaManual(vista)
const {
  identidad: identidadSalida,
  abierta: modalSalidaAbierta,
  seleccionada: salidaSeleccionada,
  procesando: procesandoSalida,
  mensaje: mensajeSalida,
  estado: estadoSalida,
  puedeSolicitar: puedeSolicitarSalida,
  seleccionar: seleccionarSalida,
  confirmar: confirmarSalida,
  consultar: consultarSalida,
} = useSalidasManuales(
  entradasDentro,
  actualizarDentro,
  historial.recargar,
  dispositivoSalidaDisponibleAhora,
)
const {
  eventosAcceso,
  lector,
  mensajeError,
  pagina,
  paginaActual,
  pending,
  periodo,
  desde,
  hasta,
  resultado,
} = historial

const lectores: Array<{ label: string; value: FiltroLectorAccesos }> = [
  { label: 'Todos', value: 'TODOS' },
  { label: 'Entrada', value: 'RFID2' },
  { label: 'Salida', value: 'RFID3' },
  { label: 'Salida manual', value: 'MANUAL' },
]
const resultados: Array<{ label: string; value: FiltroResultadoAccesos }> = [
  { label: 'Todos', value: 'TODOS' },
  { label: 'Autorizado', value: 'AUTORIZADA' },
  { label: 'Denegado', value: 'DENEGADA' },
]
const periodos: Array<{ label: string; value: PeriodoHistorialAccesos }> = [
  { label: 'Hoy', value: 'HOY' },
  { label: 'Últimos 7 días', value: 'ULTIMOS_7_DIAS' },
  { label: 'Últimos 30 días', value: 'ULTIMOS_30_DIAS' },
  { label: 'Todo el historial', value: 'TODO' },
  { label: 'Rango personalizado', value: 'PERSONALIZADO' },
]
const selectUi = {
  content: 'w-max min-w-full max-w-[calc(100vw-2rem)]',
  itemLabel: 'whitespace-nowrap',
}
const motivos: Record<string, string> = {
  TARJETA_DESCONOCIDA: 'Tarjeta desconocida',
  TARJETA_CANCELADA: 'Tarjeta cancelada',
  ENTRADA_PENDIENTE: 'Ya existe una entrada abierta',
  SIN_ENTRADA_ABIERTA: 'No existe una entrada abierta',
  FUERA_DE_HORARIO: 'Fuera del horario del estacionamiento',
  CAPACIDAD_COMPLETA: 'Capacidad completa',
  MEMBRESIA_NO_VIGENTE: 'Membresía no vigente',
  SALIDA_MANUAL_EN_CURSO: 'Salida manual en curso',
}
const meses = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
const periodoSeleccionado = ref<PeriodoHistorialAccesos>(periodo.value)
const desdeBorrador = ref(desde.value ?? '')
const hastaBorrador = ref(hasta.value ?? '')
const totalPaginas = computed(() =>
  Math.ceil((pagina.value?.totalRegistros ?? 0) / (pagina.value?.tamano ?? 10)),
)
const paginasVisibles = computed(() => {
  if (totalPaginas.value < 1) return []
  let inicio = Math.max(1, paginaActual.value - 2)
  let fin = Math.min(totalPaginas.value, inicio + 4)
  inicio = Math.max(1, fin - 4)
  return Array.from({ length: fin - inicio + 1 }, (_, indice) => inicio + indice)
})
const primeraPaginaVisible = computed(() => paginasVisibles.value[0] ?? 0)
const ultimaPaginaVisible = computed(() => paginasVisibles.value.at(-1) ?? 0)
const rangoValido = computed(() =>
  Boolean(desdeBorrador.value && hastaBorrador.value && desdeBorrador.value <= hastaBorrador.value),
)
const filtrosActivos = computed(
  () =>
    lector.value !== 'TODOS' || resultado.value !== 'TODOS' || periodo.value !== 'ULTIMOS_7_DIAS',
)
const resultadosSinCoincidencias = computed(
  () => lector.value !== 'TODOS' || resultado.value !== 'TODOS',
)

watch([periodo, desde, hasta], () => {
  periodoSeleccionado.value = periodo.value
  desdeBorrador.value = desde.value ?? ''
  hastaBorrador.value = hasta.value ?? ''
})

let montado = false
onMounted(() => {
  montado = true
  if (vista.value === 'HISTORIAL') historial.iniciarEventos()
})
watch(vista, (actual) => {
  if (!montado) return
  if (actual === 'HISTORIAL') historial.iniciarEventos()
  else historial.detenerEventos()
})

function lectorValido(valor: unknown): valor is FiltroLectorAccesos {
  return valor === 'TODOS' || valor === 'RFID2' || valor === 'RFID3' || valor === 'MANUAL'
}

function resultadoValido(valor: unknown): valor is FiltroResultadoAccesos {
  return valor === 'TODOS' || valor === 'AUTORIZADA' || valor === 'DENEGADA'
}

function periodoValido(valor: unknown): valor is PeriodoHistorialAccesos {
  return periodos.some((opcion) => opcion.value === valor)
}

function cambiarLector(valor: unknown) {
  if (lectorValido(valor)) void historial.cambiarLector(valor)
}

function cambiarResultado(valor: unknown) {
  if (resultadoValido(valor)) void historial.cambiarResultado(valor)
}

function seleccionarPeriodo(valor: unknown) {
  if (!periodoValido(valor)) return
  periodoSeleccionado.value = valor
  if (valor !== 'PERSONALIZADO') void historial.cambiarPeriodo(valor)
}

function aplicarRango() {
  if (rangoValido.value) void historial.cambiarRango(desdeBorrador.value, hastaBorrador.value)
}

function nombreLector(evento: EventoAcceso) {
  if (evento.lector === 'RFID2') return 'Entrada'
  return evento.lector === 'MANUAL' ? 'Salida manual' : 'Salida'
}

function nombrePersona(evento: EventoAcceso) {
  if (!evento.persona) return 'Sin persona asociada'
  return `${evento.persona.tipo === 'CLIENTE' ? 'Cliente' : 'Empleado'} · ${evento.persona.nombre}`
}

function motivoDenegacion(evento: EventoAcceso) {
  if (evento.resultado !== 'DENEGADA') return ''
  if (!evento.motivo) return 'Motivo no disponible'
  return motivos[evento.motivo] ?? evento.motivo.replaceAll('_', ' ').toLowerCase()
}

function fechaLegible(valor: string) {
  const [anio, mes, dia] = valor.slice(0, 10).split('-')
  return `${dia} ${meses[Number(mes) - 1] ?? ''} ${anio}`
}

function horaLegible(valor: string) {
  return valor.slice(11, 19)
}
</script>

<template>
  <section class="seccion-historial" aria-label="Accesos">
    <p class="descripcion-historial">
      Revisa las entradas y salidas registradas y el resultado de cada acceso.
    </p>

    <div class="vistas-accesos" role="group" aria-label="Vistas de accesos">
      <UButton
        :color="vista === 'HISTORIAL' ? 'primary' : 'neutral'"
        :variant="vista === 'HISTORIAL' ? 'solid' : 'outline'"
        :aria-pressed="vista === 'HISTORIAL'"
        @click="vista = 'HISTORIAL'"
      >
        Historial
      </UButton>
      <UButton
        :color="vista === 'DENTRO' ? 'primary' : 'neutral'"
        :variant="vista === 'DENTRO' ? 'solid' : 'outline'"
        :aria-pressed="vista === 'DENTRO'"
        @click="vista = 'DENTRO'"
      >
        Dentro del estacionamiento
      </UButton>
    </div>

    <section
      v-if="vista === 'HISTORIAL'"
      class="panel-historial"
      aria-label="Registros de acceso"
      aria-live="polite"
      :aria-busy="pending"
    >
      <div class="barra-historial">
        <div class="resumen-historial">
          <h2>Registros</h2>
          <span v-if="pagina" class="zona-horaria">Hora local · {{ pagina.zonaHoraria }}</span>
        </div>

        <div class="filtros-historial">
          <UFormField label="Periodo" name="periodo">
            <USelect
              :model-value="periodoSeleccionado"
              :items="periodos"
              :ui="selectUi"
              class="filtro-historial filtro-periodo"
              @update:model-value="seleccionarPeriodo"
            />
          </UFormField>
          <UFormField label="Lector" name="lector">
            <USelect
              :model-value="lector"
              :items="lectores"
              :ui="selectUi"
              class="filtro-historial"
              @update:model-value="cambiarLector"
            />
          </UFormField>
          <UFormField label="Resultado" name="resultado">
            <USelect
              :model-value="resultado"
              :items="resultados"
              :ui="selectUi"
              class="filtro-historial"
              @update:model-value="cambiarResultado"
            />
          </UFormField>
          <UButton
            v-if="filtrosActivos"
            color="neutral"
            variant="ghost"
            class="limpiar-filtros"
            @click="historial.limpiarFiltros()"
          >
            Limpiar filtros
          </UButton>
        </div>
      </div>

      <div v-if="periodoSeleccionado === 'PERSONALIZADO'" class="rango-personalizado">
        <UFormField label="Desde" name="desde">
          <input
            v-model="desdeBorrador"
            class="entrada-fecha"
            type="date"
            aria-label="Fecha inicial"
          />
        </UFormField>
        <UFormField label="Hasta" name="hasta">
          <input
            v-model="hastaBorrador"
            class="entrada-fecha"
            type="date"
            aria-label="Fecha final"
          />
        </UFormField>
        <UButton :disabled="!rangoValido || pending" @click="aplicarRango">Aplicar rango</UButton>
        <p v-if="desdeBorrador && hastaBorrador && !rangoValido" class="error-rango" role="alert">
          La fecha final debe ser igual o posterior a la fecha inicial.
        </p>
      </div>

      <p v-if="pending && !pagina" class="estado-historial" role="status">Cargando el historial…</p>
      <div v-else-if="mensajeError" class="estado-historial estado-historial--error" role="alert">
        <p>{{ mensajeError }}</p>
        <UButton
          color="neutral"
          variant="outline"
          icon="i-lucide-refresh-cw"
          :loading="pending"
          @click="historial.recargar()"
        >
          Reintentar
        </UButton>
      </div>
      <p v-else-if="!eventosAcceso.length" class="estado-historial">
        {{
          resultadosSinCoincidencias
            ? 'No hay resultados con estos filtros.'
            : 'No hay accesos en este periodo.'
        }}
      </p>
      <ol v-else class="lista-accesos">
        <li v-for="evento in eventosAcceso" :key="evento.id">
          <article class="fila-acceso">
            <time class="fecha-acceso" :datetime="evento.ocurridoEn">
              <span>{{ fechaLegible(evento.ocurridoEnLocal) }}</span>
              <span class="hora-acceso">{{ horaLegible(evento.ocurridoEnLocal) }}</span>
            </time>
            <div class="lector-acceso">{{ nombreLector(evento) }}</div>
            <div class="detalle-acceso">
              <span class="persona-acceso">{{ nombrePersona(evento) }}</span>
              <span v-if="motivoDenegacion(evento)" class="motivo-acceso">
                {{ motivoDenegacion(evento) }}
              </span>
            </div>
            <span
              class="resultado-acceso"
              :class="
                evento.resultado === 'AUTORIZADA'
                  ? 'resultado-acceso--autorizada'
                  : 'resultado-acceso--denegada'
              "
            >
              {{ evento.resultado === 'AUTORIZADA' ? 'Autorizado' : 'Denegado' }}
            </span>
          </article>
        </li>
      </ol>

      <p v-if="pending && pagina" class="aviso-actualizacion" role="status">
        Actualizando el historial…
      </p>
      <footer v-if="pagina && totalPaginas > 0" class="pie-historial">
        <span class="resumen-paginacion">
          {{ (paginaActual - 1) * pagina.tamano + 1 }}–{{
            Math.min(paginaActual * pagina.tamano, pagina.totalRegistros)
          }}
          de {{ pagina.totalRegistros }} registros
        </span>
        <nav class="controles-pagina" aria-label="Paginación del historial">
          <UButton
            color="neutral"
            variant="outline"
            icon="i-lucide-chevron-left"
            aria-label="Página anterior"
            :disabled="pending || paginaActual <= 1"
            @click="historial.cambiarPagina(paginaActual - 1)"
          />
          <template v-if="primeraPaginaVisible > 1">
            <UButton
              color="neutral"
              variant="outline"
              aria-label="Página 1"
              @click="historial.cambiarPagina(1)"
            >
              1
            </UButton>
            <span v-if="primeraPaginaVisible > 2" class="separador-paginas" aria-hidden="true"
              >…</span
            >
          </template>
          <UButton
            v-for="numero in paginasVisibles"
            :key="numero"
            :color="numero === paginaActual ? 'primary' : 'neutral'"
            :variant="numero === paginaActual ? 'solid' : 'outline'"
            :aria-label="`Página ${numero}`"
            :aria-current="numero === paginaActual ? 'page' : undefined"
            :disabled="pending"
            @click="historial.cambiarPagina(numero)"
          >
            {{ numero }}
          </UButton>
          <template v-if="ultimaPaginaVisible < totalPaginas">
            <span
              v-if="ultimaPaginaVisible < totalPaginas - 1"
              class="separador-paginas"
              aria-hidden="true"
            >
              …
            </span>
            <UButton
              color="neutral"
              variant="outline"
              :aria-label="`Página ${totalPaginas}`"
              :disabled="pending"
              @click="historial.cambiarPagina(totalPaginas)"
            >
              {{ totalPaginas }}
            </UButton>
          </template>
          <UButton
            color="neutral"
            variant="outline"
            trailing-icon="i-lucide-chevron-right"
            aria-label="Página siguiente"
            :disabled="pending || paginaActual >= totalPaginas"
            @click="historial.cambiarPagina(paginaActual + 1)"
          />
        </nav>
      </footer>
    </section>
    <DentroEstacionamiento
      v-else-if="sesion.estado === 'autenticada'"
      :key="sesion.identidad.rol + ':' + sesion.identidad.correo"
      :datos="entradasDentro"
      :pendiente="pendienteDentro"
      :mensaje-error="errorDentro"
      :desactualizado="dentroDesactualizado"
      :busqueda="busquedaDentro"
      :identidad-permitida="Boolean(identidadSalida)"
      :dispositivo-disponible="dispositivoSalidaDisponible"
      :comprobando-dispositivo="comprobandoDispositivoSalida"
      :salida-abierta="modalSalidaAbierta"
      :salida-seleccionada="salidaSeleccionada"
      :procesando-salida="procesandoSalida"
      :mensaje-salida="mensajeSalida"
      :estado-salida="estadoSalida"
      :puede-solicitar-salida="puedeSolicitarSalida"
      @actualizar="actualizarDentro"
      @cambiar-pagina="cambiarPaginaDentro"
      @buscar="buscarDentro"
      @seleccionar-salida="seleccionarSalida"
      @confirmar-salida="confirmarSalida"
      @consultar-salida="consultarSalida"
      @update:salida-abierta="modalSalidaAbierta = $event"
    />
  </section>
</template>

<style scoped>
.seccion-historial {
  display: grid;
  gap: 20px;
}
.vistas-accesos {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.descripcion-historial {
  max-width: 68ch;
  margin: -8px 0 0;
  color: var(--app-muted);
  line-height: 1.5;
}
.panel-historial {
  display: grid;
  gap: 12px;
  border: 1px solid var(--app-border);
  border-radius: 16px;
  padding: clamp(14px, 2vw, 22px);
  background: var(--app-surface);
  box-shadow: 0 2px 8px rgb(41 37 47 / 4%);
}
.barra-historial,
.resumen-historial,
.pie-historial,
.controles-pagina {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.resumen-historial {
  align-items: flex-start;
  flex-direction: column;
  gap: 4px;
}
.resumen-historial h2 {
  margin: 0;
  color: var(--app-foreground);
  font-size: 1rem;
  font-weight: 600;
}
.zona-horaria,
.pie-historial {
  color: var(--app-muted);
  font-size: 0.84rem;
}
.filtros-historial {
  display: flex;
  align-items: end;
  flex-wrap: wrap;
  gap: 10px;
}
.filtro-historial {
  min-width: 9rem;
}
.filtro-periodo {
  min-width: 11rem;
}
.limpiar-filtros {
  min-height: 2.5rem;
}
.rango-personalizado {
  display: flex;
  align-items: end;
  flex-wrap: wrap;
  gap: 12px;
  border-top: 1px solid var(--app-border);
  padding-top: 12px;
}
.entrada-fecha {
  min-height: 2.5rem;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  padding: 0.4rem 0.65rem;
  background: var(--app-surface);
  color: var(--app-foreground);
}
.error-rango {
  margin: 0;
  color: var(--app-error);
  font-size: 0.84rem;
}
.lista-accesos {
  margin: 0;
  padding: 0;
  list-style: none;
}
.lista-accesos li + li {
  border-top: 1px solid var(--app-border);
}
.fila-acceso {
  display: grid;
  grid-template-columns: minmax(7.5rem, 0.7fr) minmax(9rem, 0.9fr) minmax(10rem, 2fr) auto;
  align-items: center;
  gap: 14px;
  min-height: 58px;
  padding: 8px 0;
}
.fecha-acceso,
.lector-acceso {
  color: var(--app-foreground);
  font-size: 0.9rem;
  font-weight: 600;
}
.fecha-acceso {
  display: grid;
  gap: 2px;
  font-variant-numeric: tabular-nums;
}
.hora-acceso,
.persona-acceso,
.motivo-acceso {
  color: var(--app-muted);
  font-size: 0.84rem;
  font-weight: 400;
}
.detalle-acceso {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.persona-acceso,
.motivo-acceso {
  overflow-wrap: anywhere;
}
.motivo-acceso {
  color: var(--app-error);
}
.resultado-acceso {
  border: 1px solid var(--app-border);
  border-radius: 8px;
  padding: 5px 8px;
  font-size: 0.76rem;
  font-weight: 650;
  white-space: nowrap;
}
.resultado-acceso--autorizada {
  border-color: #a6d8bf;
  background: #eff9f3;
  color: #17623d;
}
.resultado-acceso--denegada {
  border-color: #edb4b4;
  background: #fff3f2;
  color: #8b2525;
}
.estado-historial {
  display: grid;
  min-height: 10rem;
  gap: 12px;
  place-content: center;
  justify-items: center;
  margin: 0;
  color: var(--app-muted);
  text-align: center;
}
.estado-historial--error {
  color: var(--app-error);
}
.aviso-actualizacion {
  margin: 0;
  color: var(--app-muted);
  font-size: 0.82rem;
}
.pie-historial {
  flex-wrap: wrap;
  border-top: 1px solid var(--app-border);
  padding-top: 12px;
}
.controles-pagina {
  justify-content: flex-end;
  gap: 5px;
}
.separador-paginas {
  padding: 0 3px;
  color: var(--app-muted);
}
@media (max-width: 60rem) {
  .barra-historial {
    align-items: stretch;
    flex-direction: column;
  }
  .filtros-historial {
    align-items: end;
  }
  .fila-acceso {
    grid-template-columns: minmax(7rem, 0.8fr) minmax(9rem, 1fr) auto;
  }
  .detalle-acceso {
    grid-column: 2;
  }
  .resultado-acceso {
    grid-column: 3;
    grid-row: 1 / span 2;
    justify-self: end;
  }
}
@media (max-width: 38rem) {
  .filtros-historial > :deep(*) {
    flex: 1 1 9rem;
  }
  .filtro-historial,
  .filtro-periodo {
    min-width: 100%;
  }
  .rango-personalizado > :deep(*) {
    flex: 1 1 9rem;
  }
  .entrada-fecha {
    width: 100%;
  }
  .fila-acceso {
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 6px 10px;
    padding: 10px 0;
  }
  .fecha-acceso {
    grid-column: 1;
    grid-row: 1;
  }
  .lector-acceso {
    grid-column: 1;
    grid-row: 2;
  }
  .detalle-acceso {
    grid-column: 1 / -1;
    grid-row: 3;
  }
  .resultado-acceso {
    grid-column: 2;
    grid-row: 1;
  }
  .pie-historial {
    align-items: stretch;
    flex-direction: column;
  }
  .controles-pagina {
    justify-content: flex-start;
    flex-wrap: wrap;
  }
}
</style>
