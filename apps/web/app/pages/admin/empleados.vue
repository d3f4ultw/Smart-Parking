<script setup lang="ts">
import { onMounted, onScopeDispose, watch } from 'vue'
import type { Empleado, ReciboRegistroEmpleado } from '~/types/empleado'
import { ErrorEmpleadoApi, useClienteEmpleados } from '~/utils/empleados-api'
import TablaEmpleados from '~/components/admin/empleados/TablaEmpleados.vue'
import ModalRegistroEmpleado from '~/components/admin/empleados/ModalRegistroEmpleado.vue'
import ModalConfirmarCambioEstado from '~/components/admin/empleados/ModalConfirmarCambioEstado.vue'
import ModalAdministrarEmpleado from '~/components/admin/empleados/ModalAdministrarEmpleado.vue'

definePageMeta({ middleware: 'dueno' })

const directorio = await useDirectorioEmpleados()
const { empleados, pending, mensajeError, paginaActual, totalRegistros } = directorio
const { sesion } = useSesion()
const cliente = useClienteEmpleados()
const csrf = useCsrf()
const toast = useToast()
const registroAbierto = ref(false)
const estadoAbierto = ref(false)
const administracionAbierta = ref(false)
const empleadoSeleccionado = ref<Empleado | null>(null)
const empleadoAdministradoId = ref<string | null>(null)
const cambiandoEstado = ref(false)
const errorCambio = ref('')

watch(directorio.directorio, directorio.sincronizarUrl, {
  immediate: true,
  flush: 'post',
})
watch(
  () => sesion.value?.estado === 'autenticada' && sesion.value.identidad.rol === 'DUENO',
  (esDueno) => {
    if (!esDueno) {
      directorio.limpiarSesion()
      administracionAbierta.value = false
      empleadoAdministradoId.value = null
      estadoAbierto.value = false
      empleadoSeleccionado.value = null
    }
  },
)
onMounted(() => directorio.iniciarEventos())
onScopeDispose(() => directorio.detenerEventos())

watch(directorio.empleados, (empleados) => {
  if (!empleadoSeleccionado.value) return
  const actualizado = empleados.find(
    (empleado) => empleado.idTexto === empleadoSeleccionado.value?.idTexto,
  )
  if (actualizado) empleadoSeleccionado.value = actualizado
})

function confirmarCambio(empleado: Empleado) {
  empleadoSeleccionado.value = empleado
  errorCambio.value = ''
  estadoAbierto.value = true
}

function administrarEmpleado(empleado: Empleado) {
  empleadoAdministradoId.value = empleado.idTexto
  administracionAbierta.value = true
}

async function cambiarEstado() {
  const empleado = empleadoSeleccionado.value
  if (!empleado || cambiandoEstado.value) return
  cambiandoEstado.value = true
  errorCambio.value = ''
  try {
    const token = await csrf.obtener()
    const destino = empleado.estado === 'ACTIVO' ? 'INACTIVO' : 'ACTIVO'
    await cliente.cambiarEstado(empleado.idTexto, destino, `"${empleado.revisionTexto}"`, token)
    estadoAbierto.value = false
    empleadoSeleccionado.value = null
    toast.add({
      title: 'Empleado actualizado',
      description: `El empleado ${empleado.codigo} quedó ${destino === 'ACTIVO' ? 'activo' : 'inactivo'}.`,
      color: 'success',
    })
    directorio.programarRefresco()
  } catch (fallo) {
    if (fallo instanceof ErrorEmpleadoApi && fallo.estado === 412) {
      errorCambio.value = 'La información cambió. Actualiza la lista y vuelve a intentarlo.'
      directorio.programarRefresco()
    } else {
      errorCambio.value =
        fallo instanceof ErrorEmpleadoApi
          ? fallo.message
          : 'No pudimos cambiar el estado del empleado. Inténtalo de nuevo.'
    }
  } finally {
    cambiandoEstado.value = false
  }
}

async function empleadoRegistrado(recibo: ReciboRegistroEmpleado) {
  toast.add({
    title: 'Empleado agregado',
    description: `Se agregó el empleado ${recibo.codigo}.`,
    color: 'success',
  })
  const ultimaPagina = Math.max(1, Math.ceil((totalRegistros.value + 1) / 10))
  if (ultimaPagina !== directorio.paginaActual.value) await directorio.cambiarPagina(ultimaPagina)
  else directorio.programarRefresco()
}
</script>

