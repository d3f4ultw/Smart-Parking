<script setup lang="ts">
import { computed, nextTick, watch } from 'vue'
import type { CandidatoPersonaRfid1, FiltroTipoEntidadRfid1 } from '~/types/rfid1'

const props = defineProps<{
  tipoEntidad: FiltroTipoEntidadRfid1
  tiposEntidadDisponibles: FiltroTipoEntidadRfid1[]
  busqueda: string
  candidatos: CandidatoPersonaRfid1[]
  seleccionada: CandidatoPersonaRfid1 | null
  pendientes: boolean
  error: string
}>()

const emit = defineEmits<{
  'update:tipoEntidad': [valor: FiltroTipoEntidadRfid1]
  'update:busqueda': [valor: string]
  seleccionar: [candidato: CandidatoPersonaRfid1]
  cambiarPersona: []
  cerrar: []
}>()

const resaltado = ref(0)
const sugerenciasAbiertas = ref(true)
const busquedaActiva = computed(() => Array.from(props.busqueda.trim()).length >= 2)
const mostrarOpciones = computed(() => busquedaActiva.value && sugerenciasAbiertas.value)
const etiquetasTipo: Record<FiltroTipoEntidadRfid1, string> = {
  CLIENTE: 'CLIENTE',
  EMPLEADO: 'EMPLEADO',
  MIXTO: 'Mixto',
}

watch(
  () => props.candidatos.length,
  () => (resaltado.value = 0),
)

function idOpcion(candidato: CandidatoPersonaRfid1) {
  return `rfid-persona-${candidato.tipoEntidad}-${candidato.codigoPersona}`
}

const idOpcionActiva = computed(() => {
  const candidato = props.candidatos[resaltado.value]
  return candidato ? idOpcion(candidato) : undefined
})

/** Traduce motivos de API a texto claro; `CLIENTE_SIN_MEMBRESIA` explica la ausencia de membresía. */
function motivoNoElegible(candidato: CandidatoPersonaRfid1) {
  const motivo = candidato.motivoNoElegible?.trim()
  if (motivo === 'CLIENTE_SIN_MEMBRESIA') return 'Sin membresía; no se puede asociar una tarjeta.'
  if (motivo === 'PERSONA_CON_TARJETA') return 'Ya tiene una tarjeta activa.'
  if (motivo && !/^[A-Z0-9_]+$/.test(motivo)) return motivo
  return 'No se puede asociar una tarjeta a esta persona.'
}

function actualizarBusqueda(evento: Event) {
  sugerenciasAbiertas.value = true
  resaltado.value = 0
  emit('update:busqueda', (evento.target as HTMLInputElement).value)
}

function cambiarPersona() {
  emit('cambiarPersona')
  if (!import.meta.client) return
  void nextTick(() => document.getElementById('rfid-busqueda-persona')?.focus())
}

function elegirOpcion(evento: KeyboardEvent) {
  if (evento.key === 'Escape') {
    if (mostrarOpciones.value) {
      evento.preventDefault()
      evento.stopPropagation()
      sugerenciasAbiertas.value = false
      return
    }
    emit('cerrar')
    return
  }
  if (evento.key === 'ArrowDown' && busquedaActiva.value && !mostrarOpciones.value) {
    evento.preventDefault()
    sugerenciasAbiertas.value = true
  }
  if (evento.key === 'ArrowDown' && props.candidatos.length) {
    evento.preventDefault()
    resaltado.value = Math.min(resaltado.value + 1, props.candidatos.length - 1)
  }
  if (evento.key === 'ArrowUp' && props.candidatos.length) {
    evento.preventDefault()
    resaltado.value = Math.max(0, resaltado.value - 1)
  }
  if (evento.key === 'Enter') {
    if (!mostrarOpciones.value) return
    evento.preventDefault()
    const candidato = props.candidatos[resaltado.value]
    if (candidato && candidato.elegible) emit('seleccionar', candidato)
  }
}
</script>

