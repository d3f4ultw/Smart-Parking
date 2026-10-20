<script setup lang="ts">
import { computed, ref } from 'vue'

import { useClientesMembresias } from '~/composables/useClientesMembresias'
import { useSesionCliente } from '~/composables/useSesionCliente'
import {
  etiquetaEstadoMembresia,
  formatearFechaMembresia,
  formatearPrecioMembresia,
  obtenerEstadoErrorClientes,
  type PlanMembresia,
  type RespuestaMembresiaCliente,
} from '~/utils/clientes-membresias'
import { obtenerEstadoErrorSesionCliente } from '~/utils/sesion-cliente'

definePageMeta({
  layout: 'cliente',
  middleware: 'sesion-cliente',
})

type ResultadoCarga =
  | { tipo: 'exito'; membresia: RespuestaMembresiaCliente; plan: PlanMembresia | null }
  | { tipo: 'error'; codigo: number | undefined; mensaje: string }

const { consultarMembresiaCliente, consultarPlanes, crearCheckout } = useClientesMembresias()
const { limpiarSesion } = useSesionCliente()
const cargandoCheckout = ref(false)
const errorCheckout = ref('')
const claveIdempotencia = ref<string | null>(null)

useHead({
  title: 'Membresías | Cuenta de cliente',
  meta: [{ name: 'robots', content: 'noindex, nofollow, noarchive' }],
})

const carga = await useAsyncData<ResultadoCarga>(
  'cliente-membresia-y-plan',
  async (_nuxtApp, { signal }): Promise<ResultadoCarga> => {
    try {
      const [membresia, respuestaPlanes] = await Promise.all([
        consultarMembresiaCliente(signal),
        consultarPlanes(signal),
      ])
      const plan = respuestaPlanes.planes.find((elemento) => elemento.plan_id === 'mensual') ?? null
      return { tipo: 'exito', membresia, plan }
    } catch (error: unknown) {
      const codigo = obtenerEstadoErrorClientes(error)
      const mensaje = codigo === 401
        ? 'Tu sesión terminó. Inicia sesión nuevamente.'
        : 'No fue posible cargar tu membresía y el plan mensual.'
      return { tipo: 'error', codigo, mensaje }
    }
  },
  {
    default: (): ResultadoCarga => ({
      tipo: 'exito',
      membresia: {
        estado: 'sin_membresia',
        membresia: null,
        checkout_pendiente: false,
        puede_comprar: false,
      },
      plan: null,
    }),
    dedupe: 'cancel',
  },
)

const datos = computed(() => carga.data.value?.tipo === 'exito' ? carga.data.value : null)
const mensajeCarga = computed(() => carga.data.value?.tipo === 'error' ? carga.data.value.mensaje : '')
const etiquetaEstado = computed(() => datos.value
  ? etiquetaEstadoMembresia(datos.value.membresia.estado)
  : '')
const precioPlan = computed(() => datos.value?.plan
  ? formatearPrecioMembresia(datos.value.plan.monto_centavos, datos.value.plan.moneda)
  : '')
const estadoMembresia = computed(() => datos.value?.membresia.estado ?? 'sin_membresia')

if (carga.data.value?.tipo === 'error' && carga.data.value.codigo === 401) {
  limpiarSesion()
  await navigateTo('/cliente/login', { replace: true })
}

async function actualizar() {
  await carga.refresh()
  if (
    carga.data.value?.tipo === 'error'
    && carga.data.value.codigo === 401
  ) {
    limpiarSesion()
    clearNuxtData('cliente-membresia-y-plan')
    await navigateTo('/cliente/login', { replace: true })
  }
}

async function iniciarPago() {
  const estadoActual = datos.value?.membresia
  if (
    cargandoCheckout.value
    || datos.value?.plan === null
    || datos.value?.plan === undefined
    || estadoActual?.puede_comprar !== true
  ) {
    return
  }

  cargandoCheckout.value = true
  errorCheckout.value = ''
  claveIdempotencia.value ??= crypto.randomUUID()
  try {
    const respuesta = await crearCheckout(claveIdempotencia.value)
    const url = new URL(respuesta.checkout_url)
    if (url.protocol !== 'https:' || url.hostname !== 'checkout.stripe.com') {
      throw new Error('Destino de Checkout no válido')
    }
    window.location.assign(url.toString())
  } catch (error: unknown) {
    const codigo = obtenerEstadoErrorSesionCliente(error)
    if (codigo === 401) {
      limpiarSesion()
      clearNuxtData('cliente-membresia-y-plan')
      await navigateTo('/cliente/login', { replace: true })
      return
    }
    errorCheckout.value = codigo === 409
      ? 'Ya existe una compra en curso. Espera la actualización del estado de tu membresía.'
      : codigo === 429
        ? 'Se alcanzó el límite de solicitudes. Inténtalo más tarde.'
        : 'No fue posible iniciar el pago. Inténtalo nuevamente.'
  } finally {
    cargandoCheckout.value = false
  }
}
</script>

