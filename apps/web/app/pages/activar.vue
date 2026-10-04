<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

import {
  activarSiEsValida,
  esActivacionNoDisponible,
  evaluarRequisitosContrasena,
  limpiarDatosFormularioActivacion,
  mapearErrorActivacion,
  obtenerEstadoError,
  obtenerModoPrevalidado,
  obtenerTokenActivacion,
  puedeEnviarActivacion,
  type DatosFormularioActivacion,
  type RespuestaPrevalidacionActivacion,
} from '~/utils/activacion'

const route = useRoute()
const { activarCuenta, prevalidarActivacion } = useActivacion()

const token = computed(() => {
  const tokenDelRoute = obtenerTokenActivacion(route.query.token)
  if (import.meta.client) {
    const tokenDeLaUrl = obtenerTokenActivacion(
      new URL(window.location.href).searchParams.get('token'),
    )
    return tokenDeLaUrl ?? tokenDelRoute
  }
  return tokenDelRoute
})
const prevalidacion = await useAsyncData<
  RespuestaPrevalidacionActivacion | null
>(
  'activacion-prevalidacion',
  async () => {
    const tokenActual = obtenerTokenActivacion(route.query.token)
    if (tokenActual === null) {
      return null
    }
    return await prevalidarActivacion(tokenActual)
  },
  {
    default: () => null,
    dedupe: 'defer',
    immediate: token.value !== null,
    watch: [() => route.query.token],
  },
)
const modo = computed(() => obtenerModoPrevalidado(prevalidacion.data.value))
const formulario = reactive<DatosFormularioActivacion>({
  codigo: '',
  contrasenaTemporal: '',
  nuevaContrasena: '',
  confirmarContrasena: '',
})
const estado = ref<
  'formulario' | 'enviando' | 'exito' | 'error' | 'no-disponible'
>('formulario')
const mensajeError = ref('')
const mostrarNuevaContrasena = ref(false)
const mostrarConfirmarContrasena = ref(false)
watch(
  () => route.query.token,
  () => {
    limpiarDatosFormularioActivacion(formulario)
    mostrarNuevaContrasena.value = false
    mostrarConfirmarContrasena.value = false
    mensajeError.value = ''
    estado.value = 'formulario'
  },
)
const resolucionPendiente = computed(
  () => token.value !== null && prevalidacion.status.value === 'pending',
)
const formularioDisponible = computed(
  () =>
    !resolucionPendiente.value &&
    !prevalidacion.error.value &&
    modo.value !== null &&
    estado.value !== 'no-disponible',
)
const mensajeEnlace = computed(() => {
  if (resolucionPendiente.value) {
    return 'Validando el enlace de activación.'
  }
  return 'Este enlace de activación ya no es válido. Puede haber expirado, haber sido utilizado o haber sido reemplazado por uno nuevo.'
})

const mostrarEncabezado = computed(
  () =>
    formularioDisponible.value ||
    resolucionPendiente.value ||
    estado.value === 'exito',
)

const requisitosContrasena = computed(() =>
  evaluarRequisitosContrasena(
    formulario.nuevaContrasena,
    formulario.confirmarContrasena,
    formulario.contrasenaTemporal,
  ),
)
const puedeEnviar = computed(
  () => {
    const modoActual = modo.value
    return (
      modoActual !== null &&
      formularioDisponible.value &&
      estado.value !== 'enviando' &&
      puedeEnviarActivacion(modoActual, formulario, true)
    )
  },
)

async function enviarFormulario() {
  const modoActual = modo.value
  const tokenActual = token.value
  if (modoActual === null || tokenActual === null) {
    return
  }

  estado.value = 'enviando'
  mensajeError.value = ''

  try {
    const errorLocal = await activarSiEsValida(
      modoActual,
      tokenActual,
      formulario,
      activarCuenta,
    )
    if (errorLocal !== null) {
      estado.value = 'error'
      mensajeError.value = errorLocal
      return
    }
    estado.value = 'exito'
  } catch (error: unknown) {
    if (esActivacionNoDisponible(error)) {
      limpiarDatosFormularioActivacion(formulario)
      mostrarNuevaContrasena.value = false
      mostrarConfirmarContrasena.value = false
      mensajeError.value = ''
      estado.value = 'no-disponible'
      return
    }

    const status = obtenerEstadoError(error)
    estado.value = 'error'
    mensajeError.value = mapearErrorActivacion(status)
  }
}

</script>