<template>
  <div class="selector-persona-rfid">
    <fieldset class="selector-tipo-rfid">
      <legend>Tipo de persona</legend>
      <div class="selector-tipo-rfid__opciones">
        <UButton
          v-for="tipo in tiposEntidadDisponibles"
          :key="tipo"
          type="button"
          :color="tipoEntidad === tipo ? 'primary' : 'neutral'"
          :variant="tipoEntidad === tipo ? 'solid' : 'outline'"
          :aria-pressed="tipoEntidad === tipo"
          @click="emit('update:tipoEntidad', tipo)"
        >
          {{ etiquetasTipo[tipo] }}
        </UButton>
      </div>
    </fieldset>

    <div class="campo-busqueda-rfid">
      <label for="rfid-busqueda-persona">Buscar</label>
      <input
        id="rfid-busqueda-persona"
        class="campo-busqueda-rfid__entrada"
        type="search"
        :value="busqueda"
        placeholder="Nombre o código"
        autocomplete="off"
        role="combobox"
        aria-autocomplete="list"
        aria-controls="rfid-resultados-personas"
        :aria-expanded="mostrarOpciones"
        :aria-activedescendant="mostrarOpciones ? idOpcionActiva : undefined"
        @input="actualizarBusqueda"
        @keydown="elegirOpcion"
      />
      <ul
        v-if="mostrarOpciones"
        id="rfid-resultados-personas"
        class="resultados-personas-rfid"
        role="listbox"
        aria-label="Resultados de personas"
      >
        <li v-if="pendientes" class="resultados-personas-rfid__mensaje" role="status">Buscando…</li>
        <li v-else-if="error" class="resultados-personas-rfid__mensaje" role="alert">
          {{ error }}
        </li>
        <li v-else-if="!candidatos.length" class="resultados-personas-rfid__mensaje">
          Sin resultados.
        </li>
        <li
          v-for="(candidato, indice) in candidatos"
          :key="`${candidato.tipoEntidad}-${candidato.codigoPersona}`"
        >
          <button
            :id="idOpcion(candidato)"
            class="opcion-persona-rfid"
            :class="{ 'opcion-persona-rfid--resaltada': indice === resaltado }"
            type="button"
            role="option"
            :aria-selected="
              seleccionada?.tipoEntidad === candidato.tipoEntidad &&
              seleccionada?.codigoPersona === candidato.codigoPersona
            "
            :aria-disabled="!candidato.elegible"
            :disabled="!candidato.elegible"
            @mouseenter="resaltado = indice"
            @click="candidato.elegible && emit('seleccionar', candidato)"
          >
            <span class="opcion-persona-rfid__identidad">
              <strong>{{ candidato.nombreCompleto }}</strong>
              <span>{{ candidato.tipoEntidad }} · {{ candidato.codigoPersona }}</span>
              <span>Estado: {{ candidato.estadoAdministrativo }}</span>
              <span v-if="!candidato.elegible" class="opcion-persona-rfid__motivo">
                {{ motivoNoElegible(candidato) }}
              </span>
            </span>
            <span
              class="opcion-persona-rfid__elegibilidad"
              :class="candidato.elegible ? 'es-elegible' : 'no-es-elegible'"
            >
              {{ candidato.elegible ? 'Disponible' : 'No disponible' }}
            </span>
          </button>
        </li>
      </ul>
    </div>

    <section
      v-if="seleccionada"
      class="persona-seleccionada-rfid"
      aria-label="Persona seleccionada"
    >
      <span class="persona-seleccionada-rfid__tipo"
        >{{ seleccionada.tipoEntidad }} · {{ seleccionada.codigoPersona }}</span
      >
      <strong>{{ seleccionada.nombreCompleto }}</strong>
      <UButton
        type="button"
        color="neutral"
        variant="outline"
        class="persona-seleccionada-rfid__cambiar"
        @click="cambiarPersona"
      >
        Cambiar persona
      </UButton>
    </section>
    <p v-else class="ayuda-busqueda-rfid">Escribe al menos 2 caracteres para buscar.</p>
  </div>
