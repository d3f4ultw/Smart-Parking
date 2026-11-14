<script setup lang="ts">
import type { FiltroEstadoOperador } from '~/types/operador'

const props = defineProps<{
  busqueda: string
  estado: FiltroEstadoOperador
  errorBusqueda?: string
}>()

const emit = defineEmits<{
  'update:busqueda': [valor: string]
  'update:estado': [valor: FiltroEstadoOperador]
}>()

const opcionesEstado = [
  { label: 'Todos', value: 'TODOS' },
  { label: 'Por activar', value: 'PENDIENTE' },
  { label: 'Activas', value: 'ACTIVA' },
  { label: 'Desactivadas', value: 'INACTIVA' },
] satisfies { label: string; value: FiltroEstadoOperador }[]
</script>

<template>
  <div class="filtros-operadores" role="group" aria-label="Filtros de operadores">
    <UFormField
      label="Buscar por nombre o apellido"
      name="busqueda-operadores"
      :error="props.errorBusqueda"
      class="campo-filtro"
    >
      <UInput
        id="busqueda-operadores"
        class="w-full"
        :model-value="props.busqueda"
        type="search"
        maxlength="254"
        autocomplete="off"
        placeholder="Nombre o apellido"
        :color="props.errorBusqueda ? 'error' : 'neutral'"
        :aria-invalid="Boolean(props.errorBusqueda)"
        @update:model-value="emit('update:busqueda', String($event ?? ''))"
      />
    </UFormField>
    <UFormField label="Estado de cuenta" name="estado-operadores" class="campo-filtro">
      <select
        id="estado-operadores"
        :value="props.estado"
        class="selector-estado w-full"
        @change="
          emit('update:estado', ($event.target as HTMLSelectElement).value as FiltroEstadoOperador)
        "
      >
        <option v-for="opcion in opcionesEstado" :key="opcion.value" :value="opcion.value">
          {{ opcion.label }}
        </option>
      </select>
    </UFormField>
  </div>
</template>

<style scoped>
.filtros-operadores {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(11rem, 1fr);
  gap: 16px;
  align-items: end;
}
.campo-filtro {
  min-width: 0;
}
.filtros-operadores :deep(input),
.selector-estado {
  width: 100%;
}
.selector-estado {
  width: 100%;
  min-height: 2.625rem;
  border: 1px solid var(--app-border);
  border-radius: 0.5rem;
  padding: 0.5rem 0.75rem;
  background-color: var(--app-surface);
  color: var(--app-foreground);
  font: inherit;
  cursor: pointer;
}
.selector-estado:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: 2px;
}
.selector-estado:disabled {
  cursor: not-allowed;
  opacity: 0.75;
}
@media (max-width: 42rem) {
  .filtros-operadores {
    grid-template-columns: 1fr;
  }
}
</style>
