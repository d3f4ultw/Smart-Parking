<script setup lang="ts">
import { computed, ref } from 'vue'

import {
  formatearPrecioMembresia,
  mapearErrorClientes,
  obtenerEstadoErrorClientes,
  type PlanMembresia,
} from '~/utils/clientes-membresias'

type ResultadoPlanes =
  | { tipo: 'exito'; planes: PlanMembresia[] }
  | { tipo: 'error'; codigo: number | undefined; mensaje: string }

const { consultarPlanes, crearCheckout } = useClientesMembresias()
const cargandoCheckout = ref(false)
const errorCheckout = ref('')
const claveIdempotencia = ref<string | null>(null)

const carga = await useAsyncData<ResultadoPlanes>(
  'publico-planes-membresia',
  async (_nuxtApp, { signal }): Promise<ResultadoPlanes> => {
    try {
      const respuesta = await consultarPlanes(signal)
      return { tipo: 'exito', planes: respuesta.planes }
    } catch (error: unknown) {
      const codigo = obtenerEstadoErrorClientes(error)
      return {
        tipo: 'error',
        codigo,
        mensaje: mapearErrorClientes(codigo, 'compra'),
      }
    }
  },
  { default: (): ResultadoPlanes => ({ tipo: 'exito', planes: [] }) },
)

const plan = computed(() =>
  carga.data.value?.tipo === 'exito'
    ? carga.data.value.planes.find((elemento) => elemento.plan_id === 'mensual') ?? null
    : null,
)
const mensajeCarga = computed(() =>
  carga.data.value?.tipo === 'error' ? carga.data.value.mensaje : '',
)

async function iniciarPago() {
  if (cargandoCheckout.value || plan.value === null) {
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
    errorCheckout.value = mapearErrorClientes(
      obtenerEstadoErrorClientes(error),
      'compra',
    )
  } finally {
    cargandoCheckout.value = false
  }
}
</script>

<template>
  <main class="membership-shell" aria-labelledby="membership-title">
    <section class="membership-card">
      <p class="eyebrow">SMART PARKING · COMERCIAL</p>
      <h1 id="membership-title">Una membresía. Estacionamiento más sencillo.</h1>
      <p class="intro">
        Contrata el plan mensual en Checkout seguro. Tu registro se confirma solo después de verificar el pago.
      </p>

      <div v-if="carga.pending.value" class="state-message" role="status">
        Consultando el plan disponible…
      </div>
      <div v-else-if="mensajeCarga" class="state-message error-message" role="alert">
        <span>{{ mensajeCarga }}</span>
        <button class="secondary-button" type="button" @click="carga.refresh()">
          Reintentar
        </button>
      </div>
      <section v-else-if="plan" class="plan-card" aria-labelledby="plan-title">
        <div class="plan-heading">
          <div>
            <p class="plan-kicker">PLAN MENSUAL</p>
            <h2 id="plan-title">{{ plan.nombre }}</h2>
          </div>
          <span class="plan-mark" aria-hidden="true">✓</span>
        </div>
        <p class="plan-price">
          {{ formatearPrecioMembresia(plan.monto_centavos, plan.moneda) }}
          <span>/ mes</span>
        </p>
        <ul class="plan-benefits">
          <li>Pago procesado por Stripe Checkout.</li>
          <li>Sin periodo de prueba ni cupones promocionales.</li>
          <li>Recibirás confirmación cuando el pago quede registrado.</li>
        </ul>
        <p v-if="errorCheckout" class="inline-error" role="alert">{{ errorCheckout }}</p>
        <button
          class="primary-button"
          type="button"
          :disabled="cargandoCheckout"
          @click="iniciarPago"
        >
          {{ cargandoCheckout ? 'Conectando con Stripe…' : 'Continuar al pago seguro' }}
        </button>
        <p class="secure-note">Stripe recibe los datos del pago; Smart Parking no almacena tarjetas.</p>
      </section>
      <p v-else class="state-message" role="status">
        No hay un plan mensual disponible para esta modalidad.
      </p>
    </section>
  </main>
</template>

<style scoped>
.membership-shell { display: grid; min-height: 100dvh; place-items: center; padding: 2rem 1rem; background: radial-gradient(circle at 15% 10%, #f2ebf8, transparent 37%), #f8f7fa; color: #211d28; font-family: Manrope, sans-serif; }
.membership-card { width: min(100%, 43rem); }
.eyebrow, .plan-kicker { color: #765b92; font-size: .68rem; font-weight: 800; letter-spacing: .12em; }
h1 { max-width: 40rem; margin: .8rem 0 .7rem; font-size: clamp(2rem, 5vw, 3.25rem); line-height: 1.08; letter-spacing: -.055em; }
.intro { max-width: 37rem; margin-bottom: 1.7rem; color: #706978; font-size: .96rem; line-height: 1.65; }
.plan-card { padding: clamp(1.2rem, 4vw, 2rem); border: 1px solid #e6dfeb; border-radius: 1.1rem; background: #fff; box-shadow: 0 18px 55px rgb(35 22 48 / 8%); }
.plan-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.plan-kicker { margin: 0 0 .45rem; font-size: .64rem; }
.plan-heading h2 { margin: 0; font-size: 1.05rem; }
.plan-mark { display: grid; width: 2rem; height: 2rem; place-items: center; border-radius: 50%; background: #f0e8f6; color: #664183; font-weight: 900; }
.plan-price { margin: 1.45rem 0 1rem; color: #2d2437; font-size: clamp(2.2rem, 6vw, 3.1rem); font-weight: 800; letter-spacing: -.05em; }
.plan-price span { color: #77707d; font-size: .9rem; font-weight: 550; letter-spacing: 0; }
.plan-benefits { display: grid; gap: .55rem; margin: 0 0 1.5rem; padding-left: 1.2rem; color: #655e6c; font-size: .83rem; line-height: 1.5; }
.plan-benefits li::marker { color: #805b9e; }
.primary-button { width: 100%; min-height: 3rem; border: 0; border-radius: .65rem; background: #674187; color: #fff; font: inherit; font-size: .86rem; font-weight: 800; cursor: pointer; }
.primary-button:hover:not(:disabled) { background: #56336f; }
.primary-button:disabled { opacity: .65; cursor: wait; }
.secure-note { margin: .75rem 0 0; color: #817a87; font-size: .7rem; text-align: center; }
.state-message { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 1rem 1.2rem; border: 1px solid #e8e2ec; border-radius: .8rem; background: #fff; color: #655e6c; font-size: .83rem; }
.error-message, .inline-error { color: #a44333; }
.inline-error { margin: 0 0 .8rem; font-size: .8rem; }
.secondary-button { padding: .45rem .7rem; border: 1px solid #ded8e4; border-radius: .5rem; background: #fff; color: #463d4f; font: inherit; font-size: .75rem; font-weight: 750; cursor: pointer; }
</style>
