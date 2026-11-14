<script setup lang="ts">
import { computed } from 'vue'
import type { TarjetaRfid1, FiltroTipoEntidadRfid1 } from '~/types/rfid1'
import type { FiltroTarjetasRfid1 } from '~/composables/useDirectorioTarjetasRfid1'

const props = defineProps<{
  tipoEntidad: FiltroTipoEntidadRfid1
  estado: FiltroTarjetasRfid1
  pagina: number
  busqueda: string
  busquedaAplicada: string
  tarjetas: TarjetaRfid1[]
  total: number
  totalPaginas: number
  cargando: boolean
  error: string
  mostrarUid: boolean
}>()
const emit = defineEmits<{
  actualizar: []
  cambiarTipo: [valor: FiltroTipoEntidadRfid1]
  cambiarEstado: [valor: FiltroTarjetasRfid1]
  cambiarPagina: [valor: number]
  cambiarBusqueda: [valor: string]
  detalle: [tarjeta: TarjetaRfid1]
}>()

const hayFiltros = computed(
  () =>
    Boolean(props.busquedaAplicada) || props.tipoEntidad !== 'MIXTO' || props.estado !== 'TODAS',
)
const paginasVisibles = computed(() => {
  const inicio = Math.max(1, Math.min(props.pagina - 2, props.totalPaginas - 4))
  const fin = Math.min(props.totalPaginas, inicio + 4)
  return Array.from({ length: Math.max(0, fin - inicio + 1) }, (_, indice) => inicio + indice)
})
const primerResultado = computed(() => (props.total ? (props.pagina - 1) * 10 + 1 : 0))
const ultimoResultado = computed(() => Math.min(props.pagina * 10, props.total))

function cambiarTipo(evento: Event) {
  const valor = (evento.target as HTMLSelectElement).value
  if (['MIXTO', 'CLIENTE', 'EMPLEADO'].includes(valor)) {
    emit('cambiarTipo', valor as FiltroTipoEntidadRfid1)
  }
}

function cambiarFiltro(evento: Event) {
  const valor = (evento.target as HTMLSelectElement).value
  if (['TODAS', 'ACTIVA', 'CANCELADA'].includes(valor)) {
    emit('cambiarEstado', valor as FiltroTarjetasRfid1)
  }
}

function cambiarBusqueda(evento: Event) {
  emit('cambiarBusqueda', (evento.target as HTMLInputElement).value)
}

function formatoFecha(valor: string) {
  const fecha = new Date(valor)
  return Number.isFinite(fecha.getTime())
    ? new Intl.DateTimeFormat('es-MX', { dateStyle: 'medium', timeStyle: 'short' }).format(fecha)
    : '—'
}
</script>

