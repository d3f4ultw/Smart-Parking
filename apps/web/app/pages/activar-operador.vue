<script setup lang="ts">
import { onMounted } from 'vue'
import {
  ErrorActivacionOperador,
  completarActivacionOperador,
  validarInvitacionOperador,
} from '~/utils/activacion-operador-api'

type EstadoActivacion =
  | 'preparando'
  | 'validando'
  | 'formulario'
  | 'enlaceAusente'
  | 'invalida'
  | 'bloqueada'
  | 'error'
  | 'completada'

const LONGITUD_MINIMA_CONTRASENA = 10
const estado = ref<EstadoActivacion>('preparando')
const tokenTemporal = ref<string | null>(null)
const contrasena = ref('')
const mostrarContrasena = ref(false)
const errorContrasena = ref('')
const errorFormulario = ref('')
const enviando = ref(false)
const csrf = useCsrf()
const cumpleLongitudMinima = computed(
  () => Array.from(contrasena.value).length >= LONGITUD_MINIMA_CONTRASENA,
)

if (import.meta.server) {
  useResponseHeader('cache-control').value = 'no-store, private'
  useResponseHeader('referrer-policy').value = 'no-referrer'
}

useHead({ title: 'Activar cuenta | Smart Parking' })
onMounted(() => void leerYValidarInvitacion())

async function leerYValidarInvitacion() {
  const fragmento = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : ''
  window.history.replaceState(
    window.history.state,
    '',
    window.location.pathname + window.location.search,
  )
  if (!fragmento) {
    estado.value = 'enlaceAusente'
    return
  }
  if (fragmento.length > 512) {
    estado.value = 'invalida'
    return
  }
  tokenTemporal.value = fragmento
  await validarToken()
}

async function validarToken() {
  const token = tokenTemporal.value
  if (!token) {
    estado.value = 'invalida'
    return
  }
  estado.value = 'validando'
  errorContrasena.value = ''
  errorFormulario.value = ''
  try {
    const csrfToken = await csrf.obtener()
    await validarInvitacionOperador(token, csrfToken)
    estado.value = 'formulario'
  } catch (fallo) {
    if (fallo instanceof ErrorActivacionOperador && fallo.estado === 403) csrf.limpiar()
    if (fallo instanceof ErrorActivacionOperador && fallo.estado === 410) {
      tokenTemporal.value = null
      estado.value = 'invalida'
    } else if (fallo instanceof ErrorActivacionOperador && fallo.estado === 429) {
      estado.value = 'bloqueada'
      errorFormulario.value = fallo.message
    } else {
      estado.value = 'error'
      errorFormulario.value =
        fallo instanceof ErrorActivacionOperador
          ? fallo.message
          : 'No pudimos comprobar el enlace. Revisa tu conexión e inténtalo de nuevo.'
    }
  }
}

function validarContrasena() {
  errorContrasena.value = ''
  errorFormulario.value = ''
  if (!contrasena.value) {
    errorContrasena.value = 'Ingresa una contraseña.'
    return false
  }
  if (!cumpleLongitudMinima.value) {
    errorContrasena.value = 'La contraseña debe tener al menos 10 caracteres.'
    return false
  }
  return true
}

async function activarCuenta() {
  if (enviando.value || !validarContrasena()) return
  const token = tokenTemporal.value
  if (!token) {
    estado.value = 'invalida'
    return
  }

  enviando.value = true
  errorFormulario.value = ''
  try {
    const csrfToken = await csrf.obtener()
    await completarActivacionOperador(token, contrasena.value, csrfToken)
    tokenTemporal.value = null
    contrasena.value = ''
    errorContrasena.value = ''
    estado.value = 'completada'
  } catch (fallo) {
    if (fallo instanceof ErrorActivacionOperador && fallo.estado === 403) csrf.limpiar()
    if (fallo instanceof ErrorActivacionOperador && fallo.estado === 429) {
      contrasena.value = ''
      errorContrasena.value = ''
      estado.value = 'bloqueada'
      errorFormulario.value = fallo.message
      return
    }
    if (fallo instanceof ErrorActivacionOperador && fallo.estado === 410) {
      tokenTemporal.value = null
      contrasena.value = ''
      errorContrasena.value = ''
      estado.value = 'invalida'
      return
    }
    if (fallo instanceof ErrorActivacionOperador && fallo.estado === 400) {
      errorContrasena.value = fallo.message
    } else {
      errorFormulario.value =
        fallo instanceof ErrorActivacionOperador
          ? fallo.message
          : 'No pudimos activar la cuenta. Revisa tu conexión e inténtalo de nuevo.'
    }
  } finally {
    enviando.value = false
  }
}

function limpiarErrorContrasena() {
  errorContrasena.value = ''
}
</script>

