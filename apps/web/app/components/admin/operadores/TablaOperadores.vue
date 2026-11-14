<script setup lang="ts">
import type { EstadoCuentaOperador, EstadoInvitacionOperador, Operador } from '~/types/operador'

const props = defineProps<{
  operadores: Operador[]
}>()
const emit = defineEmits<{
  administrar: [id: string, indice: number]
  conciliar: [id: string, indice: number]
}>()

const columnas = [
  { id: 'nombre', header: 'Nombre completo' },
  { id: 'vinculo', header: 'Empleado' },
  { accessorKey: 'estado', header: 'Cuenta' },
  { id: 'invitacion', header: 'Invitación' },
  { id: 'acciones', header: 'Acciones' },
]

function nombreCompleto(operador: Operador) {
  return [operador.nombres, operador.primerApellido, operador.segundoApellido]
    .filter((parte): parte is string => Boolean(parte))
    .join(' ')
}

function textoCuenta(estado: EstadoCuentaOperador) {
  return { PENDIENTE: 'Por activar', ACTIVA: 'Activa', INACTIVA: 'Desactivada' }[estado]
}

function colorCuenta(estado: EstadoCuentaOperador) {
  return { PENDIENTE: 'warning', ACTIVA: 'success', INACTIVA: 'neutral' }[estado] as
    | 'warning'
    | 'success'
    | 'neutral'
}

function textoInvitacion(estado: EstadoInvitacionOperador) {
  return {
    ENVIANDO: 'Enviando',
    ENVIADO: 'Enviado',
    FALLIDO: 'No se pudo enviar',
    DESCONOCIDO: 'No sabemos si se envió',
    DESHABILITADO: 'No se enviará',
    EXPIRADA: 'Venció',
    CONSUMIDA: 'Usada',
  }[estado]
}

function colorInvitacion(
  estado: EstadoInvitacionOperador,
): 'success' | 'error' | 'primary' | 'warning' {
  if (estado === 'ENVIADO' || estado === 'CONSUMIDA') return 'success'
  if (estado === 'FALLIDO' || estado === 'EXPIRADA') return 'error'
  if (estado === 'ENVIANDO') return 'primary'
  return 'warning'
}
</script>

<template>
  <div
    class="tabla-operadores-contenedor"
    role="region"
    aria-label="Tabla de operadores; desplázate horizontalmente para ver todas las columnas"
    tabindex="0"
  >
    <UTable
      :data="props.operadores"
      :columns="columnas"
      :get-row-id="(_operador, indice) => String(indice)"
      class="tabla-operadores"
    >
      <template #nombre-cell="{ row }">
        <span class="nombre-operador">{{ nombreCompleto(row.original) }}</span>
      </template>
      <template #vinculo-cell="{ row }">
        <span>
          {{ row.original.estadoConciliacion === 'VINCULADO' ? 'Vinculado' : 'Legado sin vínculo' }}
        </span>
      </template>
      <template #estado-cell="{ row }">
        <UBadge :color="colorCuenta(row.original.estado)" variant="subtle">
          {{ textoCuenta(row.original.estado) }}
        </UBadge>
      </template>
      <template #invitacion-cell="{ row }">
        <UBadge :color="colorInvitacion(row.original.estadoInvitacion)" variant="subtle">
          {{ textoInvitacion(row.original.estadoInvitacion) }}
        </UBadge>
      </template>
      <template #acciones-cell="{ row }">
        <div class="acciones-operador">
          <UButton
            :id="`operador-administrar-${row.index}`"
            color="neutral"
            variant="outline"
            size="sm"
            icon="i-lucide-eye"
            :aria-label="`Ver detalles de ${nombreCompleto(row.original)}`"
            @click="emit('administrar', row.original.id, row.index)"
          >
            Ver detalles
          </UButton>
          <UButton
            :id="`operador-vincular-${row.index}`"
            v-if="row.original.estadoConciliacion === 'LEGADO_SIN_VINCULO'"
            size="sm"
            icon="i-lucide-link"
            :aria-label="`Vincular la cuenta de ${nombreCompleto(row.original)} con un empleado`"
            @click="emit('conciliar', row.original.id, row.index)"
          >
            Vincular empleado
          </UButton>
        </div>
      </template>
    </UTable>
  </div>
</template>

<style scoped>
.tabla-operadores-contenedor {
  overflow-x: auto;
  border: 1px solid var(--app-border);
  border-radius: 14px;
  background: var(--app-surface);
  scrollbar-color: var(--app-border) transparent;
  scrollbar-width: thin;
}
.tabla-operadores-contenedor:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: 2px;
}
.tabla-operadores {
  min-width: 54rem;
}
.nombre-operador {
  color: var(--app-foreground);
  font-weight: 650;
}
.acciones-operador {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
