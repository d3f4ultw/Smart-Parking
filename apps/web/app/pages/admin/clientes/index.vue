<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'

import {
  etiquetaEstadoMembresia,
  formatearFechaMembresia,
  formatearPrecioMembresia,
  mapearErrorClientes,
  obtenerEstadoErrorClientes,
  obtenerPaginaSolicitadaClientes,
  type DetalleMembresiaCliente,
  type RespuestaListaClientes,
} from '~/utils/clientes-membresias'

definePageMeta({
  layout: 'admin',
  middleware: 'sesion-owner',
})

type ResultadoCarga =
  | { tipo: 'exito'; lista: RespuestaListaClientes }
  | { tipo: 'error'; codigo: number | undefined; mensaje: string }

const route = useRoute()
const router = useRouter()
const { listarClientes, consultarDetalle } = useClientesMembresias()
const { limpiarSesion } = useSesion()
const dialogoDetalle = ref<HTMLDialogElement | null>(null)
const botonDetalle = ref<HTMLButtonElement | null>(null)
const codigoClienteCargando = ref<string | null>(null)
const codigoClienteDetalle = ref<string | null>(null)
const detalle = ref<DetalleMembresiaCliente | null>(null)
const cargandoDetalle = ref(false)
const errorDetalle = ref('')
const paginaSolicitada = computed(() =>
  obtenerPaginaSolicitadaClientes(route.query.pagina),
)

function listaVacia(): RespuestaListaClientes {
  return {
    clientes: [],
    pagina: 1,
    tamano_pagina: 10,
    total: 0,
    total_paginas: 0,
  }
}

const carga = await useAsyncData<ResultadoCarga>(
  'admin-clientes-membresias-lista',
  async (_nuxtApp, { signal }): Promise<ResultadoCarga> => {
    try {
      return {
        tipo: 'exito',
        lista: await listarClientes(paginaSolicitada.value, signal),
      }
    } catch (error: unknown) {
      const codigo = obtenerEstadoErrorClientes(error)
      return {
        tipo: 'error',
        codigo,
        mensaje: mapearErrorClientes(codigo, 'leer'),
      }
    }
  },
  {
    default: (): ResultadoCarga => ({ tipo: 'exito', lista: listaVacia() }),
    dedupe: 'cancel',
    watch: [paginaSolicitada],
  },
)

const lista = computed(() =>
  carga.data.value?.tipo === 'exito' ? carga.data.value.lista : listaVacia(),
)
const mensajeErrorCarga = computed(() =>
  carga.data.value?.tipo === 'error' ? carga.data.value.mensaje : '',
)
const paginasVisibles = computed(() => Math.max(1, lista.value.total_paginas))

async function redirigirSesionInvalida(error: unknown): Promise<boolean> {
  if (obtenerEstadoErrorClientes(error) !== 401) {
    return false
  }
  limpiarSesion()
  clearNuxtData()
  await navigateTo('/login', { replace: true })
  return true
}

async function cambiarPagina(pagina: number) {
  if (pagina < 1 || pagina > paginasVisibles.value || carga.pending.value) {
    return
  }
  await router.push({
    path: route.path,
    query: pagina === 1 ? {} : { ...route.query, pagina: String(pagina) },
  })
}

async function abrirDetalle(codigoCliente: string, boton: HTMLButtonElement) {
  if (cargandoDetalle.value || dialogoDetalle.value === null || dialogoDetalle.value.open) {
    return
  }
  botonDetalle.value = boton
  codigoClienteCargando.value = codigoCliente
  codigoClienteDetalle.value = codigoCliente
  detalle.value = null
  errorDetalle.value = ''
  cargandoDetalle.value = true
  dialogoDetalle.value.showModal()
  try {
    detalle.value = await consultarDetalle(codigoCliente)
  } catch (error: unknown) {
    if (await redirigirSesionInvalida(error)) {
      return
    }
    errorDetalle.value = mapearErrorClientes(
      obtenerEstadoErrorClientes(error),
      'detalle',
    )
  } finally {
    cargandoDetalle.value = false
    codigoClienteCargando.value = null
  }
}

