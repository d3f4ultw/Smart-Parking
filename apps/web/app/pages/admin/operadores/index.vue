<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'

import {
  usarEventosTiempoReal,
  type EstadoEventosTiempoReal,
} from '~/utils/eventos-tiempo-real'
import { obtenerEstadoErrorOperador } from '~/utils/operadores'
import {
  compararCursoresEventos,
  crearRegistroCreacionesOperador,
  crearReconciliadorOperadores,
  puedeInsertarCreacionEnPagina,
} from '~/utils/operadores-tiempo-real'
import { crearDebounceBusquedaOperadores } from '~/utils/busqueda-operadores'
import {
  etiquetaCreadorOperador,
  etiquetaEstadoCuentaOperador,
  formatearCreacionOperador,
  obtenerPaginaSolicitadaOperadores,
  mapearErrorGestionOperador,
  type Operador,
  type RespuestaListaOperadores,
} from '~/utils/gestion-operadores'

definePageMeta({
  layout: 'admin',
  middleware: 'sesion-admin',
})

const CLAVE_LISTA_OPERADORES = 'admin-operadores-lista'
const COLUMNAS_SKELETON = [1, 2, 3, 4, 5, 6] as const
const route = useRoute()
const router = useRouter()
const { listarOperadores, obtenerOperador } = useOperadores()
const { limpiarSesion } = useSesion()
const { mostrarToast, limpiarToasts } = useAdminToasts()
const eventosTiempoReal = usarEventosTiempoReal()
const mensajeError = ref('')
const busqueda = ref('')
const buscarServidor = ref('')
const filtroEstado = ref<'todos' | 'activos' | 'inactivos'>('todos')
const paginaForzadaBusqueda = ref(false)
const dialogoCrearAbierto = ref(false)
const operadorDetalleId = ref<string | null>(null)
const idsCargando = ref(new Set<number>())
const idsAccionOcupada = ref(new Set<number>())
const idsCreacionTemporal = ref(new Set<number>())
const creacionesProcesadas = crearRegistroCreacionesOperador()
const estadoStream = eventosTiempoReal.estado
const paginaSolicitada = computed(() =>
  paginaForzadaBusqueda.value
    ? 1
    : obtenerPaginaSolicitadaOperadores(route.query.pagina),
)
const dialogoDetalleAbierto = computed(() => operadorDetalleId.value !== null)
const paginaConsultaCompletada = ref(paginaSolicitada.value)

const { data, error, pending, refresh } = await useAsyncData<RespuestaListaOperadores>(
  CLAVE_LISTA_OPERADORES,
  async (_nuxtApp, { signal }) => {
    const pagina = paginaSolicitada.value
    const buscar = buscarServidor.value
    const respuesta = await listarOperadores(pagina, signal, buscar || undefined)
    if (!signal.aborted) {
      paginaConsultaCompletada.value = pagina
    }
    return respuesta
  },
  {
    default: () => ({
      operadores: [],
      pagina: 1,
      tamano_pagina: 10,
      total: 0,
      total_paginas: 0,
      cursor_eventos: '0',
    }),
    dedupe: 'cancel',
    watch: [paginaSolicitada, buscarServidor],
  },
)

const paginaActual = computed(() => data.value.pagina)
const cambiandoPagina = computed(
  () => pending.value && paginaSolicitada.value !== paginaActual.value,
)
const paginaMostrada = computed(
  () => cambiandoPagina.value ? paginaSolicitada.value : paginaActual.value,
)
const filasEsqueletoPagina = computed(() => {
  const filasRestantes = data.value.total
    - ((paginaSolicitada.value - 1) * data.value.tamano_pagina)
  const cantidad = Math.max(1, Math.min(data.value.tamano_pagina, filasRestantes))
  return Array.from({ length: cantidad }, (_, indice) => indice)
})
const operadoresFiltrados = computed(() => {
  return data.value.operadores.filter((operador) => {
    const coincideEstado = filtroEstado.value === 'todos'
      || (filtroEstado.value === 'activos' && operador.esta_activo)
      || (filtroEstado.value === 'inactivos' && !operador.esta_activo)

    return coincideEstado
  })
})

