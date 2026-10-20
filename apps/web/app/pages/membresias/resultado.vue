<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { obtenerEstadoErrorClientes } from '~/utils/clientes-membresias'

const route = useRoute()
const { consultarEstadoCheckout } = useClientesMembresias()
const sessionId = typeof route.query.session_id === 'string'
  && /^cs_test_[A-Za-z0-9]+$/.test(route.query.session_id)
  ? route.query.session_id
  : null
const esCancelado = route.query.estado === 'cancelado'
const estado = ref<'pendiente' | 'confirmado' | 'no_completado'>(
  esCancelado || sessionId === null ? 'no_completado' : 'pendiente',
)
const consultaDisponible = ref(sessionId !== null && !esCancelado)
const errorConsulta = ref(false)
let timer: ReturnType<typeof setInterval> | undefined
let intentos = 0

const titulo = computed(() => {
  if (estado.value === 'confirmado') return 'Membresía confirmada'
  if (estado.value === 'no_completado') return esCancelado ? 'Pago no completado' : 'No se pudo confirmar el pago'
  return 'Estamos confirmando tu pago'
})
const descripcion = computed(() => {
  if (estado.value === 'confirmado') {
    return 'Stripe confirmó el pago y el registro ya está disponible.'
  }
  if (estado.value === 'no_completado') {
    return esCancelado
      ? 'No se realizó ningún registro. Puedes volver al plan mensual cuando estés listo.'
      : 'No se creó ningún cliente. Verifica el estado con Stripe o intenta de nuevo.'
  }
  return 'El pago puede tardar unos momentos en sincronizarse. El registro se completa únicamente después de la confirmación de Stripe.'
})

async function consultarEstado() {
  if (sessionId === null || !consultaDisponible.value) {
    return
  }
  try {
    const respuesta = await consultarEstadoCheckout(sessionId)
    estado.value = respuesta.estado
    errorConsulta.value = false
  } catch (error: unknown) {
    errorConsulta.value = obtenerEstadoErrorClientes(error) !== 404
  }
  intentos += 1
  if (estado.value !== 'pendiente' || intentos >= 12) {
    consultaDisponible.value = false
    if (timer !== undefined) clearInterval(timer)
  }
}

onMounted(async () => {
  await consultarEstado()
  if (estado.value === 'pendiente' && consultaDisponible.value) {
    timer = setInterval(() => void consultarEstado(), 2500)
  }
})

onBeforeUnmount(() => {
  if (timer !== undefined) clearInterval(timer)
})
</script>

<template>
  <main class="result-shell" aria-labelledby="result-title">
    <section class="result-card" aria-live="polite">
      <div
        class="result-mark"
        :class="{
          'result-mark-success': estado === 'confirmado',
          'result-mark-error': estado === 'no_completado',
        }"
        aria-hidden="true"
      >
        {{ estado === 'confirmado' ? '✓' : estado === 'no_completado' ? '!' : '…' }}
      </div>
      <p class="eyebrow">SMART PARKING</p>
      <h1 id="result-title">{{ titulo }}</h1>
      <p>{{ descripcion }}</p>
      <p v-if="errorConsulta && estado === 'pendiente'" class="sync-note" role="status">
        La consulta está temporalmente indisponible; Stripe seguirá notificando el resultado.
      </p>
      <NuxtLink class="return-link" to="/membresias">Volver al plan mensual</NuxtLink>
    </section>
  </main>
</template>

<style scoped>
.result-shell { display: grid; min-height: 100dvh; place-items: center; padding: 1.2rem; background: #f8f7fa; color: #211d28; font-family: Manrope, sans-serif; }
.result-card { width: min(100%, 34rem); padding: clamp(1.5rem, 5vw, 2.5rem); border: 1px solid #e7e1eb; border-radius: 1rem; background: #fff; text-align: center; box-shadow: 0 18px 55px rgb(35 22 48 / 7%); }
.result-mark { display: grid; width: 3.4rem; height: 3.4rem; margin: 0 auto 1.1rem; place-items: center; border-radius: 50%; background: #f1ecf6; color: #674187; font-size: 1.6rem; font-weight: 850; }
.result-mark-success { background: #edf8f0; color: #287244; }
.result-mark-error { background: #fff2ed; color: #a64d2c; }
.eyebrow { margin: 0 0 .45rem; color: #765b92; font-size: .65rem; font-weight: 800; letter-spacing: .12em; }
h1 { margin: 0 0 .65rem; font-size: clamp(1.45rem, 4vw, 2rem); letter-spacing: -.045em; }
.result-card > p:not(.eyebrow) { margin: 0 auto; color: #706978; font-size: .87rem; line-height: 1.6; }
.sync-note { padding-top: .75rem; font-size: .76rem !important; }
.return-link { display: inline-flex; margin-top: 1.4rem; color: #674187; font-size: .82rem; font-weight: 800; text-decoration: none; }
.return-link:hover { text-decoration: underline; }
</style>