<template>
  <main class="activation-page">
    <section
      class="activation-card"
      :aria-labelledby="mostrarEncabezado ? 'activation-title' : undefined"
    >
      <header v-if="mostrarEncabezado" class="activation-header">
        <p class="eyebrow">Smart Parking</p>
        <h1 id="activation-title">Activa tu cuenta</h1>
        <p>
          Completa los datos de activación para comenzar a usar tu cuenta de
          administrador.
        </p>
      </header>

      <div v-if="!formularioDisponible" class="state-block" role="alert">
        <h2>{{ resolucionPendiente ? 'Validando enlace…' : 'Activación no disponible' }}</h2>
        <p>{{ mensajeEnlace }}</p>
      </div>

      <div
        v-else-if="estado === 'exito'"
        class="state-block success"
        role="status"
      >
        <h2>Cuenta activada</h2>
        <p>
          Tu cuenta se activó correctamente. Ya puedes continuar al inicio de
          sesión.
        </p>
        <NuxtLink class="button primary" to="/login">
          Continuar al inicio de sesión
        </NuxtLink>
      </div>

      <form
        v-else
        class="activation-form"
        novalidate
        @submit.prevent="enviarFormulario"
      >
        <div v-if="estado === 'error'" class="state-block error" role="alert">
          <p>{{ mensajeError }}</p>
        </div>

        <div class="field-group">
          <label for="activation-code">Código de activación</label>
          <input
            id="activation-code"
            v-model="formulario.codigo"
            inputmode="numeric"
            autocomplete="one-time-code"
            pattern="[0-9]{6}"
            maxlength="6"
            required
          >
          <small>Escribe el código de 6 dígitos que recibiste por correo.</small>
        </div>

        <template v-if="modo === 'temporal'">
          <div class="field-group">
            <label for="temporary-password">Contraseña temporal</label>
            <input
              id="temporary-password"
              v-model="formulario.contrasenaTemporal"
              type="password"
              autocomplete="current-password"
              required
            >
          </div>

          <div class="field-group">
            <label for="new-password">Nueva contraseña</label>
            <div class="password-control">
              <input
                id="new-password"
                v-model="formulario.nuevaContrasena"
                :type="mostrarNuevaContrasena ? 'text' : 'password'"
                autocomplete="new-password"
                minlength="10"
                maxlength="128"
                required
              >
              <button
                class="visibility-button"
                type="button"
                :aria-label="mostrarNuevaContrasena ? 'Ocultar nueva contraseña' : 'Mostrar nueva contraseña'"
                :aria-pressed="mostrarNuevaContrasena"
                @click="mostrarNuevaContrasena = !mostrarNuevaContrasena"
              >
                <span aria-hidden="true">👁</span>
              </button>
            </div>
          </div>

          <div class="field-group">
            <label for="confirm-password">Confirmar nueva contraseña</label>
            <div class="password-control">
              <input
                id="confirm-password"
                v-model="formulario.confirmarContrasena"
                :type="mostrarConfirmarContrasena ? 'text' : 'password'"
                autocomplete="new-password"
                minlength="10"
                maxlength="128"
                required
              >
              <button
                class="visibility-button"
                type="button"
                :aria-label="mostrarConfirmarContrasena ? 'Ocultar confirmación de contraseña' : 'Mostrar confirmación de contraseña'"
                :aria-pressed="mostrarConfirmarContrasena"
                @click="mostrarConfirmarContrasena = !mostrarConfirmarContrasena"
              >
                <span aria-hidden="true">👁</span>
              </button>
            </div>
          </div>

          <ul class="password-rules" aria-live="polite">
            <li
              :class="{
                'is-valid': requisitosContrasena.longitudValida,
                'is-invalid': !requisitosContrasena.longitudValida,
              }"
            >
              <span aria-hidden="true">{{ requisitosContrasena.longitudValida ? '✓' : '✗' }}</span>
              Mínimo 10 caracteres
            </li>
            <li
              :class="{
                'is-valid': requisitosContrasena.mayusculaValida,
                'is-invalid': !requisitosContrasena.mayusculaValida,
              }"
            >
              <span aria-hidden="true">{{ requisitosContrasena.mayusculaValida ? '✓' : '✗' }}</span>
              Al menos una letra mayúscula
            </li>
            <li
              :class="{
                'is-valid': requisitosContrasena.coincidenciaValida,
                'is-invalid': !requisitosContrasena.coincidenciaValida,
              }"
            >
              <span aria-hidden="true">{{ requisitosContrasena.coincidenciaValida ? '✓' : '✗' }}</span>
              Las contraseñas coinciden
            </li>
            <li
              :class="{
                'is-valid': requisitosContrasena.diferenteDeTemporal === true,
                'is-invalid': requisitosContrasena.diferenteDeTemporal === false,
              }"
            >
              <span aria-hidden="true">
                {{ requisitosContrasena.diferenteDeTemporal === true ? '✓' : requisitosContrasena.diferenteDeTemporal === false ? '✗' : '•' }}
              </span>
              Debe ser diferente de la contraseña temporal
            </li>
          </ul>
        </template>

        <button class="button primary" type="submit" :disabled="!puedeEnviar">
          {{ estado === 'enviando' ? 'Activando…' : 'Activar cuenta' }}
        </button>
      </form>

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

