<script setup lang="ts">
import type { EntradaActiva, EstadoSalidaManual, PaginaEntradasActivas } from '~/types/acceso'

const props = defineProps<{
  datos: PaginaEntradasActivas | null
  pendiente: boolean
  mensajeError: string
  desactualizado: boolean
  busqueda: string
  identidadPermitida: boolean
  dispositivoDisponible: boolean
  comprobandoDispositivo: boolean
  salidaAbierta: boolean
  salidaSeleccionada: EntradaActiva | null
  procesandoSalida: boolean
  mensajeSalida: string
  estadoSalida: (
    entrada: EntradaActiva,
  ) => { estado: EstadoSalidaManual | 'SIN_CONFIRMACION' } | null
  puedeSolicitarSalida: (entrada: EntradaActiva) => boolean
}>()

const emit = defineEmits<{
  actualizar: []
  cambiarPagina: [numero: number]
  buscar: [valor: string]
  seleccionarSalida: [entrada: EntradaActiva]
  confirmarSalida: []
  consultarSalida: [entrada: EntradaActiva]
  'update:salidaAbierta': [abierta: boolean]
}>()

const busquedaBorrador = ref(props.busqueda)
const totalPaginas = computed(() =>
  Math.max(1, Math.ceil((props.datos?.totalRegistros ?? 0) / (props.datos?.tamano ?? 10))),
)

function fechaLocal(valor: string) {
  return valor.slice(0, 19).replace('T', ' ')
}

function limpiarBusqueda() {
  busquedaBorrador.value = ''
  emit('buscar', '')
}

function descripcionEstado(estado: EstadoSalidaManual | 'SIN_CONFIRMACION') {
  switch (estado) {
    case 'PENDIENTE':
      return 'Salida pendiente del dispositivo. Si no responde o no admite esta función, la solicitud vencerá sin confirmar la salida.'
    case 'EMITIDA':
      return 'Salida en proceso.'
    case 'CONFIRMADA':
      return 'Salida confirmada. Actualizando la lista.'
    case 'NO_EJECUTADA':
      return 'La salida no se ejecutó. El vehículo sigue contado dentro.'
    case 'ANULADA':
      return 'La solicitud fue anulada. El vehículo sigue contado dentro.'
    case 'INCIERTA':
    case 'SIN_CONFIRMACION':
      return 'Salida no confirmada. El vehículo se mantiene en la lista hasta confirmar su cierre.'
  }
}
</script>

