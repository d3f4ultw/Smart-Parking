<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import {
  evaluarRequisitosNuevaContrasenaOperador,
  extraerTokenInvitacionOperador,
  rutaActivacionSinToken,
  validarNuevaContrasenaOperador,
} from '~/utils/activacion-operador'

useHead({
  meta: [{ name: 'referrer', content: 'no-referrer' }],
})

const router = useRouter()
const estado = ref<
  'verificando' | 'intercambiando' | 'requerido' | 'formulario' | 'enviando' | 'exito' | 'invalido' | 'error'
>('verificando')
const formulario = reactive({ nuevaContrasena: '', confirmarContrasena: '' })
const mensajeError = ref('')
const mostrarNuevaContrasena = ref(false)
const mostrarConfirmarContrasena = ref(false)
const mostrarEstadoRequisitos = computed(() => formulario.nuevaContrasena.length > 0)
const requisitosContrasena = computed(() =>
  evaluarRequisitosNuevaContrasenaOperador(formulario.nuevaContrasena),
)

function limpiarFormulario() {
  formulario.nuevaContrasena = ''
  formulario.confirmarContrasena = ''
  mostrarNuevaContrasena.value = false
  mostrarConfirmarContrasena.value = false
}

async function quitarTokenDeLaUrl() {
  if (window.location.pathname === '/activar-cuenta' && window.location.search) {
    await router.replace(rutaActivacionSinToken())
  }
}

function obtenerEstadoError(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null) {
    return undefined
  }
  const errorHttp = error as { status?: unknown; statusCode?: unknown }
  if (typeof errorHttp.statusCode === 'number') {
    return errorHttp.statusCode
  }
  return typeof errorHttp.status === 'number' ? errorHttp.status : undefined
}

async function revisarDesafio() {
  try {
    const respuesta = await $fetch<{ valido: boolean }>(
      '/api/autenticacion/activacion-operador/desafio',
      { credentials: 'same-origin', cache: 'no-store' },
    )
    estado.value = respuesta.valido ? 'formulario' : 'requerido'
  } catch {
    estado.value = 'error'
  }
}

onMounted(async () => {
  const token = extraerTokenInvitacionOperador(new URL(window.location.href))
  if (token === null) {
    if (new URL(window.location.href).searchParams.has('token')) {
      await quitarTokenDeLaUrl()
      estado.value = 'invalido'
      return
    }
    await revisarDesafio()
    return
  }

  estado.value = 'intercambiando'
  try {
    await $fetch('/api/autenticacion/activacion-operador/enlace', {
      method: 'POST',
      body: { token },
      credentials: 'same-origin',
      cache: 'no-store',
    })
    estado.value = 'formulario'
  } catch (error: unknown) {
    const status = obtenerEstadoError(error)
    estado.value = status === 404 ? 'invalido' : 'error'
  } finally {
    await quitarTokenDeLaUrl()
  }
})

async function completarActivacion() {
  if (estado.value !== 'formulario') {
    return
  }
  const errorLocal = validarNuevaContrasenaOperador(
    formulario.nuevaContrasena,
    formulario.confirmarContrasena,
  )
  if (errorLocal !== null) {
    mensajeError.value = errorLocal
    return
  }

  estado.value = 'enviando'
  mensajeError.value = ''
  try {
    await $fetch('/api/autenticacion/activacion-operador/completar', {
      method: 'POST',
      body: { nueva_contrasena: formulario.nuevaContrasena },
      credentials: 'same-origin',
      cache: 'no-store',
    })
    limpiarFormulario()
    estado.value = 'exito'
  } catch (error: unknown) {
    limpiarFormulario()
    const status = obtenerEstadoError(error)
    if (status === 404) {
      estado.value = 'invalido'
    } else {
      estado.value = 'formulario'
      mensajeError.value = status === 422
        ? 'La contraseña debe tener de 10 a 128 caracteres imprimibles e incluir una mayúscula.'
        : 'No fue posible activar la cuenta. Intenta nuevamente.'
    }
  }
}
</script>

