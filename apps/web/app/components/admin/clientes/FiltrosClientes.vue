<script setup lang="ts">
import type { EstadoFiltroClientes } from '~/types/cliente-admin'

const estado = defineModel<EstadoFiltroClientes>({ required: true })
const props = defineProps<{ deshabilitado?: boolean }>()

const opciones: Array<{ label: string; value: EstadoFiltroClientes }> = [
  { label: 'Todos', value: 'todos' },
  { label: 'Sin membresía', value: 'sin-membresia' },
  { label: 'Activa', value: 'activa' },
  { label: 'Cancelada', value: 'cancelada' },
]
</script>

<template>
  <UFormField label="Estado de membresía" name="estadoMembresia">
    <USelect
      v-model="estado"
      :items="opciones"
      :disabled="props.deshabilitado"
      :ui="{ content: 'min-w-40' }"
    />
  </UFormField>
</template>
