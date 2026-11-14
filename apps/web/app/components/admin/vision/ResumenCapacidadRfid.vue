<script setup lang="ts">
import type { ResumenCapacidadRfid } from '~/types/acceso'

const props = defineProps<{
  datos: ResumenCapacidadRfid | null
  pendiente: boolean
  mensajeError: string
  desactualizado: boolean
}>()

const emit = defineEmits<{ actualizar: [] }>()

const actualizacionManual = ref(false)
const mostrarDesactualizacion = ref(false)

watch(
  () => props.desactualizado,
  (desactualizado, _anterior, onCleanup) => {
    mostrarDesactualizacion.value = false
    if (!desactualizado || import.meta.server) return

    // Una invalidación breve también marca los datos como desactualizados.
    const temporizador = setTimeout(() => {
      mostrarDesactualizacion.value = true
    }, 500)
    onCleanup(() => clearTimeout(temporizador))
  },
  { immediate: true },
)

watch(
  () => props.pendiente,
  (pendiente) => {
    if (!pendiente) actualizacionManual.value = false
  },
)

function solicitarActualizacion() {
  if (actualizacionManual.value) return
  actualizacionManual.value = true
  if (!props.pendiente) {
    emit('actualizar')
    void nextTick(() => {
      if (!props.pendiente) actualizacionManual.value = false
    })
  }
}
</script>

<template>
  <section class="capacidad-rfid" aria-labelledby="titulo-capacidad-rfid">
    <header class="encabezado-capacidad">
      <div>
        <h2 id="titulo-capacidad-rfid">Capacidad del estacionamiento</h2>
        <p class="descripcion-capacidad">
          Estimación basada en la capacidad configurada y los registros de acceso.
        </p>
      </div>
      <UButton
        type="button"
        color="neutral"
        variant="outline"
        icon="i-lucide-refresh-cw"
        :loading="pendiente && actualizacionManual"
        :disabled="actualizacionManual"
        @click="solicitarActualizacion"
      >
        Actualizar
      </UButton>
    </header>
    <dl class="indicadores-capacidad" aria-label="Resumen de capacidad RFID">
      <div class="indicador-principal">
        <dt>Espacios disponibles estimados</dt>
        <dd>{{ datos?.capacidadDisponible ?? '—' }}</dd>
      </div>
      <div>
        <dt>Vehículos registrados dentro</dt>
        <dd>{{ datos?.vehiculosDentro ?? '—' }}</dd>
      </div>
      <div>
        <dt>Capacidad total</dt>
        <dd>{{ datos?.capacidadTotal ?? '—' }}</dd>
      </div>
    </dl>
    <p v-if="mensajeError" class="aviso-capacidad" role="alert">{{ mensajeError }}</p>
    <p v-else-if="pendiente && !datos" class="aviso-capacidad" role="status">
      Cargando la capacidad…
    </p>
    <p v-else-if="!datos" class="aviso-capacidad" role="status">Capacidad no disponible.</p>
    <p v-else-if="mostrarDesactualizacion" class="aviso-capacidad" role="status">
      Los datos podrían estar desactualizados.
    </p>
  </section>
</template>

<style scoped>
.capacidad-rfid {
  display: grid;
  gap: 16px;
  border: 1px solid var(--app-border);
  border-radius: 16px;
  padding: clamp(16px, 2vw, 24px);
  background: var(--app-surface);
}
.encabezado-capacidad {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.encabezado-capacidad h2 {
  margin: 0;
  color: var(--app-foreground);
  font-size: 1.1rem;
  font-weight: 600;
}
.descripcion-capacidad,
.aviso-capacidad {
  margin: 4px 0 0;
  color: var(--app-muted);
  line-height: 1.5;
}
.indicadores-capacidad {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 0;
}
.indicadores-capacidad > div {
  border: 1px solid var(--app-border);
  border-radius: 12px;
  padding: 14px;
}
.indicadores-capacidad > .indicador-principal {
  border-color: var(--app-border);
  background: var(--app-surface-hover);
}
.indicadores-capacidad dt {
  color: var(--app-muted);
  font-size: 0.84rem;
}
.indicadores-capacidad dd {
  margin: 6px 0 0;
  color: var(--app-foreground);
  font-size: 1.5rem;
  font-weight: 600;
}
.indicador-principal dd {
  color: var(--app-primary);
  font-size: 1.75rem;
}
@media (max-width: 600px) {
  .encabezado-capacidad {
    flex-wrap: wrap;
  }
  .indicadores-capacidad {
    grid-template-columns: 1fr;
  }
}
</style>