</template>

<style scoped>
.selector-persona-rfid {
  display: grid;
  gap: 16px;
}
.selector-tipo-rfid {
  display: grid;
  gap: 8px;
  margin: 0;
  border: 0;
  padding: 0;
}
.selector-tipo-rfid legend,
.campo-busqueda-rfid label {
  margin-bottom: 8px;
  color: var(--app-foreground);
  font-size: 0.9rem;
  font-weight: 600;
}
.selector-tipo-rfid__opciones {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.selector-tipo-rfid__opciones :deep(button) {
  min-height: 40px;
}
.campo-busqueda-rfid {
  position: relative;
  display: grid;
}
.campo-busqueda-rfid__entrada {
  min-height: 44px;
  width: 100%;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  padding: 8px 12px;
  background: var(--app-surface);
  color: var(--app-foreground);
}
.campo-busqueda-rfid__entrada:focus-visible {
  outline: 2px solid var(--app-focus, var(--app-accent));
  outline-offset: 2px;
}
.resultados-personas-rfid {
  position: absolute;
  z-index: 20;
  top: calc(100% + 6px);
  right: 0;
  left: 0;
  max-height: 220px;
  overflow-y: auto;
  margin: 0;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  padding: 4px;
  background: var(--app-surface);
  box-shadow: 0 10px 28px rgb(0 0 0 / 14%);
  list-style: none;
}
.opcion-persona-rfid {
  display: grid;
  min-height: 56px;
  width: 100%;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px 12px;
  border: 0;
  border-radius: 7px;
  padding: 8px 10px;
  background: transparent;
  color: var(--app-foreground);
  text-align: left;
}
.opcion-persona-rfid:not(:disabled):hover,
.opcion-persona-rfid--resaltada:not(:disabled) {
  background: var(--app-surface-hover);
}
.opcion-persona-rfid:disabled {
  cursor: not-allowed;
  opacity: 0.72;
}
.opcion-persona-rfid__identidad,
.persona-seleccionada-rfid {
  display: grid;
  gap: 4px;
}
.opcion-persona-rfid__identidad {
  min-width: 0;
}
.opcion-persona-rfid__identidad strong {
  overflow-wrap: anywhere;
}
.opcion-persona-rfid__identidad > span,
.persona-seleccionada-rfid__tipo,
.ayuda-busqueda-rfid {
  color: var(--app-muted);
  font-size: 0.82rem;
}
.opcion-persona-rfid__elegibilidad {
  flex: 0 0 auto;
  font-size: 0.78rem;
}
.es-elegible {
  color: var(--app-success);
}
.no-es-elegible {
  color: var(--app-error);
}
.opcion-persona-rfid__motivo {
  color: var(--app-error) !important;
}
.resultados-personas-rfid__mensaje,
.ayuda-busqueda-rfid {
  margin: 0;
  padding: 10px;
  color: var(--app-muted);
}
.persona-seleccionada-rfid {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 5px 12px;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  padding: 12px 14px;
  background: var(--app-surface);
}
.persona-seleccionada-rfid__tipo,
.persona-seleccionada-rfid > strong {
  grid-column: 1;
}
.persona-seleccionada-rfid__cambiar {
  grid-column: 2;
  grid-row: 1 / span 2;
}
@media (max-width: 38rem) {
  .opcion-persona-rfid {
    grid-template-columns: minmax(0, 1fr);
    align-items: start;
  }
  .opcion-persona-rfid__elegibilidad {
    grid-row: 1;
    justify-self: start;
  }
  .persona-seleccionada-rfid {
    grid-template-columns: minmax(0, 1fr);
  }
  .persona-seleccionada-rfid__cambiar {
    grid-column: 1;
    grid-row: auto;
    justify-self: start;
  }
}
</style>
