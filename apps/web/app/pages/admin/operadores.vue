<script setup lang="ts">
import { computed, onMounted, onScopeDispose, watch } from 'vue'
import type { AccionAdministracionOperador } from '~/types/operador'
import { useDirectorioOperadores } from '~/composables/useDirectorioOperadores'
import { useAdministracionOperadores } from '~/composables/useAdministracionOperadores'
import TablaOperadores from '~/components/admin/operadores/TablaOperadores.vue'
import FiltrosOperadores from '~/components/admin/operadores/FiltrosOperadores.vue'
import ModalAdministrarOperador from '~/components/admin/operadores/ModalAdministrarOperador.vue'
import ModalConciliarOperador from '~/components/admin/operadores/ModalConciliarOperador.vue'
import ModalAgregarOperador from '~/components/admin/operadores/ModalAgregarOperador.vue'
import type { RespuestaAccionEmpleadoOperador } from '~/types/empleado'

definePageMeta({ middleware: 'dueno' })

const directorio = await useDirectorioOperadores()
const administracion = useAdministracionOperadores(directorio.programarRefresco)
const { sesion } = useSesion()
const toast = useToast()
const conciliacionAbierta = ref(false)
const altaOperadorAbierta = ref(false)
const operadorConciliarId = ref<string | null>(null)
const indiceFocoOperador = ref<number | null>(null)
const administracionAbierta = computed({
  get: () => administracion.abierto.value,
  set: (valor: boolean) => {
    if (valor) administracion.abierto.value = true
    else administracion.cerrar()
  },
})
const accionAdministracion = computed({
  get: () => administracion.accion.value,
  set: (valor: AccionAdministracionOperador | null) => {
    administracion.accion.value = valor
  },
})
type PaginaVisible = number | 'anterior' | 'siguiente'
const paginasVisibles = computed<PaginaVisible[]>(() => {
  const total = directorio.totalPaginas.value
  if (total <= 7) return Array.from({ length: total }, (_, indice) => indice + 1)

  const actual = directorio.paginaActual.value
  const inicio = actual <= 4 ? 1 : actual >= total - 3 ? total - 6 : actual - 1
  const fin = Math.min(total, inicio + 6)
  return [
    ...(inicio > 1 ? [1, ...(inicio > 2 ? (['anterior'] as const) : [])] : []),
    ...Array.from({ length: fin - inicio + 1 }, (_, indice) => inicio + indice),
    ...(fin < total ? [...(fin < total - 1 ? (['siguiente'] as const) : []), total] : []),
  ]
})

function actualizarDesdeEvento() {
  directorio.programarRefresco()
  administracion.programarRefrescoDetalle()
}

watch(
  () => sesion.value.estado === 'autenticada' && sesion.value.identidad.rol === 'DUENO',
  (esDueno) => {
    if (!esDueno) {
      directorio.limpiarSesion()
      administracion.cerrar()
      conciliacionAbierta.value = false
      altaOperadorAbierta.value = false
      operadorConciliarId.value = null
      indiceFocoOperador.value = null
    }
  },
)
onMounted(() => directorio.iniciarEventos(actualizarDesdeEvento))
onScopeDispose(directorio.detenerEventos)

function administrarOperador(id: string, indice: number) {
  indiceFocoOperador.value = indice
  administracion.abrir(id)
}

function conciliarOperador(id: string, indice: number) {
  indiceFocoOperador.value = indice
  operadorConciliarId.value = id
  conciliacionAbierta.value = true
}

function conciliacionCompletada() {
  toast.add({
    title: 'Cuenta vinculada',
    description: 'La cuenta quedó vinculada al empleado seleccionado.',
    color: 'success',
  })
  directorio.programarRefresco()
}

function operadorCreado(resultado: RespuestaAccionEmpleadoOperador) {
  const envio = resultado.estadoInvitacion
  const descripcion =
    envio === 'ENVIADO'
      ? 'La cuenta quedó pendiente de activación y la invitación se envió.'
      : envio === 'FALLIDO'
        ? 'La cuenta quedó pendiente de activación, pero el correo no se pudo enviar.'
        : envio === 'DESCONOCIDO'
          ? 'La cuenta quedó pendiente de activación; confirma la entrega en Mailpit.'
          : 'La cuenta quedó pendiente de activación.'
  toast.add({
    title: 'Cuenta de operador creada',
    description: descripcion,
    color: envio === 'ENVIADO' ? 'success' : 'warning',
  })
  directorio.programarRefresco()
}

