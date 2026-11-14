<script setup lang="ts">
import { ErrorClienteApi, useClienteApi } from '~/utils/cliente-api'

/** Un mismo formulario sirve para crear una cuenta o iniciar sesión,
 * según el modo que recibe la página.
 */
const props = defineProps<{ modo: 'registro' | 'acceso' }>()
const LONGITUD_MINIMA_CONTRASENA = 10
const api = useClienteApi()
const csrf = useCsrfCliente()
const nombres = ref('')
const primerApellido = ref('')
const segundoApellido = ref('')
const correo = ref('')
const contrasena = ref('')
const errorGeneral = ref('')
const errores = reactive<Record<string, string>>({})
const enviando = ref(false)
const modoRegistro = computed(() => props.modo === 'registro')
const mostrarContrasena = ref(false)
const contrasenaCumpleLongitud = computed(
  () => Array.from(contrasena.value).length >= LONGITUD_MINIMA_CONTRASENA,
)

function limpiarErrores() {
  for (const campo of Object.keys(errores)) delete errores[campo]
  errorGeneral.value = ''
}

function validar(): boolean {
  limpiarErrores()
  if (modoRegistro.value) {
    if (!nombres.value.trim()) errores.nombres = 'Escribe tu nombre.'
    if (!primerApellido.value.trim()) errores.primerApellido = 'Escribe tu primer apellido.'
    if (!contrasenaCumpleLongitud.value) {
      errores.contrasena = 'La contraseña debe tener al menos 10 caracteres.'
    }
  }
  if (!correo.value.trim()) errores.correo = 'Escribe tu correo electrónico.'
  if (Object.keys(errores).length) {
    return false
  }
  return true
}

/** Comprueba los datos y pide el código de seguridad antes de enviar el registro
 * o el acceso; si se inicia sesión, lleva al cliente a su portal.
 */
async function enviar() {
  if (enviando.value || !validar()) return
  enviando.value = true
  try {
    const token = await csrf.obtener()
    if (modoRegistro.value) {
      await api.registrar(
        {
          nombres: nombres.value.trim(),
          primerApellido: primerApellido.value.trim(),
          segundoApellido: segundoApellido.value.trim() || null,
          correo: correo.value.trim(),
          contrasena: contrasena.value,
        },
        token,
      )
      await navigateTo('/clientes/acceso?registro=1')
      return
    }

    const sesion = await api.iniciarSesion(
      { correo: correo.value.trim(), contrasena: contrasena.value },
      token,
    )
    csrf.actualizar(sesion.csrfToken)
    await navigateTo('/clientes/portal')
  } catch (fallo) {
    csrf.manejarFallo(fallo)
    errorGeneral.value =
      fallo instanceof ErrorClienteApi
        ? fallo.message
        : 'No pudimos completar la solicitud. Inténtalo de nuevo.'
  } finally {
    enviando.value = false
  }
}

const tituloContrasena = computed(() => (modoRegistro.value ? 'Crear contraseña' : 'Contraseña'))
const textoBoton = computed(() => (modoRegistro.value ? 'Crear cuenta' : 'Iniciar sesión'))

useHead({
  title: computed(() =>
    modoRegistro.value ? 'Crear cuenta | Smart Parking' : 'Acceso de cliente | Smart Parking',
  ),
  meta: [{ name: 'referrer', content: 'no-referrer' }],
})
</script>