function cerrarDetalle() {
  dialogoDetalle.value?.close()
}

async function restaurarFoco() {
  await nextTick()
  botonDetalle.value?.focus()
}
</script>

<template>
  <section class="page-shell" aria-labelledby="page-title">
    <header class="page-heading">
      <div>
        <p class="eyebrow">GESTIÓN</p>
        <h1 id="page-title">Clientes y membresías</h1>
        <p class="page-description">
          Consulta el estado de las membresías confirmadas por Stripe.
        </p>
      </div>
      <span class="count-chip">{{ lista.total }} clientes</span>
    </header>

    <section class="panel" aria-labelledby="table-title">
      <div class="panel-heading">
        <div>
          <h2 id="table-title">Clientes</h2>
          <p>El registro se crea después de confirmar el primer pago.</p>
        </div>
      </div>

      <div v-if="carga.pending.value && lista.clientes.length === 0" class="notice" role="status">
        Cargando clientes…
      </div>
      <div v-else-if="mensajeErrorCarga" class="notice notice-error" role="alert">
        <span>{{ mensajeErrorCarga }}</span>
        <button class="button-secondary" type="button" @click="carga.refresh()">
          Reintentar
        </button>
      </div>
      <div v-else-if="lista.clientes.length === 0" class="empty-state">
        <span class="empty-icon" aria-hidden="true">C</span>
        <h3>Aún no hay clientes</h3>
        <p>Los clientes aparecerán cuando Stripe confirme el primer pago de una membresía.</p>
      </div>
      <div v-else class="table-scroll" :aria-busy="carga.pending.value">
        <table>
          <thead>
            <tr>
              <th scope="col">Código</th>
              <th scope="col">Nombre</th>
              <th scope="col">Membresía</th>
              <th scope="col"><span class="sr-only">Acciones</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="cliente in lista.clientes" :key="cliente.codigo_cliente">
              <td class="code-cell">{{ cliente.codigo_cliente }}</td>
              <td class="name-cell">{{ cliente.nombre_completo }}</td>
              <td>
                <span class="status-pill" :class="`status-${cliente.estado_membresia}`">
                  <span class="status-dot" aria-hidden="true" />
                  {{ etiquetaEstadoMembresia(cliente.estado_membresia) }}
                </span>
              </td>
              <td class="action-cell">
                <button
                  class="text-button"
                  type="button"
                  :disabled="cargandoDetalle"
                  :aria-busy="codigoClienteCargando === cliente.codigo_cliente"
                  :aria-label="`Ver detalles de ${cliente.nombre_completo}`"
                  @click="abrirDetalle(cliente.codigo_cliente, $event.currentTarget as HTMLButtonElement)"
                >
                  {{ codigoClienteCargando === cliente.codigo_cliente ? 'Cargando…' : 'Ver detalles' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <footer v-if="lista.total_paginas > 1" class="pagination-footer" aria-label="Paginación de clientes">
        <span>Página {{ lista.pagina }} de {{ lista.total_paginas }}</span>
        <div class="pagination-actions">
          <button
            class="button-secondary"
            type="button"
            :disabled="lista.pagina <= 1 || carga.pending.value"
            @click="cambiarPagina(lista.pagina - 1)"
          >
            Anterior
          </button>
          <button
            class="button-secondary"
            type="button"
            :disabled="lista.pagina >= lista.total_paginas || carga.pending.value"
            @click="cambiarPagina(lista.pagina + 1)"
          >
            Siguiente
          </button>
        </div>
      </footer>
    </section>

    <dialog
      ref="dialogoDetalle"
      class="detail-dialog"
      aria-labelledby="detail-title"
      @close="restaurarFoco"
      @cancel="cerrarDetalle"
    >
      <form method="dialog" class="dialog-close-form">
        <button class="dialog-close" aria-label="Cerrar detalle">×</button>
      </form>
      <div class="dialog-content">
        <p class="eyebrow">MEMBRESÍA</p>
        <h2 id="detail-title">Detalle de {{ codigoClienteDetalle ?? 'cliente' }}</h2>
        <p class="dialog-description">Información vigente de la suscripción.</p>

        <div class="detail-body" :aria-busy="cargandoDetalle">
          <div v-if="cargandoDetalle" class="notice" role="status">Cargando detalle…</div>
          <div v-else-if="errorDetalle" class="notice notice-error" role="alert">
            <span>{{ errorDetalle }}</span>
            <button class="button-secondary" type="button" @click="cerrarDetalle">Cerrar</button>
          </div>
          <dl v-else-if="detalle" class="detail-grid">
            <div>
              <dt>Plan</dt>
              <dd>{{ detalle.plan }}</dd>
            </div>
            <div>
              <dt>Precio</dt>
              <dd>{{ formatearPrecioMembresia(detalle.monto_centavos, detalle.moneda) }} / mes</dd>
            </div>
            <div>
              <dt>Inicio</dt>
              <dd>{{ formatearFechaMembresia(detalle.fecha_inicio) }}</dd>
            </div>
            <div>
              <dt>Próxima renovación</dt>
              <dd>{{ formatearFechaMembresia(detalle.proxima_renovacion) }}</dd>
            </div>
            <div class="detail-status">
              <dt>Estado</dt>
              <dd>
                <span class="status-pill" :class="`status-${detalle.estado}`">
                  <span class="status-dot" aria-hidden="true" />
                  {{ etiquetaEstadoMembresia(detalle.estado) }}
                </span>
              </dd>
            </div>
          </dl>
        </div>

      </div>
    </dialog>
  </section>
</template>

<style scoped>
.page-shell { display: grid; gap: 1.4rem; max-width: 76rem; margin: 0 auto; padding: 2rem clamp(1rem, 3vw, 2.5rem) 3rem; color: #211d28; font-family: Manrope, sans-serif; }
.page-heading, .panel-heading, .pagination-footer, .pagination-actions, .notice { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.page-heading { align-items: flex-end; }
.eyebrow { margin: 0 0 .45rem; color: #7b7185; font-size: .68rem; font-weight: 800; letter-spacing: .12em; }
h1, h2, h3, p { margin-top: 0; }
h1 { margin-bottom: .35rem; font-size: clamp(1.6rem, 3vw, 2.15rem); letter-spacing: -.045em; }
.page-description, .panel-heading p, .dialog-description { margin-bottom: 0; color: #746e7b; font-size: .88rem; }
.count-chip { flex: none; padding: .45rem .75rem; border: 1px solid #e7e1ec; border-radius: 999px; background: #fbfafc; color: #554965; font-size: .76rem; font-weight: 750; }
.panel { overflow: hidden; border: 1px solid #e8e3eb; border-radius: 1rem; background: #fff; box-shadow: 0 10px 30px rgb(31 20 42 / 4%); }
.panel-heading { min-height: 5rem; padding: 1.15rem 1.35rem; border-bottom: 1px solid #eeeaf1; }
.panel-heading h2 { margin-bottom: .3rem; font-size: 1rem; }
.panel-heading p { font-size: .78rem; }
.table-scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; text-align: left; }
th { padding: .8rem 1.25rem; background: #faf9fb; color: #756d7c; font-size: .67rem; font-weight: 800; letter-spacing: .07em; text-transform: uppercase; }
td { padding: .95rem 1.25rem; border-top: 1px solid #f0edf2; font-size: .84rem; }
tbody tr:hover { background: #fcfbfd; }
.code-cell { color: #665578; font-variant-numeric: tabular-nums; font-weight: 800; }
.name-cell { min-width: 14rem; font-weight: 650; }
.action-cell { text-align: right; }
.text-button { padding: .35rem .55rem; border: 0; border-radius: .4rem; background: transparent; color: #6a4292; font: inherit; font-size: .78rem; font-weight: 750; cursor: pointer; }
.text-button:hover { background: #f5eff9; }
.text-button:disabled { color: #827b88; cursor: wait; }
.status-pill { display: inline-flex; align-items: center; gap: .4rem; padding: .3rem .55rem; border: 1px solid transparent; border-radius: 999px; font-size: .7rem; font-weight: 750; white-space: nowrap; }
.status-dot { width: .42rem; height: .42rem; border-radius: 50%; background: currentColor; }
.status-activa { border-color: #c8e7d3; background: #eff9f2; color: #267044; }
.status-cancelacion_programada { border-color: #efd7aa; background: #fff8e9; color: #90620a; }
.status-pago_vencido { border-color: #f1c9b9; background: #fff2ed; color: #a64d2c; }
.status-cancelada, .status-inactiva { border-color: #e4dfe8; background: #f7f5f8; color: #6c6672; }
.status-pendiente { border-color: #d9d0ed; background: #f5f1fc; color: #6a5191; }
.notice { min-height: 4rem; justify-content: flex-start; padding: 1rem 1.3rem; color: #625b68; font-size: .84rem; }
.notice-error { color: #a44333; }
.empty-state { display: grid; justify-items: center; padding: 3.2rem 1.5rem; text-align: center; }
.empty-icon { display: grid; width: 2.6rem; height: 2.6rem; margin-bottom: 1rem; place-items: center; border: 1px solid #e4d9ed; border-radius: .8rem; background: #f7f2fb; color: #755292; font-weight: 800; }
.empty-state h3 { margin-bottom: .35rem; font-size: .98rem; }
.empty-state p { max-width: 28rem; margin-bottom: 0; color: #77717d; font-size: .82rem; line-height: 1.55; }
.pagination-footer { padding: .9rem 1.25rem; border-top: 1px solid #eeeaf1; color: #6c6572; font-size: .77rem; }
.pagination-actions { justify-content: flex-end; }
.button-secondary { padding: .48rem .75rem; border: 1px solid #ded8e4; border-radius: .55rem; background: #fff; color: #463d4f; font: inherit; font-size: .76rem; font-weight: 700; cursor: pointer; }
.button-secondary:hover:not(:disabled) { border-color: #c4b3d3; background: #fbf8fd; }
.button-secondary:disabled { color: #aaa4ae; cursor: not-allowed; }
.detail-dialog { width: min(100% - 2rem, 37rem); max-height: min(90dvh, 48rem); padding: 0; border: 1px solid #e3dce8; border-radius: 1rem; color: #211d28; box-shadow: 0 20px 60px rgb(24 17 32 / 22%); }
.detail-dialog::backdrop { background: rgb(23 17 29 / 46%); }
.dialog-close-form { display: flex; justify-content: flex-end; padding: .6rem .65rem 0; }
.dialog-close { display: grid; width: 2.2rem; height: 2.2rem; place-items: center; border: 0; border-radius: .6rem; background: transparent; color: #746d7b; font-size: 1.4rem; cursor: pointer; }
.dialog-content { padding: .1rem 1.5rem 1.5rem; }
.dialog-content h2 { margin-bottom: .35rem; font-size: 1.2rem; }
.detail-body { display: flex; min-height: 15rem; align-items: center; margin-top: 1.35rem; }
.detail-body > * { width: 100%; }
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .85rem; margin: 0; }
.detail-grid > div { min-width: 0; padding: .8rem; border: 1px solid #eee9f1; border-radius: .65rem; background: #fcfbfd; }
.detail-grid dt { margin-bottom: .35rem; color: #776f7e; font-size: .7rem; font-weight: 700; }
.detail-grid dd { margin: 0; color: #30283a; font-size: .85rem; font-weight: 750; }
.detail-status { grid-column: 1 / -1; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; clip-path: inset(50%); }
@media (max-width: 42rem) { .page-heading { align-items: flex-start; flex-direction: column; } th, td { padding: .8rem .75rem; } .detail-grid { grid-template-columns: minmax(0, 1fr); } .detail-status { grid-column: auto; } .pagination-footer { align-items: flex-start; flex-direction: column; } .pagination-actions { width: 100%; } }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } }
</style>
