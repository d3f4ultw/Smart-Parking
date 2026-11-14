<script setup lang="ts">
import { onMounted } from 'vue'
import {
  completarRecuperacionOperador,
  ErrorRecuperacionOperador,
  validarTokenRecuperacion,
} from '~/utils/recuperacion-operador-api'

type EstadoRecuperacion =
  | 'preparando'
  | 'validando'
  | 'formulario'
  | 'invalida'
  | 'bloqueada'
  | 'error'
  | 'completada'

const estado = ref<EstadoRecuperacion>('preparando')
const tokenTemporal = ref<string | null>(null)
const contrasena = ref('')
const confirmarContrasena = ref('')
const mostrarContrasena = ref(false)
const mostrarConfirmacion = ref(false)
const errorFormulario = ref('')
const enviando = ref(false)
const csrf = useCsrf()

if (import.meta.server) {
  useResponseHeader('cache-control').value = 'no-store, private'
  useResponseHeader('referrer-policy').value = 'no-referrer'
}

useHead({
  title: 'Cambiar contraseña | Smart Parking',
  meta: [{ name: 'referrer', content: 'no-referrer' }],
})
onMounted(() => void leerYValidarToken())

async function leerYValidarToken() {
  const fragmento = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : ''
  window.history.replaceState(
    window.history.state,
    '',
    window.location.pathname + window.location.search,
  )
  if (!fragmento || fragmento.length > 512) {
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
  errorFormulario.value = ''
  try {
    await validarTokenRecuperacion(token, await csrf.obtener())
    estado.value = 'formulario'
  } catch (fallo) {
    if (fallo instanceof ErrorRecuperacionOperador && fallo.estado === 403) csrf.limpiar()
    if (fallo instanceof ErrorRecuperacionOperador && fallo.estado === 410) {
      tokenTemporal.value = null
      estado.value = 'invalida'
    } else if (fallo instanceof ErrorRecuperacionOperador && fallo.estado === 429) {
      estado.value = 'bloqueada'
      errorFormulario.value = fallo.message
    } else {
      estado.value = 'error'
      errorFormulario.value =
        fallo instanceof ErrorRecuperacionOperador
          ? fallo.message
          : 'No pudimos comprobar el enlace. Revisa tu conexión e inténtalo de nuevo.'
    }
  }
}

function validarContrasenas() {
  errorFormulario.value = ''
  if (Array.from(contrasena.value).length < 10) {
    errorFormulario.value = 'Elige una contraseña más larga.'
    return false
  }
  if (contrasena.value !== confirmarContrasena.value) {
    errorFormulario.value = 'Las contraseñas no coinciden.'
    return false
  }
  return true
}

async function restablecerContrasena() {
  if (enviando.value || !validarContrasenas()) return
  const token = tokenTemporal.value
  if (!token) {
    estado.value = 'invalida'
    return
  }

  enviando.value = true
  errorFormulario.value = ''
  try {
    await completarRecuperacionOperador(
      token,
      contrasena.value,
      confirmarContrasena.value,
      await csrf.obtener(),
    )
    tokenTemporal.value = null
    contrasena.value = ''
    confirmarContrasena.value = ''
    estado.value = 'completada'
  } catch (fallo) {
    if (fallo instanceof ErrorRecuperacionOperador && fallo.estado === 403) csrf.limpiar()
    if (fallo instanceof ErrorRecuperacionOperador && fallo.estado === 429) {
      contrasena.value = ''
      confirmarContrasena.value = ''
      estado.value = 'bloqueada'
      errorFormulario.value = fallo.message
    } else if (fallo instanceof ErrorRecuperacionOperador && fallo.estado === 410) {
      tokenTemporal.value = null
      contrasena.value = ''
      confirmarContrasena.value = ''
      estado.value = 'invalida'
    } else {
      errorFormulario.value =
        fallo instanceof ErrorRecuperacionOperador
          ? fallo.message
          : 'No pudimos cambiar la contraseña. Revisa tu conexión e inténtalo de nuevo.'
    }
  } finally {
    enviando.value = false
  }
}
</script>

<template>
  <main class="pagina-recuperacion">
    <section class="tarjeta-recuperacion" aria-labelledby="titulo-recuperacion">
      <header class="marca-recuperacion">
        <span class="simbolo-recuperacion" aria-hidden="true">
          <UIcon name="i-lucide-square-parking" />
        </span>
        <span>SMART PARKING</span>
      </header>

      <div class="contenido-recuperacion">
        <p class="sobrelinea">Tu cuenta</p>
        <h1 id="titulo-recuperacion">Cambiar contraseña</h1>

        <p
          v-if="estado === 'preparando' || estado === 'validando'"
          class="estado-recuperacion"
          role="status"
        >
          Comprobando el enlace…
        </p>
        <div v-else-if="estado === 'formulario'" class="formulario-recuperacion-contenedor">
          <p class="descripcion-recuperacion">Elige una contraseña nueva para tu cuenta.</p>
          <form class="formulario-recuperacion" @submit.prevent="restablecerContrasena">
            <UFormField label="Contraseña nueva" name="contrasena">
              <UInput
                id="recuperacion-contrasena"
                v-model="contrasena"
                :type="mostrarContrasena ? 'text' : 'password'"
                autocomplete="new-password"
                required
                :disabled="enviando"
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
                    aria-controls="recuperacion-contrasena"
                    @click="mostrarContrasena = !mostrarContrasena"
                  />
                </template>
              </UInput>
            </UFormField>
            <UFormField label="Confirmar contraseña nueva" name="confirmarContrasena">
              <UInput
                id="recuperacion-confirmar-contrasena"
                v-model="confirmarContrasena"
                :type="mostrarConfirmacion ? 'text' : 'password'"
                autocomplete="new-password"
                required
                :disabled="enviando"
              >
                <template #trailing>
                  <UButton
                    type="button"
                    color="neutral"
                    variant="link"
                    size="sm"
                    :icon="mostrarConfirmacion ? 'i-lucide-eye-off' : 'i-lucide-eye'"
                    :aria-label="mostrarConfirmacion ? 'Ocultar contraseña' : 'Mostrar contraseña'"
                    :aria-pressed="mostrarConfirmacion"
                    aria-controls="recuperacion-confirmar-contrasena"
                    @click="mostrarConfirmacion = !mostrarConfirmacion"
                  />
                </template>
              </UInput>
            </UFormField>
            <p class="ayuda-contrasena">
              Elige una contraseña larga. Las mayúsculas y minúsculas cuentan como distintas.
            </p>
            <p v-if="errorFormulario" class="error-recuperacion" role="alert">
              {{ errorFormulario }}
            </p>
            <UButton
              type="submit"
              icon="i-lucide-shield-check"
              :loading="enviando"
              :disabled="enviando"
            >
              Cambiar contraseña
            </UButton>
          </form>
        </div>
        <div
          v-else-if="estado === 'completada'"
          class="resultado-recuperacion estado-recuperacion--exito"
          role="status"
        >
          <UIcon name="i-lucide-circle-check" aria-hidden="true" />
          <p>Tu contraseña cambió.</p>
          <p>Puedes cerrar esta página.</p>
        </div>
        <div
          v-else-if="estado === 'invalida'"
          class="resultado-recuperacion estado-recuperacion--error"
          role="alert"
        >
          <p>Este enlace venció o ya se usó.</p>
          <p>Pide al propietario un enlace nuevo.</p>
        </div>
        <div
          v-else
          class="resultado-recuperacion"
          :class="{ 'estado-recuperacion--error': estado === 'bloqueada' }"
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
.pagina-recuperacion {
  display: grid;
  min-height: 100vh;
  padding: clamp(16px, 4vw, 48px);
  place-items: center;
  font-family: 'Manrope Variable', ui-sans-serif, system-ui, sans-serif;
}
.tarjeta-recuperacion {
  display: grid;
  width: min(100%, 34rem);
  gap: 32px;
  border: 1px solid var(--app-border);
  border-radius: 20px;
  padding: clamp(24px, 5vw, 40px);
  background: var(--app-surface);
  box-shadow: 0 18px 56px rgb(41 37 47 / 8%);
}
.marca-recuperacion {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--app-primary);
  font-size: 0.78rem;
  font-weight: 750;
  letter-spacing: 0.1em;
}
.simbolo-recuperacion {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border-radius: 12px;
  background: var(--app-surface-hover);
  font-size: 1.25rem;
}
.contenido-recuperacion {
  display: grid;
  gap: 16px;
}
.contenido-recuperacion h1 {
  margin: -8px 0 4px;
  color: var(--app-foreground);
  font-size: clamp(1.5rem, 5vw, 2rem);
}
.sobrelinea {
  margin: 0;
  color: var(--app-primary);
  font-size: 0.75rem;
  font-weight: 750;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
.formulario-recuperacion-contenedor,
.formulario-recuperacion,
.resultado-recuperacion {
  display: grid;
  gap: 16px;
}
.descripcion-recuperacion,
.ayuda-contrasena,
.resultado-recuperacion p,
.estado-recuperacion {
  margin: 0;
  color: var(--app-muted);
  line-height: 1.55;
}
.error-recuperacion,
.estado-recuperacion--error {
  color: var(--app-error) !important;
}
.resultado-recuperacion {
  justify-items: start;
}
.resultado-recuperacion :deep(button) {
  margin-top: 4px;
}
.estado-recuperacion--exito :deep(svg) {
  color: var(--app-success);
  font-size: 1.5rem;
}
</style>