<template>
  <section
    class="panel-directorio-rfid"
    aria-labelledby="titulo-directorio-rfid"
    :aria-busy="props.cargando"
  >
    <div class="cabecera-directorio-rfid">
      <div>
        <h2 id="titulo-directorio-rfid">Tarjetas registradas</h2>
        <p v-if="props.cargando">{{ props.tarjetas.length ? 'Actualizando…' : 'Cargando…' }}</p>
        <p v-else-if="props.error">No se pudo obtener el total.</p>
        <p v-else-if="hayFiltros">
          {{ props.total }} {{ props.total === 1 ? 'resultado' : 'resultados' }}
        </p>
        <p v-else>{{ props.total }} {{ props.total === 1 ? 'tarjeta' : 'tarjetas' }} en total</p>
      </div>
      <UButton
        color="neutral"
        variant="outline"
        icon="i-lucide-refresh-cw"
        :loading="props.cargando"
        :disabled="props.cargando"
        @click="emit('actualizar')"
        >Actualizar</UButton
      >
    </div>

    <div class="filtros-directorio-rfid">
      <div class="campo-filtro-rfid campo-busqueda-rfid">
        <label for="tarjetas-busqueda">
          {{ props.mostrarUid ? 'Buscar por nombre, código o UID' : 'Buscar por nombre o código' }}
        </label>
        <div class="entrada-busqueda-rfid">
          <input
            id="tarjetas-busqueda"
            type="search"
            autocomplete="off"
            maxlength="100"
            :placeholder="props.mostrarUid ? 'Nombre, código o UID' : 'Nombre o código'"
            :value="props.busqueda"
            @input="cambiarBusqueda"
          />
          <button
            v-if="props.busqueda"
            type="button"
            class="limpiar-busqueda-rfid"
            aria-label="Limpiar búsqueda"
            @click="emit('cambiarBusqueda', '')"
          >
            <UIcon name="i-lucide-x" aria-hidden="true" />
          </button>
        </div>
      </div>
      <div class="campo-filtro-rfid">
        <label for="tarjetas-persona">Persona</label>
        <select id="tarjetas-persona" :value="props.tipoEntidad" @change="cambiarTipo">
          <option value="MIXTO">Todos</option>
          <option value="CLIENTE">Clientes</option>
          <option value="EMPLEADO">Empleados</option>
        </select>
      </div>
      <div class="campo-filtro-rfid">
        <label for="tarjetas-estado">Estado</label>
        <select id="tarjetas-estado" :value="props.estado" @change="cambiarFiltro">
          <option value="TODAS">Todos</option>
          <option value="ACTIVA">Activas</option>
          <option value="CANCELADA">Inactivas</option>
        </select>
      </div>
    </div>

    <div v-if="props.error" class="error-directorio-rfid">
      <p class="mensaje-error-rfid" role="alert">{{ props.error }}</p>
      <p v-if="props.tarjetas.length" class="estado-directorio-anterior-rfid">
        Se muestran los resultados anteriores.
      </p>
      <UButton
        color="neutral"
        variant="outline"
        :disabled="props.cargando"
        @click="emit('actualizar')"
      >
        Reintentar
      </UButton>
    </div>
    <p
      v-else-if="props.cargando && !props.tarjetas.length"
      class="estado-directorio-rfid"
      role="status"
    >
      Cargando tarjetas…
    </p>
    <p v-else-if="!props.tarjetas.length" class="estado-directorio-rfid" role="status">
      {{
        hayFiltros
          ? 'No encontramos tarjetas con esos filtros.'
          : 'Aún no hay tarjetas registradas.'
      }}
    </p>
    <p v-else-if="props.cargando" class="actualizando-directorio-rfid" role="status">
      Actualizando tarjetas…
    </p>

    <div v-if="props.tarjetas.length" class="tabla-directorio-rfid__marco">
      <table class="tabla-directorio-rfid">
        <thead>
          <tr>
            <th v-if="props.mostrarUid" scope="col">UID</th>
            <th scope="col">Persona</th>
            <th scope="col">Estado</th>
            <th scope="col">Fecha de asociación</th>
            <th scope="col"><span class="solo-lector">Acciones</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="tarjeta in props.tarjetas" :key="tarjeta.asociacionId">
            <td v-if="props.mostrarUid && tarjeta.uid !== null" data-etiqueta="UID">
              <code>{{ tarjeta.uid }}</code>
            </td>
            <td data-etiqueta="Persona">
              <div class="persona-tarjeta-rfid">
                <strong>{{ tarjeta.nombreCompleto }}</strong>
                <span class="codigo-persona-rfid">
                  {{ tarjeta.tipoEntidad === 'CLIENTE' ? 'Cliente' : 'Empleado' }} ·
                  {{ tarjeta.codigoPersona }}
                </span>
              </div>
            </td>
            <td data-etiqueta="Estado">
              <UBadge
                :color="tarjeta.estado === 'ACTIVA' ? 'success' : 'neutral'"
                variant="subtle"
                >{{ tarjeta.estado === 'ACTIVA' ? 'Activa' : 'Inactiva' }}</UBadge
              >
            </td>
            <td data-etiqueta="Fecha de asociación">{{ formatoFecha(tarjeta.asociadaEn) }}</td>
            <td data-etiqueta="Acciones">
              <UButton
                :id="`rfid-detalle-${tarjeta.asociacionId}`"
                size="sm"
                color="neutral"
                variant="outline"
                :aria-label="`Ver detalles de ${tarjeta.nombreCompleto}`"
                @click="emit('detalle', tarjeta)"
                >Ver detalles</UButton
              >
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <footer v-if="props.totalPaginas > 1" class="paginacion-directorio-rfid">
      <span>{{ primerResultado }}–{{ ultimoResultado }} de {{ props.total }} tarjetas</span>
      <nav class="controles-paginacion-rfid" aria-label="Páginas de tarjetas">
        <UButton
          icon="i-lucide-chevron-left"
          color="neutral"
          variant="outline"
          aria-label="Página anterior"
          :disabled="props.pagina <= 1 || props.cargando"
          @click="emit('cambiarPagina', props.pagina - 1)"
        />
        <UButton
          v-for="numero in paginasVisibles"
          :key="numero"
          :color="numero === props.pagina ? 'primary' : 'neutral'"
          :variant="numero === props.pagina ? 'solid' : 'outline'"
          :aria-label="`Página ${numero}`"
          :aria-current="numero === props.pagina ? 'page' : undefined"
          :disabled="props.cargando"
          @click="emit('cambiarPagina', numero)"
        >
          {{ numero }}
        </UButton>
        <UButton
          icon="i-lucide-chevron-right"
          color="neutral"
          variant="outline"
          aria-label="Página siguiente"
          :disabled="props.pagina >= props.totalPaginas || props.cargando"
          @click="emit('cambiarPagina', props.pagina + 1)"
        />
      </nav>
    </footer>
  </section>
</template>