.activation-page {
  display: grid;
  min-height: 100vh;
  padding: 1.5rem;
  place-items: center;
}

.activation-card {
  width: min(100%, 34rem);
  padding: clamp(1.5rem, 4vw, 2.75rem);
  background: #ffffff;
  border: 1px solid #d6e5ea;
  border-radius: 1.25rem;
  box-shadow: 0 1.5rem 4rem rgb(24 50 75 / 12%);
}

.activation-header {
  margin-bottom: 1.75rem;
}

.eyebrow {
  margin: 0 0 0.5rem;
  color: #0d7286;
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h1,
h2,
p {
  margin-top: 0;
}

h1 {
  margin-bottom: 0.65rem;
  color: #102a43;
  font-size: clamp(1.8rem, 5vw, 2.4rem);
}

h2 {
  margin-bottom: 0.5rem;
  color: #102a43;
  font-size: 1.15rem;
}

p {
  line-height: 1.55;
}

.activation-form {
  display: grid;
  gap: 1rem;
}

.field-group {
  display: grid;
  gap: 0.45rem;
}

label {
  color: #244a66;
  font-size: 0.95rem;
  font-weight: 650;
}

input {
  width: 100%;
  min-height: 2.9rem;
  padding: 0.7rem 0.8rem;
  color: #102a43;
  background: #fbfdfe;
  border: 1px solid #b6ced8;
  border-radius: 0.55rem;
  font: inherit;
}

input:focus {
  border-color: #0d7286;
  outline: 3px solid rgb(13 114 134 / 18%);
}

.password-control {
  display: flex;
  align-items: stretch;
}

.password-control input {
  min-width: 0;
  border-radius: 0.55rem 0 0 0.55rem;
}

.visibility-button {
  min-width: 2.9rem;
  padding: 0.5rem;
  color: #0d596b;
  background: #e4f1f4;
  border: 1px solid #b6ced8;
  border-left: 0;
  border-radius: 0 0.55rem 0.55rem 0;
  font: inherit;
  cursor: pointer;
}

.visibility-button:hover,
.visibility-button:focus-visible {
  background: #d2e8ed;
}

.visibility-button:focus-visible {
  outline: 3px solid rgb(13 114 134 / 18%);
  outline-offset: 1px;
}

.password-rules {
  display: grid;
  gap: 0.35rem;
  padding: 0;
  margin: -0.35rem 0 0;
  color: #5c7487;
  list-style: none;
  line-height: 1.4;
}

.password-rules li {
  display: flex;
  gap: 0.45rem;
  align-items: baseline;
}

.password-rules .is-valid {
  color: #1c6b3c;
}

.password-rules .is-invalid {
  color: #a33d31;
}

small {
  color: #5c7487;
  line-height: 1.4;
}

.button {
  display: inline-flex;
  min-height: 2.9rem;
  align-items: center;
  justify-content: center;
  padding: 0.7rem 1rem;
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

.primary {
  color: #ffffff;
  background: #0d7286;
}

.primary:hover:not(:disabled),
.primary:focus-visible {
  background: #09596a;
}

.state-block {
  padding: 1rem;
  margin-bottom: 1.25rem;
  background: #f4f8fa;
  border: 1px solid #d6e5ea;
  border-radius: 0.75rem;
}

.state-block p:last-child {
  margin-bottom: 0;
}

.state-block.success {
  background: #eef9f2;
  border-color: #b8dfc3;
}

.state-block.error {
  background: #fff5f3;
  border-color: #edc2ba;
}

.state-block .button {
  width: 100%;
  margin-top: 0.75rem;
}

@media (max-width: 32rem) {
  .activation-page {
    padding: 0.75rem;
  }

  .activation-card {
    border-radius: 0.9rem;
  }
}
</style>
