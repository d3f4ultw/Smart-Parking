<script setup lang="ts">
import { reactive, ref } from 'vue'

import {
  construirSolicitudLogin,
  mapearErrorLogin,
  obtenerRutaDespuesLogin,
  obtenerEstadoErrorLogin,
  validarDatosLogin,
  type DatosFormularioLogin,
} from '~/utils/login'

const { iniciarSesion } = useLogin()

const formulario = reactive<DatosFormularioLogin>({
  correo: '',
  contrasena: '',
})
const estado = ref<'formulario' | 'enviando' | 'error'>('formulario')
const mensajeError = ref('')
const mostrarContrasena = ref(false)

async function enviarFormulario() {
  if (estado.value === 'enviando') {
    return
  }

  const errorLocal = validarDatosLogin(formulario)
  if (errorLocal !== null) {
    estado.value = 'error'
    mensajeError.value = errorLocal
    return
  }

  estado.value = 'enviando'
  mensajeError.value = ''

  try {
    const respuesta = await iniciarSesion(construirSolicitudLogin(formulario))
    formulario.contrasena = ''
    estado.value = 'formulario'
    await navigateTo(obtenerRutaDespuesLogin(respuesta.rol))
  } catch (error: unknown) {
    estado.value = 'error'
    mensajeError.value = mapearErrorLogin(obtenerEstadoErrorLogin(error))
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-card" aria-labelledby="login-title">
      <header class="login-header">
        <p class="eyebrow">Smart Parking</p>
        <h1 id="login-title">Inicia sesión</h1>
        <p>Ingresa tus datos para acceder a tu cuenta.</p>
      </header>

      <form
        class="login-form"
        novalidate
        @submit.prevent="enviarFormulario"
      >
        <div v-if="estado === 'error'" class="state-block error" role="alert">
          <p>{{ mensajeError }}</p>
        </div>

        <div class="field-group">
          <label for="login-email">Correo electrónico</label>
          <input
            id="login-email"
            v-model="formulario.correo"
            name="correo"
            type="email"
            inputmode="email"
            autocomplete="email"
            required
          >
        </div>

        <div class="field-group">
          <label for="login-password">Contraseña</label>
          <div class="password-control">
            <input
              id="login-password"
              v-model="formulario.contrasena"
              name="contrasena"
              :type="mostrarContrasena ? 'text' : 'password'"
              autocomplete="current-password"
              required
            >
            <button
              class="visibility-button"
              type="button"
              aria-controls="login-password"
              :aria-label="mostrarContrasena ? 'Ocultar contraseña' : 'Mostrar contraseña'"
              :title="mostrarContrasena ? 'Ocultar contraseña' : 'Mostrar contraseña'"
              :aria-pressed="mostrarContrasena"
              @click="mostrarContrasena = !mostrarContrasena"
            >
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M2.2 12s3.5-6.5 9.8-6.5 9.8 6.5 9.8 6.5-3.5 6.5-9.8 6.5S2.2 12 2.2 12Z" />
                <circle cx="12" cy="12" r="3" />
                <path v-if="mostrarContrasena" d="m3 3 18 18" />
              </svg>
            </button>
          </div>
        </div>

        <button class="button primary" type="submit" :disabled="estado === 'enviando'">
          {{ estado === 'enviando' ? 'Iniciando sesión…' : 'Iniciar sesión' }}
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

.login-page {
  display: grid;
  width: 100%;
  min-height: 100vh;
  padding: 1.5rem;
  place-items: center;
}

.login-card {
  width: min(100%, 34rem);
  padding: clamp(1.5rem, 4vw, 2.75rem);
  background: #ffffff;
  border: 1px solid #d6e5ea;
  border-radius: 1.25rem;
  box-shadow: 0 1.5rem 4rem rgb(24 50 75 / 12%);
}

.login-header {
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

.login-form {
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

.password-control:focus-within {
  border-radius: 0.55rem;
  outline: 3px solid rgb(13 114 134 / 18%);
}

.password-control input:focus {
  border-color: #0d7286;
  outline: none;
}

.visibility-button {
  display: inline-flex;
  min-width: 2.9rem;
  align-items: center;
  justify-content: center;
  padding: 0.65rem;
  color: #0d6071;
  background: #eef7f9;
  border: 1px solid #b6ced8;
  border-left: 0;
  border-radius: 0 0.55rem 0.55rem 0;
  font: inherit;
  font-size: 0.9rem;
  font-weight: 650;
  cursor: pointer;
}

.visibility-button svg {
  width: 1.2rem;
  height: 1.2rem;
}

.visibility-button:hover,
.visibility-button:focus-visible {
  color: #084b59;
  background: #dceff2;
}

.visibility-button:focus-visible {
  outline: 2px solid #0d7286;
  outline-offset: -3px;
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

@media (max-width: 32rem) {
  .login-page {
    padding: 0.75rem;
  }

  .login-card {
    border-radius: 0.9rem;
  }
}
</style>