<template>
  <form class="formulario-cliente" :aria-busy="enviando" @submit.prevent="enviar">
    <div v-if="modoRegistro" class="grupo-campos">
      <div class="campo-cliente">
        <label for="cliente-nombres">Nombre</label>
        <UInput
          id="cliente-nombres"
          v-model="nombres"
          autocomplete="given-name"
          required
          :disabled="enviando"
          :aria-invalid="Boolean(errores.nombres)"
          :aria-describedby="errores.nombres ? 'error-nombres' : undefined"
        />
        <p v-if="errores.nombres" id="error-nombres" class="error-campo">{{ errores.nombres }}</p>
      </div>
      <div class="campo-cliente">
        <label for="cliente-primer-apellido">Primer apellido</label>
        <UInput
          id="cliente-primer-apellido"
          v-model="primerApellido"
          autocomplete="family-name"
          required
          :disabled="enviando"
          :aria-invalid="Boolean(errores.primerApellido)"
          :aria-describedby="errores.primerApellido ? 'error-primer-apellido' : undefined"
        />
        <p v-if="errores.primerApellido" id="error-primer-apellido" class="error-campo">
          {{ errores.primerApellido }}
        </p>
      </div>
      <div class="campo-cliente">
        <label for="cliente-segundo-apellido">Segundo apellido <span>(opcional)</span></label>
        <UInput
          id="cliente-segundo-apellido"
          v-model="segundoApellido"
          autocomplete="additional-name"
          :disabled="enviando"
        />
      </div>
    </div>

    <div class="campo-cliente">
      <label for="cliente-correo">Correo electrónico</label>
      <UInput
        id="cliente-correo"
        v-model="correo"
        type="email"
        autocomplete="email"
        inputmode="email"
        required
        :disabled="enviando"
        :aria-invalid="Boolean(errores.correo)"
        :aria-describedby="errores.correo ? 'error-correo' : undefined"
      />
      <p v-if="errores.correo" id="error-correo" class="error-campo">{{ errores.correo }}</p>
    </div>

    <div class="campo-cliente">
      <label for="cliente-contrasena">{{ tituloContrasena }}</label>
      <UInput
        id="cliente-contrasena"
        v-model="contrasena"
        :type="mostrarContrasena ? 'text' : 'password'"
        :autocomplete="modoRegistro ? 'new-password' : 'current-password'"
        required
        :disabled="enviando"
        :aria-invalid="Boolean(errores.contrasena)"
        :aria-describedby="
          modoRegistro
            ? [errores.contrasena ? 'error-contrasena' : '', 'ayuda-contrasena']
                .filter(Boolean)
                .join(' ')
            : undefined
        "
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
            aria-controls="cliente-contrasena"
            @click="mostrarContrasena = !mostrarContrasena"
          />
        </template>
      </UInput>
      <p
        v-if="modoRegistro"
        id="ayuda-contrasena"
        class="ayuda-campo ayuda-contrasena"
        :class="{ 'ayuda-contrasena--cumple': contrasenaCumpleLongitud }"
      >
        <span class="indicador-contrasena" aria-hidden="true">
          {{ contrasenaCumpleLongitud ? '✓' : '' }}
        </span>
        <span>Usa al menos 10 caracteres</span>
      </p>
      <p v-if="errores.contrasena" id="error-contrasena" class="error-campo">
        {{ errores.contrasena }}
      </p>
    </div>

    <p v-if="errorGeneral" class="error-general" role="alert">{{ errorGeneral }}</p>
    <UButton
      class="boton-enviar-cliente"
      type="submit"
      :loading="enviando"
      :disabled="enviando || !contrasenaCumpleLongitud"
      :aria-label="enviando ? 'Enviando solicitud' : undefined"
    >
      {{ textoBoton }}
    </UButton>
    <p class="enlace-formulario">
      <template v-if="modoRegistro">
        ¿Ya tienes una cuenta?
        <NuxtLink to="/clientes/acceso">Inicia sesión</NuxtLink>
      </template>
      <template v-else>
        ¿Aún no tienes cuenta?
        <NuxtLink to="/clientes/registro">Crear cuenta</NuxtLink>
      </template>
    </p>
  </form>
</template>

<style scoped>
.formulario-cliente,
.grupo-campos {
  display: grid;
  gap: 18px;
}
.grupo-campos {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.grupo-campos .campo-cliente:first-child {
  grid-column: 1 / -1;
}
.campo-cliente {
  display: grid;
  min-width: 0;
  gap: 7px;
}
.campo-cliente label {
  color: var(--app-foreground);
  font-size: 0.9rem;
  font-weight: 650;
}
.campo-cliente label span,
.ayuda-campo,
.enlace-formulario {
  color: var(--app-muted);
  font-size: 0.84rem;
  font-weight: 400;
}
.campo-cliente :deep(input) {
  min-height: 44px;
  border-radius: 10px;
}
.error-campo,
.error-general {
  margin: 0;
  color: var(--app-error);
  font-size: 0.84rem;
}
.ayuda-campo {
  margin: 0;
  line-height: 1.45;
}
.ayuda-contrasena {
  display: flex;
  align-items: center;
  gap: 8px;
}
.indicador-contrasena {
  display: grid;
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  place-items: center;
  border: 1px solid var(--app-border);
  border-radius: 50%;
  color: transparent;
  font-size: 0.72rem;
  font-weight: 800;
  line-height: 1;
}
.ayuda-contrasena--cumple {
  color: var(--app-success);
}
.ayuda-contrasena--cumple .indicador-contrasena {
  border-color: var(--app-success);
  background: color-mix(in srgb, var(--app-success) 10%, var(--app-surface));
  color: var(--app-success);
}
.error-general {
  border: 1px solid color-mix(in srgb, var(--app-error) 24%, transparent);
  border-radius: 10px;
  background: color-mix(in srgb, var(--app-error) 5%, white);
  padding: 11px 13px;
}
.boton-enviar-cliente {
  min-height: 44px;
  justify-content: center;
  border-radius: 10px;
}
.enlace-formulario {
  margin: 0;
  text-align: center;
}
.enlace-formulario a {
  color: var(--app-primary);
  font-weight: 700;
  text-decoration: underline;
  text-underline-offset: 3px;
}
@media (max-width: 34rem) {
  .grupo-campos {
    grid-template-columns: minmax(0, 1fr);
  }
  .grupo-campos .campo-cliente:first-child {
    grid-column: auto;
  }
}
</style>
