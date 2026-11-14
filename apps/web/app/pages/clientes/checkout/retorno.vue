<script setup lang="ts">
import { onMounted } from 'vue'
import { useClienteApi } from '~/utils/cliente-api'

/** Al volver del proveedor de pago, aclara que el regreso no confirma el pago
 * y consulta una vez el intento antes de que el cliente revise su portal.
 */
definePageMeta({ layout: 'cliente', middleware: 'cliente-sesion' })

const route = useRoute()
const api = useClienteApi()
const formatoUuid = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i
const valorIntento = route.query.intentoId
const intentoId =
  typeof valorIntento === 'string' && formatoUuid.test(valorIntento) ? valorIntento : null
const estadoConsulta = ref<'sin-iniciar' | 'consultando' | 'consultada' | 'no-disponible'>(
  'sin-iniciar',
)
let consultaIniciada = false

const mensajeRetorno = computed(() =>
  route.query.resultado === 'cancelado'
    ? 'El flujo de Checkout se cerró. Este regreso no confirma un pago ni activa una membresía.'
    : 'El regreso desde Checkout no confirma el pago ni activa la membresía. La API actualizará el estado cuando verifique el pago.',
)

const mensajeConsulta = computed(() => {
  if (estadoConsulta.value === 'sin-iniciar') {
    return 'Este regreso no confirma el pago. Consulta la información vigente desde tu portal.'
  }
  if (estadoConsulta.value === 'consultando') return 'Consultando el estado actual del intento…'
  if (estadoConsulta.value === 'consultada') {
    return 'La consulta terminó. El portal muestra la información vigente de tu membresía.'
  }
  return 'No pudimos consultar este intento. Revisa el estado vigente desde tu portal.'
})

/** Consulta una sola vez al servidor sobre el intento de pago;
 * no toma el regreso del proveedor como prueba de que el pago se completó.
 */
async function consultarIntento() {
  if (consultaIniciada) return
  consultaIniciada = true
  if (!intentoId) {
    estadoConsulta.value = 'no-disponible'
    return
  }

  estadoConsulta.value = 'consultando'
  try {
    await api.consultarCheckoutMembresia(intentoId)
    estadoConsulta.value = 'consultada'
  } catch {
    estadoConsulta.value = 'no-disponible'
  }
}

onMounted(() => {
  void consultarIntento()
})

useHead({
  title: 'Regreso de Checkout | Smart Parking',
  meta: [{ name: 'referrer', content: 'no-referrer' }],
})
</script>

<template>
  <main class="pagina-retorno-checkout">
    <section class="tarjeta-retorno-checkout" aria-labelledby="titulo-retorno-checkout">
      <span class="icono-retorno-checkout" aria-hidden="true">
        <UIcon name="i-lucide-credit-card" />
      </span>
      <p class="sobrelinea-retorno">Membresía</p>
      <h1 id="titulo-retorno-checkout">Regresaste de Checkout</h1>
      <p class="mensaje-retorno">{{ mensajeRetorno }}</p>
      <p class="mensaje-consulta" role="status">{{ mensajeConsulta }}</p>
      <UButton to="/clientes/portal" size="lg">Volver a mi portal</UButton>
    </section>
  </main>
</template>

<style scoped>
.pagina-retorno-checkout {
  display: grid;
  flex: 1;
  place-items: center;
  padding: 38px 20px 56px;
}
.tarjeta-retorno-checkout {
  width: min(100%, 38rem);
  border: 1px solid var(--app-border);
  border-radius: 16px;
  background: var(--app-surface);
  padding: clamp(24px, 5vw, 40px);
}
.icono-retorno-checkout {
  display: grid;
  width: 48px;
  height: 48px;
  place-items: center;
  border-radius: 13px;
  background: color-mix(in srgb, var(--app-primary) 9%, var(--app-surface));
  color: var(--app-primary);
  font-size: 1.3rem;
}
.sobrelinea-retorno {
  margin: 20px 0 5px;
  color: var(--app-primary);
  font-size: 0.75rem;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
h1 {
  margin: 0;
  font-size: clamp(1.7rem, 5vw, 2.1rem);
  letter-spacing: -0.045em;
}
.mensaje-retorno,
.mensaje-consulta {
  color: var(--app-muted);
  line-height: 1.6;
}
.mensaje-retorno {
  margin: 18px 0 0;
}
.mensaje-consulta {
  margin: 10px 0 22px;
  font-size: 0.9rem;
}
</style>
