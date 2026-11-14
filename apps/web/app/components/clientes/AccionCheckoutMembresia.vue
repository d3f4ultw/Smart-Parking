<script setup lang="ts">
import { ErrorClienteApi, useClienteApi } from '~/utils/cliente-api'
import type { IntentoCheckoutPendienteCliente } from '~/types/cliente'

interface Props {
  puedeComprar: boolean
  checkoutPendiente: IntentoCheckoutPendienteCliente | null
}

const props = defineProps<Props>()
const api = useClienteApi()
const csrf = useCsrfCliente()
const sesion = useSesionCliente()
const trabajando = ref(false)
const error = ref('')
let claveIdempotencia: string | null = null

/** Solo acepta enlaces de Stripe con conexión segura (HTTPS); rechaza otros destinos
 * para evitar que una respuesta lleve al cliente a otro sitio.
 */
function validarCheckoutUrl(valor: string | null | undefined): string | null {
  if (!valor) return null
  try {
    const url = new URL(valor)
    return url.origin === 'https://checkout.stripe.com' && !url.username && !url.password
      ? url.href
      : null
  } catch {
    return null
  }
}

async function gestionarFallo(fallo: unknown) {
  csrf.manejarFallo(fallo)
  if (fallo instanceof ErrorClienteApi && fallo.estado === 401) {
    sesion.limpiar()
    await navigateTo('/clientes/acceso')
    return
  }
  error.value =
    fallo instanceof ErrorClienteApi
      ? fallo.message
      : 'No pudimos abrir Checkout. Inténtalo de nuevo desde tu portal.'
}

/** Pide un enlace de pago con el mismo identificador si debe repetir la solicitud;
 * antes de abrirlo, comprueba que pertenezca al proveedor esperado.
 */
async function crearCheckout() {
  if (trabajando.value || !props.puedeComprar || props.checkoutPendiente || !import.meta.client) {
    return
  }
  trabajando.value = true
  error.value = ''
  try {
    claveIdempotencia ??= crypto.randomUUID()
    const respuesta = await api.crearCheckoutMembresia(await csrf.obtener(), claveIdempotencia)
    const checkoutUrl = validarCheckoutUrl(respuesta.checkoutUrl)
    if (!checkoutUrl) {
      error.value = 'No pudimos abrir un Checkout seguro. Inténtalo de nuevo desde tu portal.'
      return
    }
    window.location.assign(checkoutUrl)
  } catch (fallo) {
    await gestionarFallo(fallo)
  } finally {
    trabajando.value = false
  }
}

/** Vuelve a consultar el intento pendiente al servidor y abre solo el enlace seguro
 * que devuelve si todavía está disponible.
 */
async function continuarCheckout() {
  const intento = props.checkoutPendiente
  if (trabajando.value || !intento || !import.meta.client) return
  trabajando.value = true
  error.value = ''
  try {
    const respuesta = await api.consultarCheckoutMembresia(intento.intentoId)
    const checkoutUrl = validarCheckoutUrl(respuesta.checkoutUrl)
    if (!checkoutUrl) {
      error.value = 'Este Checkout ya no está disponible. Actualiza el estado desde tu portal.'
      return
    }
    window.location.assign(checkoutUrl)
  } catch (fallo) {
    await gestionarFallo(fallo)
  } finally {
    trabajando.value = false
  }
}
</script>

<template>
  <div class="acciones-checkout">
    <p v-if="error" class="error-checkout" role="alert">{{ error }}</p>
    <UButton
      v-if="puedeComprar && !checkoutPendiente"
      class="boton-checkout"
      :loading="trabajando"
      :disabled="trabajando"
      @click="crearCheckout"
    >
      Comprar membresía
    </UButton>
    <UButton
      v-else-if="checkoutPendiente"
      class="boton-checkout"
      color="neutral"
      variant="outline"
      :loading="trabajando"
      :disabled="trabajando"
      @click="continuarCheckout"
    >
      Continuar con Checkout
    </UButton>
  </div>
</template>

<style scoped>
.acciones-checkout {
  margin-top: 18px;
}
.error-checkout {
  margin: 0 0 14px;
  color: #b42318;
  font-size: 0.9rem;
}
</style>