<template>
  <main class="activation-page">
    <section class="activation-card" aria-labelledby="activation-title">
      <p class="eyebrow">Smart Parking</p>
      <h1 id="activation-title">Activa tu cuenta</h1>

      <div v-if="estado === 'verificando' || estado === 'intercambiando'" class="state-block" role="status">
        <p>Verificando el enlace…</p>
      </div>

      <div v-else-if="estado === 'requerido'" class="state-block" role="status">
        <h2>Enlace de activación requerido</h2>
        <p>Usa el enlace de invitación que recibiste por correo o solicita al administrador que reenvíe la invitación.</p>
      </div>

      <div v-else-if="estado === 'invalido'" class="state-block error" role="alert">
        <h2>Este enlace de activación no es válido o ha expirado.</h2>
        <p>Solicita al administrador que reenvíe la invitación.</p>
      </div>

      <div v-else-if="estado === 'error'" class="state-block error" role="alert">
        <p>No fue posible verificar el enlace. Intenta abrirlo nuevamente desde el correo.</p>
      </div>

      <div v-else-if="estado === 'exito'" class="state-block success" role="status">
        <h2>Cuenta activada</h2>
        <p>Ya puedes iniciar sesión con la contraseña que creaste.</p>
        <NuxtLink class="button primary" to="/login">Ir al inicio de sesión</NuxtLink>
      </div>

      <form v-else class="activation-form" novalidate @submit.prevent="completarActivacion">
        <h2>Crear contraseña</h2>
        <div v-if="mensajeError" class="state-block error" role="alert">
          {{ mensajeError }}
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
              aria-controls="new-password"
              :aria-label="mostrarNuevaContrasena ? 'Ocultar contraseña' : 'Mostrar contraseña'"
              :title="mostrarNuevaContrasena ? 'Ocultar contraseña' : 'Mostrar contraseña'"
              :aria-pressed="mostrarNuevaContrasena"
              @click="mostrarNuevaContrasena = !mostrarNuevaContrasena"
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
                <path v-if="mostrarNuevaContrasena" d="m3 3 18 18" />
              </svg>
            </button>
          </div>
          <ul class="password-requirements" aria-label="Requisitos de la contraseña">
            <li
              :class="{
                'requirement-met': mostrarEstadoRequisitos
                  && requisitosContrasena.longitudMinima
                  && requisitosContrasena.longitudMaxima,
                'requirement-missing': mostrarEstadoRequisitos
                  && (!requisitosContrasena.longitudMinima || !requisitosContrasena.longitudMaxima),
              }"
            >
              <span aria-hidden="true">{{ mostrarEstadoRequisitos ? (requisitosContrasena.longitudMinima && requisitosContrasena.longitudMaxima ? '✓' : '×') : '○' }}</span>
              <span>Entre 10 y 128 caracteres</span>
              <span class="requirement-status">
                {{ !mostrarEstadoRequisitos ? 'Pendiente' : requisitosContrasena.longitudMinima && requisitosContrasena.longitudMaxima ? 'Cumple' : 'Falta' }}
              </span>
            </li>
            <li
              :class="{
                'requirement-met': mostrarEstadoRequisitos && requisitosContrasena.caracteresImprimibles,
                'requirement-missing': mostrarEstadoRequisitos && !requisitosContrasena.caracteresImprimibles,
              }"
            >
              <span aria-hidden="true">{{ mostrarEstadoRequisitos ? (requisitosContrasena.caracteresImprimibles ? '✓' : '×') : '○' }}</span>
              <span>Solo caracteres imprimibles</span>
              <span class="requirement-status">
                {{ !mostrarEstadoRequisitos ? 'Pendiente' : requisitosContrasena.caracteresImprimibles ? 'Cumple' : 'Falta' }}
              </span>
            </li>
            <li
              :class="{
                'requirement-met': mostrarEstadoRequisitos && requisitosContrasena.mayuscula,
                'requirement-missing': mostrarEstadoRequisitos && !requisitosContrasena.mayuscula,
              }"
            >
              <span aria-hidden="true">{{ mostrarEstadoRequisitos ? (requisitosContrasena.mayuscula ? '✓' : '×') : '○' }}</span>
              <span>Al menos una letra mayúscula</span>
              <span class="requirement-status">
                {{ !mostrarEstadoRequisitos ? 'Pendiente' : requisitosContrasena.mayuscula ? 'Cumple' : 'Falta' }}
              </span>
            </li>
          </ul>
        </div>
        <div class="field-group">
          <label for="confirm-password">Confirmar contraseña</label>
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
              aria-controls="confirm-password"
              :aria-label="mostrarConfirmarContrasena ? 'Ocultar contraseña' : 'Mostrar contraseña'"
              :title="mostrarConfirmarContrasena ? 'Ocultar contraseña' : 'Mostrar contraseña'"
              :aria-pressed="mostrarConfirmarContrasena"
              @click="mostrarConfirmarContrasena = !mostrarConfirmarContrasena"
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
                <path v-if="mostrarConfirmarContrasena" d="m3 3 18 18" />
              </svg>
            </button>
          </div>
        </div>
        <button class="button primary" type="submit" :disabled="estado === 'enviando'">
          {{ estado === 'enviando' ? 'Activando…' : 'Activar cuenta' }}
        </button>
      </form>
    </section>
  </main>