<template>
  <section class="membership-page" aria-labelledby="membership-title">
    <header class="page-heading">
      <div>
        <p class="eyebrow">CUENTA DE CLIENTE</p>
        <h1 id="membership-title">Membresías</h1>
        <p>Consulta tu plan y su estado directamente desde tu cuenta.</p>
      </div>
    </header>

    <div v-if="carga.pending.value" class="notice" role="status">
      Consultando tu membresía y los planes disponibles…
    </div>
    <div v-else-if="mensajeCarga" class="notice notice-error" role="alert">
      <span>{{ mensajeCarga }}</span>
      <button class="button-secondary" type="button" @click="actualizar">Reintentar</button>
    </div>
    <template v-else-if="datos">
      <section class="panel" aria-labelledby="status-title">
        <div class="panel-heading">
          <div>
            <h2 id="status-title">Estado de tu membresía</h2>
            <p>El estado se confirma desde el servicio de cuenta.</p>
          </div>
          <span class="status-pill" :class="`status-${estadoMembresia}`">
            <span class="status-dot" aria-hidden="true" />
            {{ etiquetaEstado }}
          </span>
        </div>

        <dl v-if="datos.membresia.membresia" class="membership-details">
          <div>
            <dt>Plan</dt>
            <dd>{{ datos.membresia.membresia.plan }}</dd>
          </div>
          <div>
            <dt>Precio</dt>
            <dd>{{ formatearPrecioMembresia(datos.membresia.membresia.monto_centavos, datos.membresia.membresia.moneda) }} / mes</dd>
          </div>
          <div>
            <dt>Inicio</dt>
            <dd>{{ formatearFechaMembresia(datos.membresia.membresia.fecha_inicio) }}</dd>
          </div>
          <div>
            <dt>Periodo actual</dt>
            <dd>
              {{ formatearFechaMembresia(datos.membresia.membresia.periodo_actual_inicio) }}
              –
              {{ formatearFechaMembresia(datos.membresia.membresia.periodo_actual_fin) }}
            </dd>
          </div>
        </dl>
        <p v-else class="empty-copy">
          Aún no hay una membresía confirmada en tu cuenta.
        </p>
      </section>

      <section v-if="datos.plan" class="panel plan-panel" aria-labelledby="plan-title">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">PLAN DISPONIBLE</p>
            <h2 id="plan-title">{{ datos.plan.nombre }}</h2>
          </div>
          <p class="plan-price">
            {{ precioPlan }} <span>/ mes</span>
          </p>
        </div>
        <p class="plan-copy">
          El importe y la disponibilidad se cargan desde el servicio de membresías.
          El pago se procesa en Stripe Checkout.
        </p>
        <p v-if="datos.membresia.checkout_pendiente" class="pending-note" role="status">
          Hay una compra en proceso. Cuando el pago se confirme, el estado aparecerá aquí.
        </p>
        <p v-if="errorCheckout" class="inline-error" role="alert">{{ errorCheckout }}</p>
        <button
          v-if="datos.membresia.puede_comprar"
          class="primary-button"
          type="button"
          :disabled="cargandoCheckout"
          @click="iniciarPago"
        >
          {{ cargandoCheckout ? 'Conectando con Stripe…' : 'Continuar al pago seguro' }}
        </button>
        <p v-else class="purchase-note">
          Este plan no está disponible para compra en el estado actual de tu cuenta.
        </p>
        <p class="secure-note">Smart Parking no almacena los datos de tu tarjeta.</p>
      </section>
      <p v-else class="notice">
        El plan mensual no está disponible en este momento. Vuelve a intentarlo más tarde.
      </p>
    </template>
  </section>
</template>