<template>
  <section
    class="panel-dentro"
    aria-labelledby="titulo-dentro"
    aria-live="polite"
    :aria-busy="pendiente"
  >
    <header class="encabezado-dentro">
      <div>
        <h2 id="titulo-dentro">Dentro del estacionamiento</h2>
        <p>Vehículos con una entrada registrada y sin salida.</p>
      </div>
      <UButton
        color="neutral"
        variant="outline"
        icon="i-lucide-refresh-cw"
        :disabled="pendiente"
        @click="$emit('actualizar')"
      >
        Actualizar
      </UButton>
    </header>
    <form class="busqueda-dentro" @submit.prevent="emit('buscar', busquedaBorrador)">
      <UFormField label="Buscar por nombre o código" name="busqueda">
        <UInput
          v-model="busquedaBorrador"
          placeholder="Nombre o código"
          maxlength="100"
          autocomplete="off"
          type="search"
        />
      </UFormField>
      <UButton type="submit" color="neutral" variant="outline">Buscar</UButton>
      <UButton
        v-if="busqueda || busquedaBorrador"
        type="button"
        color="neutral"
        variant="ghost"
        @click="limpiarBusqueda"
      >
        Limpiar búsqueda
      </UButton>
    </form>
    <p v-if="mensajeSalida && !salidaAbierta" class="aviso-dentro" role="alert">
      {{ mensajeSalida }}
    </p>
    <p v-if="identidadPermitida && !dispositivoDisponible" class="aviso-dentro" role="status">
      {{
        comprobandoDispositivo
          ? 'Comprobando la disponibilidad de la salida manual…'
          : 'Salida manual no disponible: no se pudo verificar el dispositivo o su compatibilidad.'
      }}
    </p>
    <p v-if="mensajeError" class="aviso-dentro" role="alert">{{ mensajeError }}</p>
    <p v-else-if="pendiente && !datos" class="aviso-dentro" role="status">
      Consultando los vehículos dentro…
    </p>
    <template v-else-if="datos">
      <p v-if="desactualizado" class="aviso-dentro" role="status">
        La conexión de actualizaciones se interrumpió. Estamos recuperando los datos.
      </p>
      <p v-if="datos.items.length === 0" class="aviso-dentro">
        {{
          busqueda
            ? 'No hay resultados para esta búsqueda.'
            : 'No hay vehículos registrados dentro del estacionamiento.'
        }}
      </p>
      <ul v-else class="lista-dentro">
        <li v-for="entrada in datos.items" :key="entrada.movimientoId" class="entrada-dentro">
          <div>
            <strong>{{ entrada.persona.nombre }}</strong>
            <span>
              {{ entrada.persona.tipo === 'CLIENTE' ? 'Cliente' : 'Empleado' }} ·
              {{ entrada.persona.codigo }}
            </span>
          </div>
          <div>
            <span>Entrada</span>
            <time :datetime="entrada.entradaEn">{{ fechaLocal(entrada.entradaEnLocal) }}</time>
          </div>
          <span class="estado-tarjeta">
            {{ entrada.estadoTarjeta === 'ACTIVA' ? 'Tarjeta activa' : 'Tarjeta cancelada' }}
          </span>
          <div
            v-if="identidadPermitida && entrada.estadoTarjeta === 'CANCELADA'"
            class="salida-manual"
          >
            <p v-if="estadoSalida(entrada)" role="status">
              {{ descripcionEstado(estadoSalida(entrada)!.estado) }}
            </p>
            <UButton
              v-if="
                !estadoSalida(entrada) ||
                ['NO_EJECUTADA', 'ANULADA'].includes(estadoSalida(entrada)!.estado)
              "
              color="neutral"
              variant="outline"
              :disabled="procesandoSalida || !puedeSolicitarSalida(entrada)"
              @click="emit('seleccionarSalida', entrada)"
            >
              Salida manual
            </UButton>
            <UButton
              v-else-if="estadoSalida(entrada)"
              color="neutral"
              variant="ghost"
              :disabled="procesandoSalida"
              @click="emit('consultarSalida', entrada)"
            >
              Consultar estado
            </UButton>
          </div>
        </li>
      </ul>
      <footer v-if="datos.totalRegistros > 0" class="pie-dentro">
        <span>{{ datos.totalRegistros }} vehículos · Hora local {{ datos.zonaHoraria }}</span>
        <nav aria-label="Paginación de vehículos dentro">
          <UButton
            color="neutral"
            variant="outline"
            icon="i-lucide-chevron-left"
            aria-label="Página anterior de vehículos dentro"
            :disabled="pendiente || datos.pagina <= 1"
            @click="$emit('cambiarPagina', datos.pagina - 1)"
          />
          <span>Página {{ datos.pagina }} de {{ totalPaginas }}</span>
          <UButton
            color="neutral"
            variant="outline"
            icon="i-lucide-chevron-right"
            aria-label="Página siguiente de vehículos dentro"
            :disabled="pendiente || !datos.haySiguiente"
            @click="$emit('cambiarPagina', datos.pagina + 1)"
          />
        </nav>
      </footer>
    </template>
    <UModal
      :open="salidaAbierta"
      title="Confirmar salida manual"
      description="Esta acción abre la salida para la visita seleccionada."
      :dismissible="!procesandoSalida"
      @update:open="emit('update:salidaAbierta', $event)"
    >
      <template #body>
        <p>¿Abrir la salida y registrar la salida de {{ salidaSeleccionada?.persona.nombre }}?</p>
        <p v-if="mensajeSalida" class="aviso-dentro" role="alert">{{ mensajeSalida }}</p>
      </template>
      <template #footer>
        <UButton
          color="neutral"
          variant="outline"
          :disabled="procesandoSalida"
          @click="emit('update:salidaAbierta', false)"
        >
          Cerrar
        </UButton>
        <UButton
          color="primary"
          :loading="procesandoSalida"
          :disabled="
            procesandoSalida || !salidaSeleccionada || !puedeSolicitarSalida(salidaSeleccionada)
          "
          @click="emit('confirmarSalida')"
        >
          Confirmar salida manual
        </UButton>
      </template>
    </UModal>
  </section>
</template>

<style scoped>
.panel-dentro {
  display: grid;
  gap: 16px;
  border: 1px solid var(--app-border);
  border-radius: 16px;
  padding: clamp(14px, 2vw, 22px);
  background: var(--app-surface);
}
.encabezado-dentro,
.busqueda-dentro,
.pie-dentro,
.pie-dentro nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.busqueda-dentro {
  align-items: end;
  justify-content: flex-start;
  flex-wrap: wrap;
}
.encabezado-dentro h2 {
  margin: 0;
  color: var(--app-foreground);
  font-size: 1rem;
  font-weight: 600;
}
.encabezado-dentro p,
.aviso-dentro,
.pie-dentro,
.entrada-dentro span {
  margin: 4px 0 0;
  color: var(--app-muted);
  font-size: 0.875rem;
}
.lista-dentro {
  margin: 0;
  padding: 0;
  list-style: none;
}
.entrada-dentro {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) minmax(0, 0.65fr);
  align-items: center;
  gap: 16px;
  border-top: 1px solid var(--app-border);
  padding: 14px 0;
}
.entrada-dentro div {
  display: grid;
  min-width: 0;
  gap: 3px;
}
.estado-tarjeta {
  justify-self: end;
  text-align: right;
}
.salida-manual {
  grid-column: 2 / -1;
  justify-self: end;
  text-align: right;
}
.salida-manual p {
  max-width: 20rem;
  margin: 0;
  color: var(--app-muted);
  font-size: 0.875rem;
}
.entrada-dentro strong,
.entrada-dentro time {
  color: var(--app-foreground);
  overflow-wrap: anywhere;
}
@media (max-width: 700px) {
  .encabezado-dentro,
  .pie-dentro {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .entrada-dentro {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: start;
    gap: 8px 12px;
  }
  .estado-tarjeta,
  .salida-manual {
    grid-column: 1 / -1;
    justify-self: start;
    text-align: left;
  }
}
</style>