type FilaVisibleOperador =
  | { tipo: 'operador'; id: number; operador: Operador }
  | { tipo: 'esqueleto'; id: number }

const filasVisibles = computed<FilaVisibleOperador[]>(() => {
  const idsOperadores = new Set(data.value.operadores.map((operador) => operador.id))
  const filas: FilaVisibleOperador[] = operadoresFiltrados.value.map((operador) => ({
    tipo: 'operador',
    id: operador.id,
    operador,
  }))
  const mostrarEsqueletosTemporales =
    busqueda.value.trim().length === 0
    && buscarServidor.value.length === 0
    && filtroEstado.value === 'todos'

  for (const id of idsCreacionTemporal.value) {
    if (mostrarEsqueletosTemporales && !idsOperadores.has(id)) {
      filas.push({ tipo: 'esqueleto', id })
    }
  }
  return filas.sort((a, b) => a.id - b.id)
})

const idsOcupados = computed(() => new Set([
  ...idsCargando.value,
  ...idsAccionOcupada.value,
]))
const busquedaPendiente = computed(() => busqueda.value.trim() !== buscarServidor.value)
const ariaBusy = computed(
  () => pending.value || busquedaPendiente.value || idsOcupados.value.size > 0,
)
const etiquetaEstadoStream = computed(() => {
  const etiquetas: Record<EstadoEventosTiempoReal, string> = {
    conectando: 'Conectando actualizaciones en tiempo real…',
    conectado: 'Actualizaciones en tiempo real conectadas',
    reconectando: 'Reconectando actualizaciones en tiempo real…',
    'verificando-sesion': 'Verificando la sesión para reconectar…',
    'sesion-perdida': 'La sesión ADMIN terminó.',
    detenido: 'Actualizaciones en tiempo real detenidas',
  }
  return etiquetas[estadoStream.value]
})

function cambiarPresenciaId(
  conjunto: typeof idsCargando,
  id: number,
  presente: boolean,
) {
  const nuevosIds = new Set(conjunto.value)
  if (presente) {
    nuevosIds.add(id)
  } else {
    nuevosIds.delete(id)
  }
  conjunto.value = nuevosIds
}

function cambiarPagina(pagina: number) {
  const nuevaPagina = Math.min(Math.max(1, pagina), data.value.total_paginas)
  return router.push({
    path: '/admin/operadores',
    query: nuevaPagina > 1 ? { pagina: String(nuevaPagina) } : {},
  })
}

function consultaConModal(modal?: 'crear' | 'detalle', operadorId?: string) {
  return {
    ...(paginaActual.value > 1 ? { pagina: String(paginaActual.value) } : {}),
    ...(modal ? { modal } : {}),
    ...(modal === 'detalle' && operadorId ? { operador: operadorId } : {}),
  }
}

function consultaModalActual() {
  if (route.query.modal === 'crear') {
    return { modal: 'crear' }
  }
  if (route.query.modal === 'detalle' && typeof route.query.operador === 'string') {
    return { modal: 'detalle', operador: route.query.operador }
  }
  return {}
}

function aplicarBusquedaEfectiva(consulta: string) {
  if (consulta === buscarServidor.value) {
    return
  }

  const reiniciarPagina = obtenerPaginaSolicitadaOperadores(route.query.pagina) > 1
  if (reiniciarPagina) {
    paginaForzadaBusqueda.value = true
  }
  buscarServidor.value = consulta

  if (reiniciarPagina) {
    void router.replace({
      path: '/admin/operadores',
      query: consultaModalActual(),
    }).then(
      () => {
        paginaForzadaBusqueda.value = false
      },
      () => {
        paginaForzadaBusqueda.value = false
      },
    )
  }
}

const debounceBusqueda = crearDebounceBusquedaOperadores(aplicarBusquedaEfectiva)

function abrirDialogoCrear() {
  dialogoCrearAbierto.value = true
  operadorDetalleId.value = null
  void router.push({ path: '/admin/operadores', query: consultaConModal('crear') })
}

function actualizarDialogoCrear(abierto: boolean) {
  dialogoCrearAbierto.value = abierto
  if (!abierto && route.query.modal === 'crear') {
    void router.replace({
      path: '/admin/operadores',
      query: consultaConModal(),
    })
  }
}

