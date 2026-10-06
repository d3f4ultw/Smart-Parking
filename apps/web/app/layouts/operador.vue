<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'

import {
  crearControladorEventosTiempoReal,
  proveerEventosTiempoReal,
} from '~/utils/eventos-tiempo-real'

const { limpiarSesion } = useSesion()
const eventosTiempoReal = crearControladorEventosTiempoReal({
  alPerderSesion: async () => {
    limpiarSesion()
    clearNuxtData()
    await navigateTo('/login', { replace: true })
  },
})
proveerEventosTiempoReal(eventosTiempoReal)

onMounted(() => eventosTiempoReal.iniciar())
onBeforeUnmount(() => eventosTiempoReal.detener())
</script>

<template>
  <div class="operator-layout">
    <slot />
  </div>
</template>