<template>
  <section class="seccion-directorio" aria-label="Empleados">
    <div class="encabezado-directorio">
      <div>
        <p class="sobrelinea">Equipo del estacionamiento</p>
        <h2 id="titulo-empleados" tabindex="-1">Empleados</h2>
        <p class="descripcion-directorio">
          Administra los datos del equipo y las cuentas de operador vinculadas.
        </p>
      </div>
      <UButton icon="i-lucide-user-round-plus" @click="registroAbierto = true"
        >Agregar empleado</UButton
      >
    </div>

    <section class="panel-directorio" aria-label="Lista de empleados" aria-live="polite">
      <div class="resumen-directorio">
        <h3>Empleados</h3>
        <span>{{ totalRegistros }} {{ totalRegistros === 1 ? 'empleado' : 'empleados' }}</span>
      </div>
      <div v-if="pending" class="estado-directorio" role="status">Cargando empleados…</div>
      <div v-else-if="mensajeError" class="estado-directorio estado-directorio--error" role="alert">
        <p>{{ mensajeError }}</p>
        <UButton
          color="neutral"
          variant="outline"
          icon="i-lucide-refresh-cw"
          @click="directorio.recargar()"
          >Reintentar</UButton
        >
      </div>
      <div v-else-if="totalRegistros === 0" class="estado-directorio">
        <UIcon name="i-lucide-users-round" aria-hidden="true" />
        <h3>Aún no hay empleados</h3>
        <p>Agrega al primer empleado para verlo aquí.</p>
        <UButton variant="outline" @click="registroAbierto = true">Agregar empleado</UButton>
      </div>
      <TablaEmpleados
        v-else
        :empleados="empleados"
        :ocupado="cambiandoEstado"
        @administrar="administrarEmpleado"
        @cambiar-estado="confirmarCambio"
      />
      <footer v-if="totalRegistros > 0" class="pie-directorio">
        <span>Mostrando {{ empleados.length }} de {{ totalRegistros }} empleados.</span>
        <UPagination
          :page="paginaActual"
          :items-per-page="10"
          :total="totalRegistros"
          :disabled="pending"
          aria-label="Páginas de empleados"
          @update:page="directorio.cambiarPagina"
        />
      </footer>
    </section>

    <ModalRegistroEmpleado v-model:open="registroAbierto" @registrado="empleadoRegistrado" />
    <ModalAdministrarEmpleado
      v-model:open="administracionAbierta"
      :id-texto="empleadoAdministradoId"
      @actualizado="directorio.programarRefresco"
    />
    <ModalConfirmarCambioEstado
      v-model:open="estadoAbierto"
      :empleado="empleadoSeleccionado"
      :ocupado="cambiandoEstado"
      :error="errorCambio"
      @confirmar="cambiarEstado"
    />
  </section>
</template>

<style scoped>
.seccion-directorio {
  display: grid;
  gap: 24px;
}
.encabezado-directorio,
.resumen-directorio,
.pie-directorio {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}
.encabezado-directorio h2,
.resumen-directorio h3 {
  margin: 4px 0 0;
  color: var(--app-foreground);
}
.encabezado-directorio h2 {
  font-size: 1.35rem;
}
.descripcion-directorio {
  margin: 8px 0 0;
  color: var(--app-muted);
  line-height: 1.55;
}
.panel-directorio {
  display: grid;
  gap: 20px;
  border: 1px solid var(--app-border);
  border-radius: 16px;
  padding: clamp(16px, 3vw, 24px);
  background: var(--app-surface);
  box-shadow: 0 2px 8px rgb(41 37 47 / 4%);
}
.resumen-directorio {
  padding-bottom: 4px;
}
.resumen-directorio h3 {
  font-size: 1rem;
}
.resumen-directorio > span,
.pie-directorio {
  color: var(--app-muted);
  font-size: 0.86rem;
}
.estado-directorio {
  display: grid;
  min-height: 12rem;
  gap: 12px;
  place-content: center;
  justify-items: center;
  text-align: center;
  color: var(--app-muted);
}
.estado-directorio h3,
.estado-directorio p {
  margin: 0;
}
.estado-directorio h3 {
  color: var(--app-foreground);
}
.estado-directorio--error {
  color: var(--app-error);
}
.pie-directorio {
  flex-wrap: wrap;
  border-top: 1px solid var(--app-border);
  padding-top: 16px;
}
@media (max-width: 38rem) {
  .encabezado-directorio {
    align-items: flex-start;
    flex-direction: column;
  }
  .encabezado-directorio :deep(button) {
    width: 100%;
    justify-content: center;
  }
  .resumen-directorio {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }
  .pie-directorio {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