<style scoped>
.membership-page { display: grid; gap: 1.2rem; max-width: 72rem; margin: 0 auto; color: #29252f; }
.page-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem; }
.eyebrow { margin: 0 0 .45rem; color: #765b92; font-size: .68rem; font-weight: 800; letter-spacing: .12em; }
h1 { margin: 0; font-size: clamp(1.7rem, 3vw, 2.2rem); letter-spacing: -.045em; }
.page-heading > div > p:last-child { margin: .45rem 0 0; color: #746f7b; font-size: .86rem; line-height: 1.5; }
.panel { overflow: hidden; border: 1px solid #e8e5eb; border-radius: 1rem; background: #fff; box-shadow: 0 10px 30px rgb(31 20 42 / 4%); }
.panel-heading { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 1.2rem 1.35rem; border-bottom: 1px solid #eeeaf1; }
.panel-heading h2 { margin: 0; font-size: 1rem; }
.panel-heading .eyebrow { margin-bottom: .35rem; font-size: .62rem; }
.panel-heading > div > .eyebrow + h2 { margin-bottom: 0; }
.panel-heading > div > p:not(.eyebrow) { margin: .3rem 0 0; color: #746f7b; font-size: .78rem; }
.status-pill { display: inline-flex; align-items: center; gap: .4rem; padding: .35rem .6rem; border: 1px solid transparent; border-radius: 999px; font-size: .73rem; font-weight: 750; white-space: nowrap; }
.status-dot { width: .42rem; height: .42rem; border-radius: 50%; background: currentColor; }
.status-activa { border-color: #c8e7d3; background: #eff9f2; color: #267044; }
.status-cancelacion_programada { border-color: #efd7aa; background: #fff8e9; color: #90620a; }
.status-pago_vencido { border-color: #f1c9b9; background: #fff2ed; color: #a64d2c; }
.status-cancelada, .status-inactiva { border-color: #e4dfe8; background: #f7f5f8; color: #6c6672; }
.status-pendiente { border-color: #d9d0ed; background: #f5f1fc; color: #6a5191; }
.status-sin_membresia { border-color: #e4dfe8; background: #f7f5f8; color: #6c6672; }
.membership-details { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .9rem; margin: 0; padding: 1.25rem 1.35rem; }
.membership-details > div { min-width: 0; padding: .8rem; background: #fcfbfd; border: 1px solid #eee9f1; border-radius: .7rem; }
.membership-details dt { margin-bottom: .35rem; color: #776f7e; font-size: .7rem; font-weight: 700; }
.membership-details dd { margin: 0; color: #30283a; font-size: .86rem; font-weight: 750; }
.empty-copy { margin: 0; padding: 1.25rem 1.35rem; color: #746f7b; font-size: .85rem; line-height: 1.55; }
.plan-panel { padding-bottom: 1.2rem; }
.plan-panel .panel-heading { align-items: flex-start; }
.plan-price { margin: 0; color: #2d2437; font-size: clamp(1.7rem, 4vw, 2.3rem); font-weight: 800; letter-spacing: -.05em; white-space: nowrap; }
.plan-price span { color: #77707d; font-size: .82rem; font-weight: 550; letter-spacing: 0; }
.plan-copy, .secure-note, .purchase-note { margin: 1rem 1.35rem 0; color: #655e6c; font-size: .82rem; line-height: 1.55; }
.pending-note { margin: 1rem 1.35rem 0; padding: .75rem .85rem; color: #72540b; background: #fff8e9; border: 1px solid #efd7aa; border-radius: .65rem; font-size: .8rem; line-height: 1.5; }
.inline-error { margin: 1rem 1.35rem 0; color: #a44333; font-size: .8rem; }
.primary-button { display: block; width: calc(100% - 2.7rem); min-height: 3rem; margin: 1.15rem 1.35rem 0; padding: .7rem 1rem; color: #fff; background: #674187; border: 0; border-radius: .65rem; cursor: pointer; font: inherit; font-size: .86rem; font-weight: 800; }
.primary-button:hover:not(:disabled) { background: #56336f; }
.primary-button:disabled { cursor: wait; opacity: .65; }
.secure-note { margin-top: .7rem; color: #817a87; font-size: .7rem; text-align: center; }
.notice { display: flex; min-height: 4rem; align-items: center; justify-content: space-between; gap: 1rem; padding: 1rem 1.2rem; color: #655e6c; background: #fff; border: 1px solid #e8e2ec; border-radius: .8rem; font-size: .83rem; }
.notice-error { color: #a44333; }
.button-secondary { padding: .48rem .75rem; color: #463d4f; background: #fff; border: 1px solid #ded8e4; border-radius: .55rem; cursor: pointer; font: inherit; font-size: .76rem; font-weight: 700; }
.button-secondary:hover { background: #fbf8fd; border-color: #c4b3d3; }
.primary-button:focus-visible, .button-secondary:focus-visible { outline: 3px solid rgb(92 58 134 / 24%); outline-offset: 3px; }
@media (max-width: 40rem) { .panel-heading { align-items: flex-start; flex-direction: column; } .membership-details { grid-template-columns: 1fr; } .plan-price { white-space: normal; } .notice { align-items: flex-start; flex-direction: column; } }
</style>
