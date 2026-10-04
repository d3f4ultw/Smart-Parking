<script setup lang="ts">
import { computed, reactive, ref } from 'vue'

import {
  construirSolicitudCrearOperador,
  mapearErrorOperador,
  obtenerEstadoErrorOperador,
  validarDatosOperador,
  type CampoFormularioOperador,
  type DatosFormularioOperador,
  type ErroresFormularioOperador,
} from '~/utils/operadores'
import { obtenerPaginaSolicitadaOperadores } from '~/utils/gestion-operadores'

definePageMeta({
  middleware: 'sesion-admin',
})

const { crearOperador } = useOperadores()
const { limpiarSesion } = useSesion()
const route = useRoute()
const paginaOrigen = obtenerPaginaSolicitadaOperadores(route.query.pagina)
const rutaListaOperadores = computed(() => paginaOrigen > 1
  ? `/admin/operadores?pagina=${paginaOrigen}`
  : '/admin/operadores')
const rutaCancelar = computed(() => route.query.desde === 'panel'
  ? '/admin'
  : rutaListaOperadores.value)
const formulario = reactive<DatosFormularioOperador>({
  nombre: '',
  apellido_paterno: '',
  apellido_materno: '',
  correo: '',
})
const erroresCampos = ref<ErroresFormularioOperador>({})
const estado = ref<'listo' | 'enviando' | 'exito' | 'error'>('listo')
const mensajeError = ref('')

function alCambiarCampo(campo: CampoFormularioOperador) {
  const erroresRestantes = { ...erroresCampos.value }
  Reflect.deleteProperty(erroresRestantes, campo)
  erroresCampos.value = erroresRestantes
  if (estado.value === 'exito' || estado.value === 'error') {
    estado.value = 'listo'
    mensajeError.value = ''
  }
}

async function enviarFormulario() {
  if (estado.value === 'enviando') {
    return
  }

  const errores = validarDatosOperador(formulario)
  erroresCampos.value = errores
  mensajeError.value = ''
  if (Object.keys(errores).length > 0) {
    estado.value = 'listo'
    return
  }

  estado.value = 'enviando'

  try {
    await crearOperador(construirSolicitudCrearOperador(formulario))
    estado.value = 'exito'
  } catch (error: unknown) {
    const estadoError = obtenerEstadoErrorOperador(error)
    if (estadoError === 401) {
      limpiarSesion()
      await navigateTo('/login', { replace: true })
      return
    }

    estado.value = 'error'
    const mensaje = mapearErrorOperador(estadoError)
    if (estadoError === 409) {
      erroresCampos.value.correo = mensaje
      return
    }
    mensajeError.value = mensaje
  }
}
</script>

<template>
  <main class="operator-page">
    <section class="operator-card" aria-labelledby="operator-title">
      <p class="eyebrow">Smart Parking</p>
      <h1 id="operator-title">CREAR OPERADOR</h1>
      <p class="required-note">* Campos necesarios</p>

      <div v-if="estado === 'exito'" class="state-block success" role="status">
        <p>Operador creado. Se envió una invitación para activar la cuenta.</p>
        <NuxtLink class="button secondary" :to="rutaListaOperadores">
          Volver al listado de operadores
        </NuxtLink>
      </div>

      <div v-if="mensajeError" class="state-block error" role="alert">
        <p>{{ mensajeError }}</p>
      </div>

      <form novalidate @submit.prevent="enviarFormulario">
        <div class="field-group">
          <label for="operator-name">Nombre *</label>
          <input
            id="operator-name"
            v-model="formulario.nombre"
            name="nombre"
            type="text"
            autocomplete="given-name"
            maxlength="100"
            required
            :aria-invalid="Boolean(erroresCampos.nombre)"
            aria-describedby="operator-name-error"
            @input="alCambiarCampo('nombre')"
          >
          <p v-if="erroresCampos.nombre" id="operator-name-error" class="field-error">
            {{ erroresCampos.nombre }}
          </p>
        </div>

        <div class="field-group">
          <label for="operator-last-name">Apellido paterno *</label>
          <input
            id="operator-last-name"
            v-model="formulario.apellido_paterno"
            name="apellido_paterno"
            type="text"
            autocomplete="family-name"
            maxlength="100"
            required
            :aria-invalid="Boolean(erroresCampos.apellido_paterno)"
            aria-describedby="operator-last-name-error"
            @input="alCambiarCampo('apellido_paterno')"
          >
          <p
            v-if="erroresCampos.apellido_paterno"
            id="operator-last-name-error"
            class="field-error"
          >
            {{ erroresCampos.apellido_paterno }}
          </p>
        </div>

        <div class="field-group">
          <label for="operator-second-last-name">Apellido materno *</label>
          <input
            id="operator-second-last-name"
            v-model="formulario.apellido_materno"
            name="apellido_materno"
            type="text"
            autocomplete="additional-name"
            maxlength="100"
            required
            :aria-invalid="Boolean(erroresCampos.apellido_materno)"
            aria-describedby="operator-second-last-name-error"
            @input="alCambiarCampo('apellido_materno')"
          >
          <p
            v-if="erroresCampos.apellido_materno"
            id="operator-second-last-name-error"
            class="field-error"
          >
            {{ erroresCampos.apellido_materno }}
          </p>
        </div>

        <div class="field-group">
          <label for="operator-email">Correo electrónico *</label>
          <input
            id="operator-email"
            v-model="formulario.correo"
            name="correo"
            type="email"
            inputmode="email"
            autocomplete="email"
            maxlength="320"
            required
            :aria-invalid="Boolean(erroresCampos.correo)"
            aria-describedby="operator-email-error"
            @input="alCambiarCampo('correo')"
          >
          <p v-if="erroresCampos.correo" id="operator-email-error" class="field-error">
            {{ erroresCampos.correo }}
          </p>
        </div>

        <div class="form-actions">
          <NuxtLink class="button secondary" :to="rutaCancelar">Cancelar</NuxtLink>
          <button class="button primary" type="submit" :disabled="estado === 'enviando'">
            {{ estado === 'enviando' ? 'Creando…' : 'Crear operador' }}
          </button>
        </div>
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

.operator-page {
  display: grid;
  width: 100%;
  min-height: 100vh;
  padding: 1.5rem;
  place-items: center;
}

.operator-card {
  width: min(100%, 40rem);
  padding: clamp(1.5rem, 4vw, 2.75rem);
  background: #ffffff;
  border: 1px solid #d6e5ea;
  border-radius: 1.25rem;
  box-shadow: 0 1.5rem 4rem rgb(24 50 75 / 12%);
}

.eyebrow {
  margin: 0 0 0.5rem;
  color: #0d7286;
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h1 {
  margin: 0 0 0.5rem;
  color: #102a43;
  font-size: clamp(1.8rem, 5vw, 2.4rem);
}

p {
  line-height: 1.55;
}

.required-note {
  margin: 0 0 1.5rem;
  color: #5c7487;
  font-size: 0.9rem;
}

form {
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

input[aria-invalid="true"] {
  border-color: #b54747;
}

.field-error {
  margin: 0;
  color: #933b3b;
  font-size: 0.9rem;
}

.form-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 0.5rem;
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

.secondary {
  color: #244a66;
  background: #e4eef2;
}

.secondary:hover,
.secondary:focus-visible {
  background: #d6e5ea;
}

.state-block {
  margin: 1rem 0;
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
  .operator-page {
    padding: 0.75rem;
  }

  .operator-card {
    border-radius: 0.9rem;
  }
}
</style>
