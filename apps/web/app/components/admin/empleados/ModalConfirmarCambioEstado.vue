<script setup lang="ts">
import { nextTick, watch } from 'vue'
import type { Empleado } from '~/types/empleado'

const abierta = defineModel<boolean>('open', { required: true })
const props = defineProps<{ empleado: Empleado | null; ocupado?: boolean; error?: string }>()
const emit = defineEmits<{ confirmar: [] }>()
const ultimoIdEmpleado = ref<string | null>(props.empleado?.idTexto ?? null)
const esDesactivacion = computed(() => props.empleado?.estado === 'ACTIVO')
const uiModal = {
  overlay: 'bg-black/55',
  content: 'max-w-md rounded-2xl border border-[var(--app-border)] bg-white shadow-xl',
  header: 'px-5 py-4 sm:px-6',
  title: 'text-lg font-semibold',
  description: 'text-sm text-[var(--app-muted)]',
  body: 'px-5 pb-5 pt-0 sm:px-6 sm:pb-6',
}

watch(
  () => props.empleado?.idTexto,
  (id) => {
    if (id !== undefined) ultimoIdEmpleado.value = id
  },
)

const accion = computed(() => (esDesactivacion.value ? 'Desactivar empleado' : 'Activar empleado'))
const nombre = computed(() =>
  props.empleado
    ? [props.empleado.nombres, props.empleado.primerApellido, props.empleado.segundoApellido]
        .filter(Boolean)
        .join(' ')
    : '',
)
const confirmacion = computed(() => {
  if (!props.empleado) return ''
  return esDesactivacion.value
    ? `¿Desactivar a ${nombre.value}?`
    : `¿Quieres activar el registro de ${nombre.value}?`
})

async function restaurarFoco(evento: Event) {
  evento.preventDefault()
  await nextTick()
  const idEmpleado = ultimoIdEmpleado.value
  if (idEmpleado !== null) document.getElementById(`empleado-estado-${idEmpleado}`)?.focus()
}
</script>

<template>
  <UModal
    v-model:open="abierta"
    :title="accion"
    :description="confirmacion"
    :ui="esDesactivacion ? uiModal : undefined"
    :dismissible="!props.ocupado"
    :close="!props.ocupado"
    :content="{ onCloseAutoFocus: restaurarFoco }"
  >
    <template #body>
      <div
        class="contenido-confirmacion"
        :class="{ 'contenido-confirmacion--desactivacion': esDesactivacion }"
      >
        <p v-if="esDesactivacion">El empleado quedará inactivo.</p>
        <p v-if="esDesactivacion && props.empleado?.operador">
          También se desactivará su acceso como operador.
        </p>
        <p v-if="props.error" class="error-cambio" role="alert">{{ props.error }}</p>
        <footer class="acciones-modal-empleado">
          <UButton
            type="button"
            color="neutral"
            variant="outline"
            :disabled="props.ocupado"
            @click="abierta = false"
            >Cancelar</UButton
          >
          <UButton
            type="button"
            :color="esDesactivacion ? 'error' : 'primary'"
            :loading="props.ocupado"
            :disabled="!props.empleado || props.ocupado"
            @click="emit('confirmar')"
          >
            {{ esDesactivacion ? 'Desactivar' : accion }}
          </UButton>
        </footer>
      </div>
    </template>
  </UModal>
</template>

<style scoped>
.contenido-confirmacion {
  display: grid;
  gap: 16px;
}
.contenido-confirmacion--desactivacion {
  gap: 12px;
}
.contenido-confirmacion > p {
  margin: 0;
  color: var(--app-muted);
  line-height: 1.6;
}
.contenido-confirmacion--desactivacion > p {
  line-height: 1.5;
}
.error-cambio {
  color: var(--app-error) !important;
}
.acciones-modal-empleado {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
@media (max-width: 34rem) {
  .acciones-modal-empleado {
    flex-direction: column-reverse;
  }
  .acciones-modal-empleado :deep(button) {
    width: 100%;
    justify-content: center;
  }
}
</style>