function abrirDialogoDetalle(operadorId: number) {
  dialogoCrearAbierto.value = false
  const operadorIdSeleccionado = String(operadorId)
  operadorDetalleId.value = operadorIdSeleccionado
  void router.push({
    path: '/admin/operadores',
    query: consultaConModal('detalle', operadorIdSeleccionado),
  })
}

function actualizarDialogoDetalle(abierto: boolean) {
  if (abierto) {
    return
  }
  operadorDetalleId.value = null
  if (route.query.modal === 'detalle') {
    void router.replace({
      path: '/admin/operadores',
      query: consultaConModal(),
    })
  }
}

function estaEnPaginaActual(id: number): boolean {
  return data.value.operadores.some((operador) => operador.id === id)
}

function puedeAparecerEnPaginaActual(id: number): boolean {
  return puedeInsertarCreacionEnPagina(
    id,
    data.value.pagina,
    data.value.total_paginas,
    data.value.tamano_pagina,
    data.value.operadores,
  )
}

function aplicarOperadorReconciliado(operador: Operador, permiteInsertar: boolean) {
  const operadores = data.value.operadores
  const indice = operadores.findIndex((actual) => actual.id === operador.id)
  if (indice >= 0) {
    const actualizados = [...operadores]
    actualizados[indice] = operador
    data.value = { ...data.value, operadores: actualizados }
    return
  }
  if (!permiteInsertar || !puedeAparecerEnPaginaActual(operador.id)) {
    return
  }
  data.value = {
    ...data.value,
    operadores: [...operadores, operador].sort((a, b) => a.id - b.id),
  }
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

const reconciliador = crearReconciliadorOperadores({
  obtenerOperador: (id, signal) => obtenerOperador(id, signal),
  alCambiarCarga: (id, cargando) => {
    cambiarPresenciaId(idsCargando, id, cargando)
    if (!cargando) {
      cambiarPresenciaId(idsCreacionTemporal, id, false)
    }
  },
  alRecibirOperador: aplicarOperadorReconciliado,
  alFallar: (_id, errorActual) => {
    void atenderError(errorActual)
  },
})

function operadorCreado() {
  mensajeError.value = ''
  mostrarToast('Operador creado. Se envió una invitación para activar la cuenta.')
}

type EventoPendienteOperador =
  | { tipo: 'actualizado'; id: number }
  | { tipo: 'creado'; id: number; cursorEvento: string }

const eventosDuranteCarga = ref<EventoPendienteOperador[]>([])
let temporizadorRefrescoBusqueda: ReturnType<typeof setTimeout> | null = null
let refrescoBusquedaSolicitado = false

function procesarCreacionOperador(id: number, cursorEvento: string) {
  const yaVisible = estaEnPaginaActual(id)
  if (
    !yaVisible
    && compararCursoresEventos(cursorEvento, data.value.cursor_eventos) > 0
  ) {
    const total = data.value.total + 1
    data.value = {
      ...data.value,
      total,
      total_paginas: Math.ceil(total / data.value.tamano_pagina),
    }
  }

  if (yaVisible) {
    void reconciliador.reconciliar(id)
    return
  }
  if (!puedeAparecerEnPaginaActual(id)) {
    return
  }
  cambiarPresenciaId(idsCreacionTemporal, id, true)
  void reconciliador.reconciliar(id, true)
}

function manejarCreacionOperador(id: number, cursorEvento: string) {
  if (!creacionesProcesadas.aceptar(id)) {
    return
  }
  if (buscarServidor.value.length > 0) {
    programarRefrescoBusquedaActiva()
    return
  }
  if (pending.value || paginaSolicitada.value !== data.value.pagina) {
    eventosDuranteCarga.value = [
      ...eventosDuranteCarga.value,
      { tipo: 'creado', id, cursorEvento },
    ]
    return
  }
  procesarCreacionOperador(id, cursorEvento)
}

function manejarActualizacionOperador(id: number) {
  if (pending.value || paginaSolicitada.value !== data.value.pagina) {
    eventosDuranteCarga.value = [
      ...eventosDuranteCarga.value,
      { tipo: 'actualizado', id },
    ]
    return
  }
  if (estaEnPaginaActual(id) || idsCreacionTemporal.value.has(id)) {
    void reconciliador.reconciliar(id, idsCreacionTemporal.value.has(id))
  }
}

function reconciliarOperador(id: number) {
  if (!estaEnPaginaActual(id)) {
    return
  }
  void reconciliador.reconciliar(id)
}

function cambiarAccionOperador(id: number, ocupada: boolean) {
  cambiarPresenciaId(idsAccionOcupada, id, ocupada)
}

let recuperacionResync: Promise<void> | null = null
async function recuperarPaginaActual(): Promise<void> {
  if (recuperacionResync !== null) {
    return recuperacionResync
  }
  recuperacionResync = (async () => {
    mensajeError.value = ''
    reconciliador.suspenderYDescartar()
    idsCreacionTemporal.value = new Set()
    try {
      await refresh()
    } finally {
      reconciliador.reanudar()
    }
  })()
  try {
    await recuperacionResync
  } finally {
    recuperacionResync = null
    if (refrescoBusquedaSolicitado) {
      refrescoBusquedaSolicitado = false
      programarRefrescoBusquedaActiva()
    }
  }
}

function programarRefrescoBusquedaActiva() {
  if (buscarServidor.value.length === 0) {
    refrescoBusquedaSolicitado = false
    if (temporizadorRefrescoBusqueda !== null) {
      clearTimeout(temporizadorRefrescoBusqueda)
      temporizadorRefrescoBusqueda = null
    }
    return
  }

  if (
    pending.value
    || paginaSolicitada.value !== data.value.pagina
    || recuperacionResync !== null
  ) {
    refrescoBusquedaSolicitado = true
    return
  }
  if (temporizadorRefrescoBusqueda !== null) {
    return
  }

  temporizadorRefrescoBusqueda = setTimeout(() => {
    temporizadorRefrescoBusqueda = null
    if (
      buscarServidor.value.length === 0
      || pending.value
      || paginaSolicitada.value !== data.value.pagina
      || recuperacionResync !== null
    ) {
      refrescoBusquedaSolicitado = buscarServidor.value.length > 0
      return
    }
    refrescoBusquedaSolicitado = false
    void recuperarPaginaActual()
  }, 150)
}

const suscripcionEventos = eventosTiempoReal.suscribir(
  data.value.cursor_eventos,
  {
    alActualizarOperador: manejarActualizacionOperador,
    alCrearOperador: manejarCreacionOperador,
    alResync: recuperarPaginaActual,
  },
)

watch(() => data.value.cursor_eventos, (cursor) => {
  suscripcionEventos.actualizarCursor(cursor)
})

if (error.value) {
  await atenderError(error.value)
}

watch(error, (errorActual) => {
  if (errorActual) {
    void atenderError(errorActual)
  }
})

watch(busqueda, (texto) => {
  const consulta = texto.trim()
  if (consulta === buscarServidor.value) {
    debounceBusqueda.cancelar()
    return
  }
  if (consulta.length === 0) {
    debounceBusqueda.cancelar()
    aplicarBusquedaEfectiva('')
    return
  }
  debounceBusqueda.programar(consulta)
})

watch([paginaSolicitada, buscarServidor], () => {
  mensajeError.value = ''
  reconciliador.suspenderYDescartar()
})

watch([pending, error], ([estaPendiente]) => {
  if (!estaPendiente && recuperacionResync === null) {
    reconciliador.reanudar()
  }
  if (!estaPendiente && eventosDuranteCarga.value.length > 0) {
    const eventos = eventosDuranteCarga.value
    eventosDuranteCarga.value = []
    for (const evento of eventos) {
      if (evento.tipo === 'creado') {
        if (buscarServidor.value.length > 0) {
          programarRefrescoBusquedaActiva()
        } else {
          procesarCreacionOperador(evento.id, evento.cursorEvento)
        }
      } else {
        manejarActualizacionOperador(evento.id)
      }
    }
  }
  if (
    !estaPendiente
    && recuperacionResync === null
    && refrescoBusquedaSolicitado
  ) {
    refrescoBusquedaSolicitado = false
    programarRefrescoBusquedaActiva()
  }
})

watch(filtroEstado, () => {
  limpiarToasts()
})

watch([() => route.query.modal, () => route.query.operador], ([modal, operadorId]) => {
  dialogoCrearAbierto.value = modal === 'crear'
  operadorDetalleId.value = modal === 'detalle' && typeof operadorId === 'string'
    ? operadorId
    : null
}, { immediate: true })

watch(
  [paginaConsultaCompletada, data, pending, error],
  ([paginaConsultada, respuesta, estaPendiente, errorActual]) => {
    const pagina = paginaSolicitada.value
    if (
      !import.meta.client
      || estaPendiente
      || errorActual
      || paginaForzadaBusqueda.value
      || paginaConsultada !== pagina
    ) {
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
        query: {
          ...(parametroEsperado ? { pagina: parametroEsperado } : {}),
          ...(route.query.modal === 'crear' ? { modal: 'crear' } : {}),
          ...(route.query.modal === 'detalle' && typeof route.query.operador === 'string'
            ? { modal: 'detalle', operador: route.query.operador }
            : {}),
        },
      })
    }
  },
  { flush: 'post', immediate: true },
)