<style scoped>
.panel-directorio-rfid {
  display: grid;
  gap: 16px;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  padding: clamp(16px, 3vw, 24px);
  background: var(--app-surface);
  box-shadow: 0 8px 28px rgb(0 0 0 / 4%);
}
.cabecera-directorio-rfid,
.paginacion-directorio-rfid {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.cabecera-directorio-rfid h2,
.cabecera-directorio-rfid p {
  margin: 0;
}
.cabecera-directorio-rfid p {
  margin-top: 4px;
  color: var(--app-muted);
  font-size: 0.85rem;
}
.cabecera-directorio-rfid h2 {
  font-size: 1rem;
  font-weight: 600;
}
.filtros-directorio-rfid {
  display: grid;
  grid-template-columns: minmax(14rem, 1fr) minmax(9rem, 12rem) minmax(9rem, 12rem);
  align-items: start;
  gap: 14px;
}
.campo-filtro-rfid {
  display: grid;
  min-width: 0;
  gap: 6px;
}
.campo-filtro-rfid label {
  font-size: 0.86rem;
  font-weight: 600;
  line-height: 1.25;
}
.campo-filtro-rfid input,
.campo-filtro-rfid select {
  width: 100%;
  min-height: 40px;
  border: 1px solid var(--app-border);
  border-radius: 9px;
  padding: 7px 10px;
  background: var(--app-surface);
  color: var(--app-foreground);
}
.campo-filtro-rfid input:focus-visible,
.campo-filtro-rfid select:focus-visible,
.limpiar-busqueda-rfid:focus-visible {
  outline: 2px solid var(--ui-primary);
  outline-offset: 2px;
}
.entrada-busqueda-rfid {
  position: relative;
}
.entrada-busqueda-rfid input {
  padding-right: 38px;
}
.entrada-busqueda-rfid input::-webkit-search-cancel-button {
  display: none;
}
.limpiar-busqueda-rfid {
  position: absolute;
  top: 50%;
  right: 8px;
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--app-muted);
  cursor: pointer;
  transform: translateY(-50%);
}
.limpiar-busqueda-rfid:hover {
  background: var(--app-hover, rgb(0 0 0 / 6%));
}
.error-directorio-rfid {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}
.estado-directorio-rfid,
.mensaje-error-rfid,
.estado-directorio-anterior-rfid,
.actualizando-directorio-rfid {
  margin: 0;
  color: var(--app-muted);
}
.estado-directorio-rfid {
  padding: 16px 0;
}
.actualizando-directorio-rfid {
  font-size: 0.85rem;
}
.mensaje-error-rfid {
  color: var(--app-error);
}
.tabla-directorio-rfid__marco {
  width: 100%;
  overflow-x: auto;
}
.tabla-directorio-rfid {
  width: 100%;
  min-width: 640px;
  border-collapse: collapse;
  text-align: left;
}
.tabla-directorio-rfid th,
.tabla-directorio-rfid td {
  border-bottom: 1px solid var(--app-border);
  padding: 10px;
  vertical-align: middle;
}
.tabla-directorio-rfid th {
  color: var(--app-muted);
  font-size: 0.78rem;
  font-weight: 600;
}
.tabla-directorio-rfid td code {
  font-variant-numeric: tabular-nums;
}
.persona-tarjeta-rfid strong,
.codigo-persona-rfid {
  display: block;
}
.codigo-persona-rfid {
  margin-top: 3px;
  color: var(--app-muted);
  font-size: 0.8rem;
}
.solo-lector {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}
.paginacion-directorio-rfid > span {
  color: var(--app-muted);
  font-size: 0.84rem;
}
.controles-paginacion-rfid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
@media (max-width: 44rem) {
  .cabecera-directorio-rfid,
  .paginacion-directorio-rfid {
    flex-wrap: wrap;
  }
  .filtros-directorio-rfid {
    grid-template-columns: minmax(0, 1fr);
  }
  .campo-busqueda-rfid {
    grid-column: auto;
  }
  .tabla-directorio-rfid__marco {
    overflow: visible;
  }
  .tabla-directorio-rfid,
  .tabla-directorio-rfid tbody {
    display: block;
    min-width: 0;
  }
  .tabla-directorio-rfid thead {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
  }
  .tabla-directorio-rfid tr {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 4px 12px;
    margin-bottom: 10px;
    border: 1px solid var(--app-border);
    border-radius: 10px;
    padding: 10px 12px;
  }
  .tabla-directorio-rfid td {
    display: block;
    min-width: 0;
    border: 0;
    padding: 4px 0;
    overflow-wrap: anywhere;
  }
  .tabla-directorio-rfid td::before {
    display: block;
    margin-bottom: 3px;
    color: var(--app-muted);
    content: attr(data-etiqueta);
    font-size: 0.75rem;
    font-weight: 600;
  }
  .tabla-directorio-rfid td[data-etiqueta='Persona'],
  .tabla-directorio-rfid td[data-etiqueta='Acciones'] {
    grid-column: 1 / -1;
  }
  .tabla-directorio-rfid td[data-etiqueta='Acciones']::before {
    display: none;
  }
}
</style>