function limpiarFiltros() {
  directorio.limpiarFiltros()
}
</script>

<template>
  <section class="seccion-operadores" aria-label="Administración de operadores">
    <div class="encabezado-operadores">
      <div>
        <p class="descripcion-operadores">Administra las cuentas y su vínculo con empleados.</p>
      </div>
      <div class="acciones-encabezado-operadores">
        <UButton
          id="boton-anadir-operador"
          color="primary"
          icon="i-lucide-user-round-plus"
          @click="altaOperadorAbierta = true"
        >
          Añadir operador
        </UButton>
        <UButton
          color="neutral"
          variant="outline"
          icon="i-lucide-refresh-cw"
          :disabled="directorio.pending.value"
          @click="directorio.recargar()"
        >
          Actualizar lista
        </UButton>
      </div>
    </div>

    <section class="panel-operadores" aria-label="Directorio de operadores">
      <FiltrosOperadores
        :busqueda="directorio.busqueda.value"
        :estado="directorio.estado.value"
        :error-busqueda="directorio.errorBusqueda.value"
        @update:busqueda="directorio.cambiarBusqueda"
        @update:estado="directorio.cambiarEstado"
      />
      <div
        v-if="directorio.pending.value"
        class="estado-operadores estado-operadores--cargando"
        role="status"
      >
        Cargando operadores…
      </div>
      <div
        v-else-if="directorio.mensajeError.value"
        class="estado-operadores estado-operadores--error"
        role="alert"
      >
        <p>{{ directorio.mensajeError.value }}</p>
        <UButton
          color="neutral"
          variant="outline"
          icon="i-lucide-refresh-cw"
          :disabled="directorio.pending.value"
          @click="directorio.recargar()"
        >
          Reintentar
        </UButton>
      </div>
      <div v-else-if="directorio.totalRegistros.value === 0" class="estado-operadores">
        <template v-if="directorio.filtrosActivos.value">
          <UIcon name="i-lucide-search-x" aria-hidden="true" />
          <h2>No encontramos personas con esos datos</h2>
          <p>Prueba con otro nombre o estado.</p>
          <UButton color="neutral" variant="outline" @click="limpiarFiltros">
            Limpiar filtros
          </UButton>
        </template>
        <template v-else>
          <UIcon name="i-lucide-users-round" aria-hidden="true" />
          <h2>Aún no hay operadores</h2>
          <p>Las cuentas de operador se crean desde el registro de un empleado.</p>
          <UButton to="/admin/empleados" variant="outline">Agregar empleado</UButton>
        </template>
      </div>
      <TablaOperadores
        v-else
        :operadores="directorio.operadores.value"
        @administrar="administrarOperador"
        @conciliar="conciliarOperador"
      />
      <footer v-if="directorio.totalRegistros.value > 0" class="pie-operadores">
        <span class="resumen-operadores" role="status">
          Mostrando {{ directorio.operadores.value.length }} de
          {{ directorio.totalRegistros.value }} operadores
        </span>
        <nav
          v-if="directorio.totalPaginas.value > 1"
          class="paginacion-operadores"
          :aria-label="`Páginas de operadores, página ${directorio.paginaActual.value} de ${directorio.totalPaginas.value}`"
        >
          <UButton
            color="neutral"
            variant="outline"
            size="sm"
            :disabled="directorio.pending.value || directorio.paginaActual.value <= 1"
            aria-label="Página anterior"
            @click="directorio.cambiarPagina(directorio.paginaActual.value - 1)"
          >
            Anterior
          </UButton>
          <ul class="lista-paginas">
            <li v-for="pagina in paginasVisibles" :key="pagina">
              <span v-if="typeof pagina !== 'number'" class="separador-paginas" aria-hidden="true">
                …
              </span>
              <span v-if="typeof pagina !== 'number'" class="sr-only">Se omiten páginas</span>
              <UButton
                v-else
                :color="pagina === directorio.paginaActual.value ? 'primary' : 'neutral'"
                :variant="pagina === directorio.paginaActual.value ? 'solid' : 'ghost'"
                size="sm"
                :disabled="directorio.pending.value"
                :aria-current="pagina === directorio.paginaActual.value ? 'page' : undefined"
                :aria-label="`Ir a la página ${pagina}`"
                @click="directorio.cambiarPagina(pagina)"
              >
                {{ pagina }}
              </UButton>
            </li>
          </ul>
          <UButton
            color="neutral"
            variant="outline"
            size="sm"
            :disabled="
              directorio.pending.value ||
              directorio.paginaActual.value >= directorio.totalPaginas.value
            "
            aria-label="Página siguiente"
            @click="directorio.cambiarPagina(directorio.paginaActual.value + 1)"
          >
            Siguiente
          </UButton>
        </nav>
      </footer>
    </section>

    <ModalAdministrarOperador
      v-model:open="administracionAbierta"
      v-model:accion="accionAdministracion"
      :detalle="administracion.detalle.value"
      :cargando="administracion.cargando.value"
      :ocupado="administracion.ocupado.value"
      :error="administracion.error.value"
      :puede-reintentar="administracion.puedeReintentar.value"
      :indice-foco="indiceFocoOperador"
      @confirmar="administracion.confirmarAccion"
      @reintentar="administracion.cargarDetalle()"
    />
    <ModalConciliarOperador
      v-model:open="conciliacionAbierta"
      :operador-id="operadorConciliarId"
      :indice-foco="indiceFocoOperador"
      @vinculado="conciliacionCompletada"
    />
    <ModalAgregarOperador v-model:open="altaOperadorAbierta" @creada="operadorCreado" />
  </section>