onUnmounted(() => {
  debounceBusqueda.cancelar()
  if (temporizadorRefrescoBusqueda !== null) {
    clearTimeout(temporizadorRefrescoBusqueda)
  }
  suscripcionEventos.detener()
  reconciliador.detener()
  clearNuxtData(CLAVE_LISTA_OPERADORES)
})
</script>

<template>
  <main class="operators-page">
    <header class="page-header">
      <div>
        <p class="eyebrow">Smart Parking · Administración</p>
        <h1 id="operators-title">Administrar operadores</h1>
      </div>
      <button class="button primary create-button" type="button" @click="abrirDialogoCrear">
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
          <path d="M12 5v14M5 12h14" />
        </svg>
        Crear operador
      </button>
    </header>

    <div v-if="mensajeError" class="notice error" role="alert">
      {{ mensajeError }}
    </div>

    <section class="operators-panel" :aria-busy="ariaBusy" aria-labelledby="operators-title">
      <div class="panel-toolbar">
        <div>
          <h2>Operadores registrados</h2>
          <p class="stream-status" role="status">{{ etiquetaEstadoStream }}</p>
        </div>
      </div>

      <div class="filters" aria-label="Filtros de operadores">
        <label class="search-control" for="operator-search">
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
            <circle cx="10.8" cy="10.8" r="6.8" />
            <path d="m16 16 4.5 4.5" />
          </svg>
          <span class="sr-only">Buscar operadores</span>
          <input id="operator-search" v-model="busqueda" type="search" maxlength="320" placeholder="Buscar por nombre o correo">
        </label>
        <label class="status-filter" for="operator-status">
          <span>Estado</span>
          <select id="operator-status" v-model="filtroEstado">
            <option value="todos">Todos</option>
            <option value="activos">Activos</option>
            <option value="inactivos">Inactivos</option>
          </select>
        </label>
      </div>
      <p class="panel-copy">
        {{ data.total }} {{ data.total === 1 ? 'cuenta' : 'cuentas' }} ·
        Página {{ paginaMostrada }} de {{ Math.max(data.total_paginas, 1) }}
      </p>

      <p v-if="pending && data.total === 0" class="empty-state" role="status">
        Cargando operadores…
      </p>
      <p v-else-if="data.total === 0 && !mensajeError" class="empty-state" role="status">
        {{ buscarServidor ? 'No hay operadores que coincidan con la búsqueda.' : 'No hay cuentas de operador registradas.' }}
      </p>
      <template v-else-if="data.total > 0">
        <p v-if="cambiandoPagina" class="inline-status" role="status">Actualizando página…</p>
        <div v-if="!cambiandoPagina && filasVisibles.length === 0" class="empty-state" role="status">
          No hay operadores que coincidan con los filtros de esta página.
        </div>
        <div v-else class="table-scroll" tabindex="0" aria-label="Tabla desplazable de operadores">
          <table>
            <colgroup>
              <col class="operator-column">
              <col class="email-column">
              <col class="status-column">
              <col class="creator-column">
              <col class="created-column">
              <col class="actions-column">
            </colgroup>
            <thead>
              <tr>
                <th scope="col">Operador</th>
                <th scope="col">Correo electrónico</th>
                <th scope="col">Estado</th>
                <th scope="col">Creado por</th>
                <th scope="col">Fecha de creación</th>
                <th scope="col">Acciones</th>
              </tr>
            </thead>
            <tbody v-if="cambiandoPagina">
              <tr
                v-for="fila in filasEsqueletoPagina"
                :key="`pagina-${paginaSolicitada}-${fila}`"
                aria-busy="true"
              >
                <td v-for="columna in COLUMNAS_SKELETON" :key="columna">
                  <span
                    class="row-skeleton"
                    :class="`skeleton-column-${columna}`"
                    aria-hidden="true"
                  />
                </td>
              </tr>
            </tbody>
            <tbody v-else>
              <tr
                v-for="fila in filasVisibles"
                :key="`${fila.tipo}-${fila.id}`"
                :aria-busy="fila.tipo === 'esqueleto' || idsOcupados.has(fila.id)"
              >
                <template v-if="fila.tipo === 'esqueleto'">
                  <td v-for="columna in COLUMNAS_SKELETON" :key="columna">
                    <span
                      class="row-skeleton"
                      :class="`skeleton-column-${columna}`"
                      aria-hidden="true"
                    />
                  </td>
                </template>
                <template v-else>
                  <td>
                    <span class="operator-name">
                      {{ [fila.operador.nombre, fila.operador.apellido_paterno, fila.operador.apellido_materno].filter(Boolean).join(' ') || fila.operador.correo }}
                    </span>
                  </td>
                  <td class="operator-email">{{ fila.operador.correo }}</td>
                  <td>
                    <span class="state" :class="fila.operador.esta_activo ? 'active' : 'inactive'">
                      {{ etiquetaEstadoCuentaOperador(fila.operador.estado_cuenta) }}
                    </span>
                  </td>
                  <td class="creator-cell">
                    {{ etiquetaCreadorOperador(fila.operador.creado_por) }}
                  </td>
                  <td class="created-cell">
                    <time :datetime="fila.operador.creado_en">
                      {{ formatearCreacionOperador(fila.operador.creado_en) }}
                    </time>
                  </td>
                  <td class="action-cell">
                    <button
                      class="detail-link"
                      type="button"
                      @click="abrirDialogoDetalle(fila.operador.id)"
                    >
                      Ver detalle
                    </button>
                  </td>
                </template>
              </tr>
            </tbody>
          </table>
        </div>

        <nav v-if="data.total_paginas > 1" class="pagination" aria-label="Paginación de operadores">
          <button class="button secondary" type="button" :disabled="pending || paginaActual <= 1" @click="cambiarPagina(1)">
            Primera
          </button>
          <button class="button secondary" type="button" :disabled="pending || paginaActual <= 1" @click="cambiarPagina(paginaActual - 1)">
            Anterior
          </button>
          <span>Página {{ paginaMostrada }} de {{ data.total_paginas }}</span>
          <button class="button secondary" type="button" :disabled="pending || paginaActual >= data.total_paginas" @click="cambiarPagina(paginaActual + 1)">
            Siguiente
          </button>
          <button class="button secondary" type="button" :disabled="pending || paginaActual >= data.total_paginas" @click="cambiarPagina(data.total_paginas)">
            Última
          </button>
        </nav>
      </template>
    </section>

    <AdminCrearOperadorModal
      :model-value="dialogoCrearAbierto"
      @update:model-value="actualizarDialogoCrear"
      @created="operadorCreado"
    />
    <AdminGestionarOperadorModal
      v-if="operadorDetalleId"
      :key="operadorDetalleId"
      :model-value="dialogoDetalleAbierto"
      :operator-id="operadorDetalleId"
      @update:model-value="actualizarDialogoDetalle"
      @operator-state-changed="reconciliarOperador"
      @action-busy="cambiarAccionOperador"
    />
  </main>
