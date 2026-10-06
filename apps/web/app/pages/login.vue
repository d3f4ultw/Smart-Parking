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
    <div class="login-shell">
      <aside class="brand-panel" aria-label="Smart Parking">
        <div class="brand-lockup">
          <span class="brand-mark" aria-hidden="true">
            <svg
              viewBox="0 0 40 40"
              fill="none"
              stroke="currentColor"
              stroke-width="2.4"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M13 31V9h9a7 7 0 0 1 0 14h-9" />
              <path d="M10 35h20" />
            </svg>
          </span>
          <span class="brand-name-group">
            <span class="brand-name">Smart Parking</span>
            <span class="brand-caption">PLATAFORMA DE ESTACIONAMIENTO</span>
          </span>
        </div>

        <div class="brand-intro">
          <p class="brand-kicker">PANEL DE ADMINISTRACIÓN</p>
          <h2>Todo el control,<br>desde un solo<br>espacio.</h2>
          <p>Gestiona accesos, espacios y disponibilidad de manera simple y eficiente.</p>
        </div>

        <p class="brand-footer">Administración · Operación · Control</p>
      </aside>

      <section class="login-panel" aria-labelledby="login-title">
        <div class="login-card">
          <header class="login-header">
            <p class="eyebrow">Acceso a tu cuenta</p>
            <h1 id="login-title">Inicia sesión</h1>
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
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.login-page,
.login-page * {
  box-sizing: border-box;
}

.login-page {
  --login-background: #f4f3f5;
  --login-surface: #ffffff;
  --login-input: #fdfcfe;
  --login-foreground: #27232c;
  --login-muted: #726d78;
  --login-border: #e3dfe7;
  --login-accent: #5c3a86;
  --login-accent-hover: #6c4a97;
  --login-focus: rgb(92 58 134 / 22%);
  position: fixed;
  inset: 0;
  display: grid;
  min-width: 0;
  min-height: 100vh;
  overflow-y: auto;
  padding: clamp(1rem, 3vw, 3rem);
  place-items: center;
  color: var(--login-foreground);
  background: var(--login-background);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
}

.login-shell {
  display: grid;
  width: min(100%, 72rem);
  min-height: min(44rem, calc(100vh - 3rem));
  grid-template-columns: 0.92fr 1.08fr;
  overflow: hidden;
  background: var(--login-surface);
  border: 1px solid var(--login-border);
  border-radius: 1.5rem;
  box-shadow: 0 1.5rem 4rem rgb(32 24 42 / 11%);
}

