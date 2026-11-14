<script setup lang="ts">
import OcupacionCajones from '~/components/admin/vision/OcupacionCajones.vue'
import ResumenCapacidadRfid from '~/components/admin/vision/ResumenCapacidadRfid.vue'

definePageMeta({
  layout: 'admin',
  middleware: ['sesion', 'modulo-administracion'],
  alias: '/operador/monitoreo',
})
useSeoMeta({ title: 'Monitoreo | Smart Parking' })

const {
  cajones,
  pendiente,
  desactualizado,
  mensajeError,
  ultimaConsulta,
  hayDatos,
  estado,
  actualizar,
} = await useOcupacionVision()

const {
  datos: capacidad,
  pendiente: pendienteCapacidad,
  mensajeError: errorCapacidad,
  desactualizado: capacidadDesactualizada,
  actualizar: actualizarCapacidad,
} = await useCapacidadRfid()
</script>

<template>
  <div class="paneles-monitoreo">
    <ResumenCapacidadRfid
      :datos="capacidad"
      :pendiente="pendienteCapacidad"
      :mensaje-error="errorCapacidad"
      :desactualizado="capacidadDesactualizada"
      @actualizar="actualizarCapacidad"
    />
    <OcupacionCajones
      :cajones="cajones"
      :pendiente="pendiente"
      :desactualizado="desactualizado"
      :mensaje-error="mensajeError"
      :ultima-consulta="ultimaConsulta"
      :hay-datos="hayDatos"
      :estado="estado"
      @actualizar="actualizar"
    />
  </div>
</template>

<style scoped>
.paneles-monitoreo {
  display: grid;
  width: 100%;
  min-width: 0;
  gap: 24px;
}
</style>