</template>

<style scoped>
.seccion-operadores {
  display: grid;
  gap: 24px;
}
.encabezado-operadores,
.resumen-operadores,
.pie-operadores {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}
.acciones-encabezado-operadores {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.resumen-operadores {
  margin: 4px 0 0;
  color: var(--app-foreground);
}
.descripcion-operadores {
  margin: 8px 0 0;
  color: var(--app-muted);
  line-height: 1.55;
}
.panel-operadores {
  display: grid;
  gap: 20px;
  border: 1px solid var(--app-border);
  border-radius: 16px;
  padding: clamp(16px, 3vw, 24px);
  background: var(--app-surface);
  box-shadow: 0 2px 8px rgb(41 37 47 / 4%);
}
.resumen-operadores,
.pie-operadores {
  color: var(--app-muted);
  font-size: 0.86rem;
}
.estado-operadores {
  display: grid;
  min-height: 12rem;
  gap: 12px;
  place-content: center;
  justify-items: center;
  text-align: center;
  color: var(--app-muted);
}
.estado-operadores h2,
.estado-operadores p {
  margin: 0;
}
.estado-operadores h2 {
  color: var(--app-foreground);
}
.estado-operadores--error {
  display: flex;
  min-height: 0;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid color-mix(in srgb, var(--app-error) 28%, var(--app-border));
  border-radius: 12px;
  padding: 12px 14px;
  color: var(--app-error);
  text-align: left;
}
.estado-operadores--error p {
  margin: 0;
}
.pie-operadores {
  flex-wrap: wrap;
  border-top: 1px solid var(--app-border);
  padding-top: 16px;
}
.paginacion-operadores,
.lista-paginas {
  display: flex;
  align-items: center;
  gap: 4px;
}
.lista-paginas {
  margin: 0;
  padding: 0;
  list-style: none;
}
.separador-paginas {
  display: inline-grid;
  min-width: 1.5rem;
  min-height: 2rem;
  place-items: center;
}
@media (max-width: 38rem) {
  .encabezado-operadores,
  .resumen-operadores,
  .pie-operadores {
    align-items: flex-start;
    flex-direction: column;
  }
  .encabezado-operadores :deep(button) {
    width: 100%;
    justify-content: center;
  }
  .acciones-encabezado-operadores {
    width: 100%;
    flex-direction: column-reverse;
  }
  .resumen-operadores {
    margin: 0;
  }
  .estado-operadores--error {
    align-items: flex-start;
    flex-direction: column;
  }
  .paginacion-operadores {
    max-width: 100%;
    flex-wrap: wrap;
  }
  .lista-paginas {
    flex-wrap: wrap;
  }
}
</style>
