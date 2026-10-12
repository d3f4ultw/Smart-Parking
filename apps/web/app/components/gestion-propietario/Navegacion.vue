<script setup lang="ts">
import {
  ACCIONES_GESTION_PROPIETARIO,
  type AccionGestionPropietario,
} from '~/utils/gestion-propietario'

defineProps<{ seleccionada: AccionGestionPropietario }>()
const emit = defineEmits<{ seleccionar: [accion: AccionGestionPropietario] }>()
</script>

<template>
  <nav class="management-navigation" aria-label="Acciones de gestión de dueño">
    <button
      v-for="accion in ACCIONES_GESTION_PROPIETARIO"
      :key="accion.id"
      class="management-navigation-item"
      :class="{
        'is-active': seleccionada === accion.id,
        'is-disabled': !accion.disponible,
      }"
      type="button"
      :disabled="!accion.disponible"
      :aria-current="seleccionada === accion.id ? 'page' : undefined"
      @click="emit('seleccionar', accion.id)"
    >
      <span>{{ accion.nombre }}</span>
      <small v-if="!accion.disponible">Fase 3</small>
    </button>
  </nav>
</template>

<style scoped>
.management-navigation {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
  gap: 0.65rem;
}

.management-navigation-item {
  display: flex;
  min-height: 3.25rem;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  padding: 0.75rem 1rem;
  color: #463753;
  background: #ffffff;
  border: 1px solid #ded6e7;
  border-radius: 0.8rem;
  font: inherit;
  font-weight: 650;
  text-align: left;
  cursor: pointer;
}

.management-navigation-item:hover:not(:disabled),
.management-navigation-item:focus-visible {
  border-color: #80649b;
  outline: none;
}

.management-navigation-item.is-active {
  color: #ffffff;
  background: #523775;
  border-color: #523775;
}

.management-navigation-item:disabled {
  color: #827c88;
  background: #f2f0f4;
  cursor: not-allowed;
}

.management-navigation-item small {
  color: inherit;
  font-size: 0.72rem;
  font-weight: 550;
}
</style>