</template>

<style scoped>
.operators-page {
  display: grid;
  min-width: 0;
  gap: 1.25rem;
}

.page-header,
.panel-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.page-header {
  align-items: center;
  margin-bottom: 0.4rem;
}

.eyebrow {
  margin: 0 0 0.4rem;
  color: #6b4a89;
  font-size: 0.7rem;
  font-weight: 750;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h1,
h2 {
  margin: 0;
  color: #29252f;
  letter-spacing: -0.035em;
}

h1 {
  font-size: clamp(1.65rem, 3vw, 2.15rem);
  line-height: 1.2;
}

h2 {
  font-size: 1rem;
}

.page-header p:last-child {
  margin: 0.5rem 0 0;
  color: #746f7b;
  font-size: 0.92rem;
}

.button {
  display: inline-flex;
  min-height: 2.7rem;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  gap: 0.55rem;
  padding: 0.6rem 0.85rem;
  border: 1px solid transparent;
  border-radius: 0.62rem;
  font: inherit;
  font-size: 0.84rem;
  font-weight: 700;
  text-decoration: none;
  cursor: pointer;
  transition: background-color 140ms ease, border-color 140ms ease, color 140ms ease;
}

.button svg {
  width: 1.05rem;
  height: 1.05rem;
}

.button:disabled {
  cursor: wait;
  opacity: 0.65;
}

.primary {
  color: #ffffff;
  background: #5c3a86;
  border-color: #5c3a86;
}

.primary:hover:not(:disabled) {
  background: #6c4a97;
  border-color: #6c4a97;
}

.secondary {
  color: #4e4556;
  background: #ffffff;
  border-color: #ded9e3;
}

.secondary:hover:not(:disabled) {
  color: #4d326f;
  background: #f8f6fa;
  border-color: #cfc1dc;
}

.operators-panel {
  min-width: 0;
  padding: clamp(1rem, 2.5vw, 1.5rem);
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 1rem;
  box-shadow: 0 0.75rem 2rem rgb(37 28 47 / 4%);
}

.panel-toolbar {
  align-items: center;
}

.panel-copy {
  margin: 0 0 0.85rem;
  color: #827c89;
  font-size: 0.82rem;
  text-align: right;
}

.stream-status {
  margin: 0.35rem 0 0;
  color: #827c89;
  font-size: 0.74rem;
}

.filters {
  display: flex;
  align-items: center;
  gap: 0.8rem;
  margin-top: 1.35rem;
}

.search-control {
  display: flex;
  min-width: min(100%, 20rem);
  min-height: 2.7rem;
  align-items: center;
  gap: 0.55rem;
  padding: 0 0.75rem;
  color: #827c89;
  background: #fdfcfe;
  border: 1px solid #ded9e3;
  border-radius: 0.62rem;
}

.search-control:focus-within {
  border-color: #76569a;
  outline: 3px solid rgb(92 58 134 / 16%);
  outline-offset: 1px;
}

.search-control svg {
  width: 1.05rem;
  height: 1.05rem;
  flex: 0 0 auto;
}

.search-control input {
  width: 100%;
  min-width: 0;
  color: #29252f;
  background: transparent;
  border: 0;
  outline: 0;
  font: inherit;
  font-size: 0.86rem;
}

.search-control input::placeholder {
  color: #98929f;
}

.search-control input:focus-visible {
  outline: 0;
}

.status-filter {
  display: flex;
  min-height: 2.7rem;
  align-items: center;
  gap: 0.55rem;
  color: #746f7b;
  font-size: 0.82rem;
  font-weight: 600;
}

.status-filter select {
  min-height: 2.7rem;
  padding: 0.55rem 2rem 0.55rem 0.7rem;
  color: #3c3542;
  background-color: #ffffff;
  border: 1px solid #ded9e3;
  border-radius: 0.62rem;
  font: inherit;
  font-size: 0.84rem;
}

.status-filter select:focus-visible {
  border-color: #76569a;
  outline: 3px solid rgb(92 58 134 / 16%);
  outline-offset: 1px;
}

.filter-note {
  margin: 0.45rem 0 1.1rem;
  color: #908a96;
  font-size: 0.76rem;
}

.table-scroll {
  width: 100%;
  overflow-x: auto;
  border: 1px solid #ece9ef;
  border-radius: 0.7rem;
}

.table-scroll:focus-visible {
  outline: 3px solid rgb(92 58 134 / 20%);
  outline-offset: 2px;
}

table {
  width: 100%;
  min-width: 62rem;
  table-layout: fixed;
  border-collapse: collapse;
  text-align: left;
}

.operator-column {
  width: 14%;
}

.email-column {
  width: 23%;
}

.status-column {
  width: 17%;
}

.creator-column {
  width: 16%;
}

.created-column {
  width: 19%;
}

.actions-column {
  width: 11%;
}

th {
  padding: 0.85rem 1rem;
  color: #746f7b;
  background: #faf9fb;
  border-bottom: 1px solid #e8e5eb;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

td {
  padding: 0.9rem 1rem;
  color: #403a46;
  border-bottom: 1px solid #f0edf2;
  font-size: 0.86rem;
  vertical-align: middle;
}

tbody tr:last-child td {
  border-bottom: 0;
}

.operator-name {
  display: block;
  color: #302b35;
  font-weight: 650;
  overflow-wrap: anywhere;
}

.operator-email {
  color: #746f7b;
  overflow-wrap: anywhere;
}

.creator-cell {
  color: #746f7b;
  overflow-wrap: anywhere;
}

.created-cell {
  color: #746f7b;
  white-space: nowrap;
}

.action-cell {
  padding-inline: 0.75rem;
  white-space: nowrap;
}

.row-skeleton {
  display: block;
  height: 1.05rem;
  border-radius: 0.3rem;
  background: linear-gradient(90deg, #eeeaf1 25%, #f7f5f8 50%, #eeeaf1 75%);
  background-size: 200% 100%;
  animation: operator-skeleton 1.35s ease-in-out infinite;
}

.skeleton-column-1,
.skeleton-column-4 {
  width: 72%;
}

.skeleton-column-2,
.skeleton-column-5 {
  width: 84%;
}

.skeleton-column-3 {
  width: 58%;
}

.skeleton-column-6 {
  width: 55%;
}

@keyframes operator-skeleton {
  to {
    background-position: -200% 0;
  }
}

.state {
  display: inline-flex;
  min-height: 1.65rem;
  align-items: center;
  padding: 0.25rem 0.55rem;
  color: #5c3a86;
  background: #f2edf6;
  border: 1px solid #e6dcec;
  border-radius: 999px;
  font-size: 0.74rem;
  font-weight: 700;
  white-space: nowrap;
}

.state.inactive {
  color: #69636f;
  background: #f3f2f4;
  border-color: #e4e1e7;
}

.detail-link {
  padding: 0;
  color: #5c3a86;
  background: transparent;
  border: 0;
  font: inherit;
  font-size: 0.82rem;
  font-weight: 700;
  text-align: left;
  cursor: pointer;
  white-space: nowrap;
}

.detail-link:hover {
  color: #6c4a97;
  text-decoration: underline;
  text-underline-offset: 0.15em;
}

.pagination {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 0.45rem;
  margin-top: 1.1rem;
}

.pagination span {
  margin: 0 0.35rem;
  color: #746f7b;
  font-size: 0.78rem;
}

.pagination .button {
  min-height: 2.4rem;
  padding: 0.5rem 0.65rem;
  font-size: 0.76rem;
}

.notice,
.empty-state {
  padding: 1rem;
  color: #514957;
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 0.75rem;
  font-size: 0.9rem;
  line-height: 1.5;
}

.notice.error {
  color: #67456e;
  background: #f8f5f9;
  border-color: #e6dce9;
}

.inline-status {
  padding: 0.8rem 0;
  color: #746f7b;
  font-size: 0.88rem;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  clip-path: inset(50%);
}

.button:focus-visible,
.detail-link:focus-visible {
  outline: 3px solid rgb(92 58 134 / 24%);
  outline-offset: 2px;
}

@media (max-width: 48rem) {
  .page-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .create-button {
    align-self: stretch;
  }

  .panel-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

}

@media (max-width: 38rem) {
  .filters {
    align-items: stretch;
    flex-direction: column;
  }

  .search-control {
    min-width: 0;
    width: 100%;
  }

  .status-filter {
    justify-content: space-between;
  }

  .status-filter select {
    flex: 1;
  }

  .pagination {
    justify-content: center;
  }

  .pagination span {
    order: -1;
    width: 100%;
    margin: 0 0 0.35rem;
    text-align: center;
  }
}

@media (prefers-reduced-motion: reduce) {
  .button {
    transition: none;
  }

  .row-skeleton {
    animation: none;
  }
}
</style>