<template>
  <main class="pagina-activacion">
    <section class="tarjeta-activacion" aria-labelledby="titulo-activacion">
      <header class="marca-activacion">
        <span class="simbolo-activacion" aria-hidden="true">
          <UIcon name="i-lucide-square-parking" />
        </span>
        <span>SMART PARKING</span>
      </header>

      <div class="contenido-activacion">
        <h1 id="titulo-activacion">Activar cuenta</h1>

        <p
          v-if="estado === 'preparando' || estado === 'validando'"
          class="estado-activacion"
          role="status"
        >
          Comprobando la invitación…
        </p>
        <div v-else-if="estado === 'formulario'" class="formulario-activacion-contenedor">
          <form class="formulario-activacion" novalidate @submit.prevent="activarCuenta">
            <UFormField
              class="w-full"
              label="Contraseña"
              name="contrasena"
              :error="errorContrasena || undefined"
              :ui="{ error: 'empty:hidden' }"
            >
              <UInput
                id="activacion-contrasena"
                class="w-full"
                v-model="contrasena"
                name="password"
                :type="mostrarContrasena ? 'text' : 'password'"
                autocomplete="new-password"
                required
                :disabled="enviando"
                :aria-invalid="Boolean(errorContrasena)"
                aria-description="Mínimo 10 caracteres."
                @update:model-value="limpiarErrorContrasena"
              >
                <template #trailing>
                  <UButton
                    type="button"
                    color="neutral"
                    variant="link"
                    size="sm"
                    :icon="mostrarContrasena ? 'i-lucide-eye-off' : 'i-lucide-eye'"
                    :aria-label="mostrarContrasena ? 'Ocultar contraseña' : 'Mostrar contraseña'"
                    :aria-pressed="mostrarContrasena"
                    aria-controls="activacion-contrasena"
                    @click="mostrarContrasena = !mostrarContrasena"
                  />
                </template>
              </UInput>
              <template #error="{ error }">
                <span v-if="error" role="alert">{{ error }}</span>
              </template>
            </UFormField>
            <p
              v-if="cumpleLongitudMinima"
              class="indicador-contrasena"
              role="status"
              aria-label="La contraseña cumple con el mínimo de 10 caracteres."
              data-testid="indicador-contrasena-valida"
            >
              <UIcon name="i-lucide-check" aria-hidden="true" />
            </p>
            <p v-if="errorFormulario" class="error-activacion" role="alert">
              {{ errorFormulario }}
            </p>
            <UButton
              type="submit"
              class="w-full justify-center"
              :loading="enviando"
              :disabled="enviando"
            >
              {{ enviando ? 'Activando…' : 'Activar cuenta' }}
            </UButton>
          </form>
        </div>
        <div
          v-else-if="estado === 'completada'"
          class="resultado-activacion estado-activacion--exito"
          role="status"
        >
          <UIcon name="i-lucide-circle-check" aria-hidden="true" />
          <p>Tu cuenta está lista.</p>
          <p>Puedes cerrar esta página.</p>
        </div>
        <div v-else-if="estado === 'enlaceAusente'" class="resultado-activacion" role="status">
          <p>No encontramos el enlace de activación en esta página.</p>
          <p>Vuelve a abrir la invitación desde el correo.</p>
        </div>
        <div
          v-else-if="estado === 'invalida'"
          class="resultado-activacion estado-activacion--error"
          role="alert"
        >
          <p>Este enlace venció o ya se usó.</p>
          <p>Pide otra invitación al propietario.</p>
        </div>
        <div
          v-else
          class="resultado-activacion"
          :class="{ 'estado-activacion--error': estado === 'bloqueada' }"
        >
          <p role="alert">{{ errorFormulario }}</p>
          <UButton color="neutral" variant="outline" @click="validarToken">
            Comprobar de nuevo
          </UButton>
        </div>
      </div>
    </section>
  </main>
</template>

<style scoped>
.pagina-activacion {
  display: grid;
  min-height: 100vh;
  min-height: 100svh;
  padding: clamp(16px, 4vw, 40px);
  place-items: center;
  font-family: 'Manrope Variable', ui-sans-serif, system-ui, sans-serif;
}
.tarjeta-activacion {
  display: grid;
  width: min(100%, 32rem);
  gap: 28px;
  border: 1px solid var(--app-border);
  border-radius: 18px;
  padding: clamp(24px, 5vw, 36px);
  background: var(--app-surface);
  box-shadow: 0 16px 44px rgb(41 37 47 / 7%);
}
.marca-activacion {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--app-primary);
  font-size: 0.78rem;
  font-weight: 750;
  letter-spacing: 0.1em;
}
.simbolo-activacion {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border-radius: 12px;
  background: var(--app-surface-hover);
  font-size: 1.25rem;
}
.contenido-activacion {
  display: grid;
  gap: 12px;
}
.contenido-activacion h1 {
  margin: 0;
  color: var(--app-foreground);
  font-size: clamp(1.8rem, 5vw, 2.15rem);
  font-weight: 650;
  letter-spacing: -0.04em;
  line-height: 1.15;
}
.estado-activacion,
.resultado-activacion {
  color: var(--app-muted);
  line-height: 1.55;
}
.estado-activacion,
.resultado-activacion p {
  margin: 0;
}
.formulario-activacion {
  display: grid;
  gap: 16px;
}
.formulario-activacion :deep(input),
.formulario-activacion :deep(button) {
  min-height: 44px;
}
.formulario-activacion :deep(input) {
  width: 100%;
}
.formulario-activacion :deep(button[type='submit']) {
  width: 100%;
}
.indicador-contrasena {
  display: flex;
  min-height: 16px;
  justify-content: flex-end;
  margin: -8px 0 0;
  color: var(--app-success);
  font-size: 1rem;
}
.error-activacion,
.estado-activacion--error {
  color: var(--app-error);
}
.error-activacion {
  margin: 0;
}
.resultado-activacion {
  display: grid;
  gap: 10px;
  justify-items: start;
}
.estado-activacion--exito {
  color: var(--app-success);
}
.estado-activacion--exito :deep(svg) {
  width: 28px;
  height: 28px;
}
@media (max-width: 480px) {
  .tarjeta-activacion {
    gap: 24px;
    border-radius: 16px;
    padding: 24px;
  }
}
</style>
