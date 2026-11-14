<script setup lang="ts">
import type { ClienteResumenAdministracion } from '~/types/cliente-admin'

const props = defineProps<{ clientes: ClienteResumenAdministracion[]; ocupado?: boolean }>()
const emit = defineEmits<{
  verDetalles: [cliente: ClienteResumenAdministracion]
}>()

const columnas = [
  { accessorKey: 'codigo', header: 'Código' },
  { accessorKey: 'nombreCompleto', header: 'Nombre completo' },
  { id: 'estado', accessorKey: 'estadoMembresia', header: 'Estado de membresía' },
  { id: 'acciones', header: 'Acciones' },
]

const etiquetas: Record<ClienteResumenAdministracion['estadoMembresia'], string> = {
  SIN_MEMBRESIA: 'Sin membresía',
  PENDIENTE: 'Pendiente',
  ACTIVA: 'Activa',
  PAGO_VENCIDO: 'Pago vencido',
  CANCELADA: 'Cancelada',
  INACTIVA: 'Inactiva',
}

function claseEstado(estado: ClienteResumenAdministracion['estadoMembresia']) {
  return `estado-cliente--${estado.toLowerCase().replaceAll('_', '-')}`
}
</script>

<template>
  <div class="tabla-clientes-contenedor" role="region" aria-label="Lista de clientes" tabindex="0">
    <UTable :data="props.clientes" :columns="columnas" class="tabla-clientes">
      <template #estado-cell="{ row }">
        <span class="estado-cliente" :class="claseEstado(row.original.estadoMembresia)">
          <span class="punto-estado" aria-hidden="true" />
          {{ etiquetas[row.original.estadoMembresia] }}
        </span>
      </template>
      <template #acciones-cell="{ row }">
        <div class="acciones-cliente">
          <UButton
            :id="`cliente-detalle-${row.original.codigo}`"
            color="neutral"
            variant="outline"
            size="sm"
            :disabled="props.ocupado"
            :aria-label="`Ver detalles de ${row.original.nombreCompleto}`"
            @click="emit('verDetalles', row.original)"
          >
            Ver detalles
          </UButton>
        </div>
      </template>
    </UTable>
  </div>
</template>

<style scoped>
.tabla-clientes-contenedor {
  overflow-x: auto;
  border: 1px solid var(--app-border);
  border-radius: 14px;
  background: var(--app-surface);
}
.tabla-clientes {
  min-width: 44rem;
}
.acciones-cliente {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.estado-cliente {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 0.8rem;
  font-weight: 700;
}
.estado-cliente--sin-membresia,
.estado-cliente--pendiente,
.estado-cliente--inactiva {
  background: #f0edf2;
  color: #625b68;
}
.estado-cliente--activa {
  background: #e7f5ed;
  color: #176b42;
}
.estado-cliente--pago-vencido {
  background: #fff2df;
  color: #8a4b08;
}
.estado-cliente--cancelada {
  background: #fbe9e8;
  color: #9f3833;
}
.punto-estado {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}
</style>
