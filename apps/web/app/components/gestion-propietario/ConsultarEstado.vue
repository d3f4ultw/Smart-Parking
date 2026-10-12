<script setup lang="ts">
import { computed } from 'vue'

import ListaInscripciones from './ListaInscripciones.vue'
import type { PanelGestionProps } from '~/utils/gestion-propietario'

const props = defineProps<PanelGestionProps>()
const emit = defineEmits<{ reenviar: [id: number] }>()

const inscripcionCompletada = computed(() =>
  props.estado?.inscripciones.some((inscripcion) => inscripcion.estado === 'completado') ?? false)
</script>

<template>
  <section class="action-panel" aria-labelledby="history-title">
    <header>
      <h1 id="history-title">Historial</h1>
    </header>

    <p v-if="cargando && reenviandoId === null" class="loading-copy" role="status">Consultando estado…</p>
    <p
      v-if="estado !== null && (!estado.owner_activo || !inscripcionCompletada)"
      class="owner-state"
      role="status"
    >
      {{ estado.owner_activo ? 'El dueño ya está vinculado.' : 'No hay un dueño vinculado.' }}
    </p>

    <ListaInscripciones
      v-if="estado !== null"
      :inscripciones="estado.inscripciones"
      :consultado-en="consultadoEn"
      :owner-activo="estado.owner_activo"
      :owner-correo="estado.owner?.correo ?? null"
      :permitir-reenvio="true"
      :reenviando-id="reenviandoId"
      @reenviar="emit('reenviar', $event)"
    />
  </section>
</template>

<style scoped>
.action-panel {
  display: grid;
  gap: 1rem;
}

h1 {
  margin: 0;
  color: #30263b;
  font-size: clamp(1.5rem, 3vw, 2rem);
  letter-spacing: -0.03em;
}

.eyebrow {
  margin: 0 0 0.35rem;
  color: #74647f;
  font-size: 0.69rem;
  font-weight: 750;
  letter-spacing: 0.11em;
  text-transform: uppercase;
}

.loading-copy {
  margin: 0.55rem 0 0;
  color: #655d6c;
  font-size: 0.9rem;
  line-height: 1.55;
}

.owner-state {
  margin: 0;
  padding: 0.75rem 0.9rem;
  border: 1px solid #ded6e7;
  border-radius: 0.65rem;
  color: #443653;
  background: #ffffff;
  font-size: 0.88rem;
}
</style>
