<script setup lang="ts">
import type { Empleado } from '~/types/empleado'

const props = defineProps<{ empleados: Empleado[]; ocupado?: boolean }>()
const emit = defineEmits<{
  administrar: [empleado: Empleado]
  cambiarEstado: [empleado: Empleado]
}>()

const columnas = [
  { accessorKey: 'codigo', header: 'Número de empleado' },
  { id: 'nombre', header: 'Nombre completo' },
  { accessorKey: 'estado', header: 'Empleado' },
  { id: 'operador', header: 'Cuenta de operador' },
  { id: 'acciones', header: 'Acciones' },
]

function nombreCompleto(empleado: Empleado) {
  return [empleado.nombres, empleado.primerApellido, empleado.segundoApellido]
    .filter((parte): parte is string => Boolean(parte))
    .join(' ')
}

function textoOperador(empleado: Empleado) {
  if (!empleado.operador) return 'Sin cuenta'
  return {
    PENDIENTE: 'Por activar',
    ACTIVA: 'Activa',
    INACTIVA: 'Desactivada',
  }[empleado.operador.estado]
}

function colorOperador(
  empleado: Empleado,
): 'primary' | 'warning' | 'success' | 'neutral' {
  if (!empleado.operador) return 'primary'
  return {
    PENDIENTE: 'warning',
    ACTIVA: 'success',
    INACTIVA: 'neutral',
  }[empleado.operador.estado] as 'warning' | 'success' | 'neutral'
}
</script>

<template>
  <div
    class="tabla-empleados-contenedor"
    role="region"
    aria-label="Lista de empleados"
    tabindex="0"
  >
    <UTable
      :data="props.empleados"
      :columns="columnas"
      :get-row-id="(empleado) => empleado.idTexto"
      class="tabla-empleados"
    >
      <template #nombre-cell="{ row }">
        <span class="nombre-empleado">{{ nombreCompleto(row.original) }}</span>
      </template>
      <template #estado-cell="{ row }">
        <span
          class="estado-empleado"
          :class="`estado-empleado--${row.original.estado.toLowerCase()}`"
        >
          <span class="punto-estado" aria-hidden="true" />
          {{ row.original.estado === 'ACTIVO' ? 'Activo' : 'Inactivo' }}
        </span>
      </template>
      <template #operador-cell="{ row }">
        <UBadge :color="colorOperador(row.original)" variant="subtle">
          {{ textoOperador(row.original) }}
        </UBadge>
      </template>
      <template #acciones-cell="{ row }">
        <div class="acciones-empleado">
          <UButton
            :id="`empleado-administrar-${row.original.idTexto}`"
            color="primary"
            variant="soft"
            size="sm"
            :disabled="props.ocupado"
            :aria-label="`Administrar cuenta de ${nombreCompleto(row.original)}`"
            @click="emit('administrar', row.original)"
          >
            Administrar
          </UButton>
          <UButton
            :id="`empleado-estado-${row.original.idTexto}`"
            :color="row.original.estado === 'ACTIVO' ? 'error' : 'success'"
            variant="outline"
            size="sm"
            :disabled="props.ocupado"
            :aria-label="`${row.original.estado === 'ACTIVO' ? 'Desactivar' : 'Activar'} empleado ${nombreCompleto(row.original)}`"
            @click="emit('cambiarEstado', row.original)"
          >
            {{ row.original.estado === 'ACTIVO' ? 'Desactivar empleado' : 'Activar empleado' }}
          </UButton>
        </div>
      </template>
    </UTable>
  </div>
</template>

<style scoped>
.tabla-empleados-contenedor {
  overflow-x: auto;
  border: 1px solid var(--app-border);
  border-radius: 14px;
  background: var(--app-surface);
}
.tabla-empleados {
  min-width: 56rem;
}
.nombre-empleado {
  color: var(--app-foreground);
  font-weight: 600;
}
.acciones-empleado {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.estado-empleado {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 0.8rem;
  font-weight: 700;
}
.estado-empleado--activo {
  background: #e7f5ed;
  color: #176b42;
}
.estado-empleado--inactivo {
  background: #f0edf2;
  color: #625b68;
}
.punto-estado {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}
</style>
