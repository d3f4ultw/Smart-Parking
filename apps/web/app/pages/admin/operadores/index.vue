<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'

import { obtenerEstadoErrorOperador } from '~/utils/operadores'
import {
  etiquetaEstadoCuentaOperador,
  obtenerPaginaSolicitadaOperadores,
  mapearErrorGestionOperador,
  type RespuestaListaOperadores,
} from '~/utils/gestion-operadores'

definePageMeta({
  middleware: 'sesion-admin',
})

const CLAVE_LISTA_OPERADORES = 'admin-operadores-lista'
const route = useRoute()
const router = useRouter()
const { listarOperadores } = useOperadores()
const { limpiarSesion } = useSesion()
const mensajeError = ref('')
const paginaSolicitada = computed(() =>
  obtenerPaginaSolicitadaOperadores(route.query.pagina),
)

const { data, error, pending, refresh } = await useAsyncData<RespuestaListaOperadores>(
  CLAVE_LISTA_OPERADORES,
  () => listarOperadores(paginaSolicitada.value),
  {
    default: () => ({
      operadores: [],
      pagina: 1,
      tamano_pagina: 10,
      total: 0,
      total_paginas: 0,
    }),
    dedupe: 'defer',
    watch: [paginaSolicitada],
  },
)

const paginaActual = computed(() => data.value.pagina)

function rutaDetalle(operadorId: number) {
  return {
    path: `/admin/operadores/${operadorId}`,
    query: paginaActual.value > 1
      ? { pagina: String(paginaActual.value) }
      : {},
  }
}

function cambiarPagina(pagina: number) {
  const nuevaPagina = Math.min(Math.max(1, pagina), data.value.total_paginas)
  return router.push({
    path: '/admin/operadores',
    query: nuevaPagina > 1 ? { pagina: String(nuevaPagina) } : {},
  })
}

async function atenderError(errorActual: unknown) {
  const codigo = obtenerEstadoErrorOperador(errorActual)
  if (codigo === 401) {
    limpiarSesion()
    clearNuxtData(CLAVE_LISTA_OPERADORES)
    await navigateTo('/login', { replace: true })
    return
  }
  mensajeError.value = mapearErrorGestionOperador(codigo)
}

if (error.value) {
  await atenderError(error.value)
}

watch(error, (errorActual) => {
  if (errorActual) {
    void atenderError(errorActual)
  }
})

watch(paginaSolicitada, () => {
  mensajeError.value = ''
})

watch([paginaSolicitada, data, pending, error], ([pagina, respuesta, estaPendiente, errorActual]) => {
  if (!import.meta.client || estaPendiente || errorActual) {
    return
  }

  const paginaEfectiva = respuesta.pagina
  const parametroEsperado = paginaEfectiva > 1 ? String(paginaEfectiva) : undefined
  const parametroActual = route.query.pagina
  const urlCanonica = parametroEsperado === undefined
    ? parametroActual === undefined
    : parametroActual === parametroEsperado

  if (!urlCanonica || pagina !== paginaEfectiva) {
    void router.replace({
      path: '/admin/operadores',
      query: parametroEsperado ? { pagina: parametroEsperado } : {},
    })
  }
}, { flush: 'post', immediate: true })

async function actualizarLista() {
  mensajeError.value = ''
  await refresh()
}

onUnmounted(() => clearNuxtData(CLAVE_LISTA_OPERADORES))
</script>