.brand-panel {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: clamp(2.25rem, 5vw, 4rem);
  color: #ffffff;
  background:
    radial-gradient(ellipse at 14% 18%, rgb(126 97 160 / 15%), transparent 36%),
    linear-gradient(145deg, #281e35 0%, #1c1525 70%, #18121f 100%);
}

.brand-lockup {
  display: flex;
  align-items: center;
  gap: 0.9rem;
}

.brand-mark {
  display: grid;
  width: 3rem;
  height: 3rem;
  flex: 0 0 auto;
  place-items: center;
  color: #ffffff;
  background: rgb(255 255 255 / 10%);
  border: 1px solid rgb(255 255 255 / 20%);
  border-radius: 0.85rem;
}

.brand-mark svg {
  width: 1.75rem;
  height: 1.75rem;
}

.brand-name-group {
  display: grid;
  gap: 0.15rem;
}

.brand-name {
  font-size: 1.05rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.brand-caption {
  color: rgb(255 255 255 / 65%);
  font-size: 0.62rem;
  font-weight: 650;
  letter-spacing: 0.12em;
}

.brand-intro {
  max-width: 25rem;
  margin-block: 5rem;
}

.brand-kicker {
  margin-bottom: 1rem;
  color: #cbb9e2;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.13em;
}

.brand-intro h2 {
  max-width: none;
  margin: 0 0 1rem;
  color: #ffffff;
  font-size: clamp(2.2rem, 4vw, 3.35rem);
  font-weight: 650;
  letter-spacing: -0.045em;
  line-height: 1.08;
}

.brand-intro > p:last-child {
  max-width: 23rem;
  margin: 0;
  color: rgb(255 255 255 / 72%);
  font-size: 1rem;
  line-height: 1.65;
}

.brand-footer {
  margin: 0;
  padding-top: 1rem;
  color: rgb(255 255 255 / 62%);
  border-top: 1px solid rgb(255 255 255 / 20%);
  font-size: 0.75rem;
  letter-spacing: 0.04em;
}

.login-panel {
  display: grid;
  padding: clamp(2rem, 6vw, 5rem);
  place-items: center;
  background: var(--login-surface);
}

.login-card {
  width: min(100%, 27rem);
}

.login-header {
  margin-bottom: 2rem;
}

.eyebrow {
  margin: 0 0 0.8rem;
  color: var(--login-accent);
  font-size: 0.73rem;
  font-weight: 700;
  letter-spacing: 0.11em;
  text-transform: uppercase;
}

h1 {
  margin: 0 0 0.65rem;
  color: #29242f;
  font-size: clamp(1.9rem, 4vw, 2.35rem);
  font-weight: 680;
  letter-spacing: -0.045em;
  line-height: 1.15;
}

.login-header > p:last-child {
  margin: 0;
  color: var(--login-muted);
  font-size: 0.97rem;
  line-height: 1.55;
}

.login-form {
  display: grid;
  gap: 1.25rem;
}

.field-group {
  display: grid;
  gap: 0.55rem;
}

label {
  color: #4e435d;
  font-size: 0.88rem;
  font-weight: 650;
}

input {
  width: 100%;
  min-height: 3.1rem;
  padding: 0.75rem 0.9rem;
  color: #29242f;
  background: var(--login-input);
  border: 1px solid var(--login-border);
  border-radius: 0.7rem;
  font: inherit;
}

input:focus-visible {
  border-color: var(--login-accent);
  outline: 2px solid var(--login-focus);
  outline-offset: 1px;
}

.password-control {
  position: relative;
  display: flex;
  align-items: stretch;
}

.password-control input {
  min-width: 0;
  padding-right: 3.25rem;
}

.visibility-button {
  position: absolute;
  top: 50%;
  right: 0.35rem;
  display: grid;
  width: 2.4rem;
  height: 2.4rem;
  align-items: center;
  justify-content: center;
  padding: 0;
  color: #766f7d;
  background: transparent;
  border: 0;
  border-radius: 0.55rem;
  cursor: pointer;
  transform: translateY(-50%);
}

.visibility-button svg {
  width: 1.25rem;
  height: 1.25rem;
}

.visibility-button:hover {
  color: var(--login-accent-hover);
  background: #f2eef6;
}

.visibility-button:focus-visible {
  outline: 2px solid var(--login-accent);
  outline-offset: 2px;
}

.button {
  display: inline-flex;
  min-height: 3.1rem;
  align-items: center;
  justify-content: center;
  margin-top: 0.25rem;
  padding: 0.75rem 1rem;
  border: 1px solid transparent;
  border-radius: 0.7rem;
  font: inherit;
  font-weight: 700;
  text-decoration: none;
  cursor: pointer;
  transition: background-color 150ms ease, box-shadow 150ms ease;
}

.button:disabled {
  cursor: wait;
  opacity: 0.72;
}

.primary {
  color: #ffffff;
  background: var(--login-accent);
}

.primary:hover:not(:disabled) {
  background: var(--login-accent-hover);
}

.button:focus-visible {
  outline: 2px solid var(--login-accent);
  outline-offset: 3px;
}

.state-block {
  padding: 0.85rem 1rem;
  background: #f7f6f8;
  border: 1px solid var(--login-border);
  border-radius: 0.7rem;
}

.state-block p {
  margin: 0;
  font-size: 0.88rem;
  line-height: 1.5;
}

.state-block.error {
  color: #503c68;
  background: #f4f0f8;
  border-color: #c9bdd9;
}

@media (max-width: 58rem) {
  .login-page {
    padding: 1.25rem;
  }

  .login-shell {
    width: min(100%, 36rem);
    min-height: auto;
    grid-template-columns: 1fr;
  }

  .brand-panel {
    gap: 2.5rem;
    padding: 1.25rem 1.5rem;
  }

  .brand-intro {
    max-width: 29rem;
    margin: 0;
  }

  .brand-intro h2 {
    max-width: none;
    font-size: clamp(1.9rem, 5vw, 2.5rem);
  }

  .brand-intro > p:last-child {
    max-width: 29rem;
  }

  .brand-mark {
    width: 2.5rem;
    height: 2.5rem;
  }

  .brand-mark svg {
    width: 1.5rem;
    height: 1.5rem;
  }

  .brand-footer {
    font-size: 0.7rem;
  }

  .login-panel {
    padding: clamp(2rem, 7vw, 3.5rem);
  }
}

@media (max-width: 32rem) {
  .login-page {
    padding: 0.5rem;
  }

  .login-shell {
    border-radius: 1rem;
  }

  .brand-panel {
    gap: 2rem;
    padding: 1rem 1.25rem 1.25rem;
  }

  .brand-caption {
    display: none;
  }

  .brand-intro h2 {
    font-size: 1.9rem;
  }

  .brand-kicker {
    font-size: 0.66rem;
  }

  .login-panel {
    padding: 2rem 1.25rem;
  }
}
</style>
