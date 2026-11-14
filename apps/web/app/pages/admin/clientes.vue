<script setup lang="ts">
import { onMounted, onScopeDispose, watch } from 'vue'
import FiltrosClientes from '~/components/admin/clientes/FiltrosClientes.vue'
import ModalDetalleCliente from '~/components/admin/clientes/ModalDetalleCliente.vue'
import TablaClientes from '~/components/admin/clientes/TablaClientes.vue'
import type { ClienteResumenAdministracion } from '~/types/cliente-admin'

definePageMeta({
  middleware: ['sesion', 'modulo-administracion'],
  alias: '/operador/clientes',
})

const directorio = await useDirectorioClientes()
const {
  clientes,
  directorio: datosDirectorio,
  estado,
  busqueda,
  pending,
  mensajeError,
  paginaActual,
  totalClientes,
  totalRegistros,
  totalPaginas,
} = directorio
const { sesion } = useSesion()
const detalleAbierto = ref(false)
const codigoSeleccionado = ref<string | null>(null)
const actualizacionDetalle = ref(0)

watch(directorio.directorio, directorio.sincronizarUrl, {
  immediate: true,
  flush: 'post',
})
watch(
  () => sesion.value?.estado === 'autenticada' && sesion.value.identidad.rol === 'DUENO',
  (esDueno) => {
    if (!esDueno) {
      detalleAbierto.value = false
      directorio.limpiarSesion()
    }
  },
)

onMounted(() => {
  directorio.iniciarEventos(() => {
    actualizacionDetalle.value += 1
  })
})
onScopeDispose(() => directorio.detenerEventos())

function verDetalles(cliente: ClienteResumenAdministracion) {
  codigoSeleccionado.value = cliente.codigo
  detalleAbierto.value = true
}
</script>

<template>
  <section class="seccion-directorio" aria-label="Clientes">
    <div id="titulo-clientes" class="encabezado-directorio" tabindex="-1">
      <div>
        <p class="sobrelinea">Directorio administrativo</p>
        <p class="descripcion-directorio">
          Consulta el estado de las membresías y los datos de cada cliente.
        </p>
      </div>
    </div>

    <section
      class="panel-directorio"
      aria-label="Lista de clientes"
      aria-live="polite"
      :aria-busy="pending"
    >
      <div class="resumen-directorio">
        <div>
          <h3>Directorio</h3>
          <span>
            {{ totalClientes }}
            {{ totalClientes === 1 ? 'cliente' : 'clientes' }} en total
          </span>
        </div>
        <div class="filtros-directorio">
          <UFormField label="Buscar por nombre o código" name="busqueda">
            <div class="campo-busqueda">
              <UInput
                :model-value="busqueda"
                placeholder="Nombre o código de cliente"
                maxlength="100"
                autocomplete="off"
                @update:model-value="directorio.cambiarBusqueda"
              />
              <UButton
                v-if="busqueda"
                type="button"
                color="neutral"
                variant="ghost"
                icon="i-lucide-x"
                aria-label="Limpiar búsqueda"
                @click="directorio.limpiarBusqueda"
              />
            </div>
          </UFormField>
          <FiltrosClientes
            :model-value="estado"
            :deshabilitado="pending"
            @update:model-value="directorio.cambiarEstado"
          />
        </div>
      </div>

      <div v-if="pending && !datosDirectorio" class="estado-directorio" role="status">
        Cargando clientes…
      </div>
      <div v-else-if="mensajeError" class="estado-directorio estado-directorio--error" role="alert">
        <p>{{ mensajeError }}</p>
        <UButton
          color="neutral"
          variant="outline"
          icon="i-lucide-refresh-cw"
          @click="directorio.recargar()"
        >
          Reintentar
        </UButton>
      </div>
      <div v-else-if="totalRegistros === 0" class="estado-directorio">
        <UIcon name="i-lucide-users-round" aria-hidden="true" />
        <template v-if="totalClientes === 0 && estado === 'todos' && !busqueda">
          <h3>Aún no hay clientes</h3>
          <p>Cuando una persona cree su cuenta, aparecerá en este directorio.</p>
        </template>
        <template v-else-if="busqueda">
          <h3>No hay resultados de búsqueda</h3>
          <p>Prueba con otro nombre o código, o cambia el estado de membresía.</p>
          <UButton color="neutral" variant="outline" @click="directorio.limpiarBusqueda">
            Limpiar búsqueda
          </UButton>
        </template>
        <template v-else>
          <h3>No hay clientes con este estado</h3>
          <p>Cambia el estado de membresía para consultar otros clientes.</p>
        </template>
      </div>
      <TablaClientes v-else :clientes="clientes" :ocupado="pending" @ver-detalles="verDetalles" />

      <footer v-if="totalRegistros > 0" class="pie-directorio">
        <span>
          Mostrando {{ clientes.length }} de {{ totalRegistros }}
          {{ totalRegistros === 1 ? 'cliente' : 'clientes' }}.
        </span>
        <UPagination
          v-if="totalPaginas > 1"
          :page="paginaActual"
          :items-per-page="10"
          :sibling-count="1"
          :total="totalRegistros"
          :disabled="pending"
          aria-label="Páginas de clientes"
          @update:page="directorio.cambiarPagina"
        />
      </footer>
    </section>

    <ModalDetalleCliente
      v-model:open="detalleAbierto"
      :codigo="codigoSeleccionado"
      :actualizacion="actualizacionDetalle"
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
.filtros-directorio,
.campo-busqueda {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}
.campo-busqueda :deep(input) {
  min-width: 15rem;
}
.resumen-directorio h3 {
  margin: 4px 0 0;
  color: var(--app-foreground);
}
.descripcion-directorio {
  margin: 8px 0 0;
  color: var(--app-muted);
  line-height: 1.55;
}
.resumen-directorio > div:first-child {
  display: grid;
  gap: 6px;
}
.resumen-directorio h3 {
  font-size: 1rem;
}
.resumen-directorio span,
.pie-directorio {
  color: var(--app-muted);
  font-size: 0.86rem;
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
  padding-top: 4px;
}
@media (max-width: 42rem) {
  .resumen-directorio,
  .pie-directorio {
    align-items: stretch;
    flex-direction: column;
  }
  .filtros-directorio {
    align-items: stretch;
    flex-direction: column;
  }
  .campo-busqueda {
    align-items: center;
    flex-direction: row;
  }
  .campo-busqueda :deep(input) {
    width: 100%;
    min-width: 0;
  }
  .pie-directorio :deep(ul) {
    justify-content: center;
  }
}
</style>