<template>
  <main class="operators-page">
    <section class="operators-card" aria-labelledby="operators-title">
      <header class="page-header">
        <div>
          <p class="eyebrow">Smart Parking · Administración</p>
          <h1 id="operators-title">Operadores</h1>
          <p>Consulta y administra el acceso de las cuentas OPERADOR.</p>
        </div>
        <NuxtLink class="button secondary" to="/admin">Volver al panel</NuxtLink>
      </header>

      <div v-if="mensajeError" class="notice error" role="alert">
        {{ mensajeError }}
      </div>

      <div class="list-actions">
        <NuxtLink
          class="button secondary"
          :to="{
            path: '/admin/operadores/nuevo',
            query: paginaActual > 1 ? { pagina: String(paginaActual) } : {},
          }"
        >
          Crear operador
        </NuxtLink>
        <button class="button secondary" type="button" :disabled="pending" @click="actualizarLista">
          {{ pending ? 'Actualizando…' : 'Actualizar lista' }}
        </button>
      </div>

      <p v-if="pending && data.total === 0" role="status">
        Cargando operadores…
      </p>
      <p v-else-if="data.total === 0 && !mensajeError" role="status">
        No hay cuentas OPERADOR registradas.
      </p>

      <section v-else-if="data.total > 0 && !error" :aria-busy="pending" aria-label="Listado de operadores">
        <p class="page-summary">
          {{ data.total }} {{ data.total === 1 ? 'operador' : 'operadores' }} ·
          Página {{ data.pagina }} de {{ data.total_paginas }}
        </p>

        <p v-if="pending" role="status">Actualizando página…</p>
        <ul v-else class="operator-list" aria-label="Cuentas OPERADOR">
          <li v-for="operador in data.operadores" :key="operador.id" class="operator-row">
            <div class="operator-identity">
              <NuxtLink :to="rutaDetalle(operador.id)">
                {{ [operador.nombre, operador.apellido_paterno, operador.apellido_materno].filter(Boolean).join(' ') || operador.correo }}
              </NuxtLink>
              <span>{{ operador.correo }}</span>
            </div>
            <div class="operator-states">
              <span class="state" :class="operador.estado_cuenta">
                {{ etiquetaEstadoCuentaOperador(operador.estado_cuenta) }}
              </span>
            </div>
          </li>
        </ul>

        <nav v-if="data.total_paginas > 1" class="pagination" aria-label="Paginación de operadores">
          <button
            class="button secondary"
            type="button"
            :disabled="pending || paginaActual <= 1"
            @click="cambiarPagina(1)"
          >Primera</button>
          <button
            class="button secondary"
            type="button"
            :disabled="pending || paginaActual <= 1"
            @click="cambiarPagina(paginaActual - 1)"
          >Anterior</button>
          <button
            class="button secondary"
            type="button"
            :disabled="pending || paginaActual >= data.total_paginas"
            @click="cambiarPagina(paginaActual + 1)"
          >Siguiente</button>
          <button
            class="button secondary"
            type="button"
            :disabled="pending || paginaActual >= data.total_paginas"
            @click="cambiarPagina(data.total_paginas)"
          >Última</button>
        </nav>
      </section>
    </section>
  </main>
</template>

<style scoped>
:global(*) {
  box-sizing: border-box;
}

:global(body) {
  margin: 0;
  color: #18324b;
  background: #edf5f8;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
}

.operators-page {
  min-height: 100vh;
  padding: clamp(0.75rem, 3vw, 2rem);
}

.operators-card {
  width: min(100%, 58rem);
  margin: 0 auto;
  padding: clamp(1.25rem, 4vw, 2.5rem);
  background: #ffffff;
  border: 1px solid #d6e5ea;
  border-radius: 1.25rem;
  box-shadow: 0 1.5rem 4rem rgb(24 50 75 / 10%);
}

.page-header,
.list-actions,
.operator-row,
.operator-states,
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.page-header {
  margin-bottom: 1.5rem;
}

.eyebrow {
  margin: 0 0 0.45rem;
  color: #0d7286;
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  color: #102a43;
  font-size: clamp(1.8rem, 5vw, 2.5rem);
}

.page-header p:last-child {
  margin: 0.5rem 0 0;
  color: #5c7487;
}

.list-actions {
  justify-content: flex-start;
  margin: 1.25rem 0;
}

.page-summary {
  color: #5c7487;
}

.pagination {
  flex-wrap: wrap;
  justify-content: flex-start;
  margin-top: 1.25rem;
}

.operator-states {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.operator-list {
  display: grid;
  gap: 0.75rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.operator-row {
  padding: 1rem;
  background: #f7fafb;
  border: 1px solid #d6e5ea;
  border-radius: 0.75rem;
}

.operator-identity {
  display: grid;
  gap: 0.3rem;
  min-width: 0;
}

.operator-identity a {
  color: #0b6478;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.operator-identity span {
  color: #5c7487;
  overflow-wrap: anywhere;
}

.state {
  flex: 0 0 auto;
  padding: 0.35rem 0.65rem;
  border-radius: 999px;
  font-size: 0.85rem;
  font-weight: 700;
}

.state.acceso_habilitado {
  color: #23613a;
  background: #e5f5e9;
}

.state.inactivo {
  color: #7b3333;
  background: #fff0ed;
}

.state.pendiente_activacion {
  color: #805b16;
  background: #fff4d7;
}

.button {
  display: inline-flex;
  min-height: 2.75rem;
  align-items: center;
  justify-content: center;
  padding: 0.65rem 0.95rem;
  border: 0;
  border-radius: 0.55rem;
  font: inherit;
  font-weight: 700;
  text-decoration: none;
  cursor: pointer;
}

.button:disabled {
  cursor: wait;
  opacity: 0.65;
}

.secondary {
  color: #244a66;
  background: #e4eef2;
}

.secondary:hover,
.secondary:focus-visible {
  background: #d6e5ea;
}

.notice {
  margin: 1rem 0;
  padding: 0.9rem 1rem;
  border: 1px solid #d6e5ea;
  border-radius: 0.7rem;
}

.notice.error {
  color: #7b3333;
  background: #fff5f3;
  border-color: #edc2ba;
}

@media (max-width: 38rem) {
  .page-header,
  .operator-row,
  .operator-states {
    align-items: flex-start;
    flex-direction: column;
  }

  .list-actions {
    flex-wrap: wrap;
  }
}
</style>