</template>

<style scoped>
:global(*) { box-sizing: border-box; }
:global(body) {
  margin: 0;
  color: #18324b;
  background: #edf5f8;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.activation-page { display: grid; min-height: 100vh; padding: 1rem; place-items: center; }
.activation-card {
  width: min(100%, 36rem);
  padding: clamp(1.5rem, 4vw, 2.75rem);
  background: #fff;
  border: 1px solid #d6e5ea;
  border-radius: 1.25rem;
  box-shadow: 0 1.5rem 4rem rgb(24 50 75 / 12%);
}
.eyebrow { margin: 0 0 .5rem; color: #0d7286; font-size: .8rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
h1 { margin: 0 0 1.5rem; color: #102a43; font-size: clamp(1.8rem, 5vw, 2.4rem); }
h2 { margin-top: 0; }
.activation-form, .field-group { display: grid; gap: 1rem; }
.field-group { gap: .45rem; }
label { color: #244a66; font-size: .95rem; font-weight: 650; }
input { width: 100%; min-height: 2.9rem; padding: .7rem .8rem; color: #102a43; background: #fbfdfe; border: 1px solid #b6ced8; border-radius: .55rem; font: inherit; }
input:focus { border-color: #0d7286; outline: 3px solid rgb(13 114 134 / 18%); }
.password-control { display: flex; align-items: stretch; }
.password-control input { min-width: 0; border-radius: .55rem 0 0 .55rem; }
.password-control:focus-within { border-radius: .55rem; outline: 3px solid rgb(13 114 134 / 18%); }
.password-control input:focus { border-color: #0d7286; outline: none; }
.password-requirements {
  display: grid;
  gap: .35rem;
  margin: .25rem 0 0;
  padding: .75rem .85rem;
  background: #f4f8fa;
  border: 1px solid #d6e5ea;
  border-radius: .55rem;
  list-style: none;
}
.password-requirements li { display: flex; align-items: center; gap: .5rem; color: #526779; font-size: .875rem; }
.password-requirements li.requirement-met { color: #21623b; }
.password-requirements li.requirement-missing { color: #9a3f32; }
.requirement-status { margin-left: auto; font-weight: 650; }
.visibility-button {
  display: inline-flex;
  min-width: 2.9rem;
  align-items: center;
  justify-content: center;
  padding: .65rem;
  color: #0d6071;
  background: #eef7f9;
  border: 1px solid #b6ced8;
  border-left: 0;
  border-radius: 0 .55rem .55rem 0;
  font: inherit;
  font-size: .9rem;
  font-weight: 650;
  cursor: pointer;
}
.visibility-button svg { width: 1.2rem; height: 1.2rem; }
.visibility-button:hover, .visibility-button:focus-visible { color: #084b59; background: #dceff2; }
.visibility-button:focus-visible { outline: 2px solid #0d7286; outline-offset: -3px; }
.button { display: inline-flex; min-height: 2.9rem; align-items: center; justify-content: center; padding: .7rem 1rem; border: 0; border-radius: .55rem; font: inherit; font-weight: 700; text-decoration: none; cursor: pointer; }
.button:disabled { cursor: wait; opacity: .65; }
.primary { color: #fff; background: #0d7286; }
.state-block { padding: 1rem; background: #f4f8fa; border: 1px solid #d6e5ea; border-radius: .75rem; }
.state-block p:last-child { margin-bottom: 0; }
.state-block.error { background: #fff5f3; border-color: #edc2ba; }
.state-block.success { background: #eef9f2; border-color: #b8dfc3; }
@media (max-width: 32rem) { .activation-page { padding: .75rem; } }
</style>
