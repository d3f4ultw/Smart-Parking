<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'

type EstadoRegistro = 'inicial' | 'enviando' | 'recibido'

const formulario = reactive({
  nombre: '',
  apellido_paterno: '',
  apellido_materno: '',
  correo: '',
  contrasena: '',
})
const estado = ref<EstadoRegistro>('inicial')
const mensajeError = ref('')
const intentoEnvio = ref(false)
const cumpleLongitudContrasena = computed(() => formulario.contrasena.length >= 10)
const cumpleMayusculaContrasena = computed(() => /[A-Z]/.test(formulario.contrasena))

useHead({
  title: 'Registro de cliente | Smart Parking',
  meta: [
    {
      name: 'description',
      content: 'Crea una cuenta de cliente de Smart Parking.',
    },
  ],
})

async function enviarFormulario() {
  if (estado.value === 'enviando') {
    return
  }

  mensajeError.value = ''
  estado.value = 'enviando'
  try {
    await $fetch('/api/clientes/registro', {
      method: 'POST',
      body: {
        nombre: formulario.nombre,
        apellido_paterno: formulario.apellido_paterno,
        ...(formulario.apellido_materno
          ? { apellido_materno: formulario.apellido_materno }
          : {}),
        correo: formulario.correo,
        contrasena: formulario.contrasena,
      },
    })
    Object.assign(formulario, {
      nombre: '',
      apellido_paterno: '',
      apellido_materno: '',
      correo: '',
      contrasena: '',
    })
    estado.value = 'recibido'
  } catch (error: unknown) {
    const codigo = typeof error === 'object' && error !== null && 'statusCode' in error
      ? error.statusCode
      : undefined
    mensajeError.value = codigo === 429
      ? 'Se alcanzó el límite de solicitudes. Inténtalo más tarde.'
      : codigo === 422
        ? 'Revisa los datos e inténtalo de nuevo.'
        : 'No se pudo enviar la solicitud. Inténtalo más tarde.'
    estado.value = 'inicial'
  }
}
</script>

<template>
  <main class="cliente-registro" aria-labelledby="registro-title">
    <section class="registro-card">
      <RouterLink class="registro-brand" to="/" aria-label="Smart Parking, inicio">
        <span class="registro-brand__mark" aria-hidden="true">SP</span>
        <span>Smart Parking</span>
      </RouterLink>

      <header class="registro-header">
        <p class="registro-eyebrow">Cuenta de cliente</p>
        <h1 id="registro-title">Crea tu cuenta</h1>
        <p>Regístrate para usar los servicios de Smart Parking.</p>
      </header>

      <form
        class="registro-form"
        :class="{ 'registro-form--intento-envio': intentoEnvio }"
        @invalid.capture="intentoEnvio = true"
        @submit.prevent="enviarFormulario"
      >
        <div v-if="mensajeError" class="registro-message registro-message--error" role="alert">
          {{ mensajeError }}
        </div>

        <template v-if="estado !== 'recibido'">
          <div class="registro-grid">
            <div class="registro-field">
              <label for="cliente-nombre">Nombre</label>
              <input
                id="cliente-nombre"
                v-model="formulario.nombre"
                name="nombre"
                type="text"
                autocomplete="given-name"
                maxlength="100"
                required
                :disabled="estado === 'enviando'"
              >
            </div>
            <div class="registro-field">
              <label for="cliente-apellido-paterno">Apellido paterno</label>
              <input
                id="cliente-apellido-paterno"
                v-model="formulario.apellido_paterno"
                name="apellido_paterno"
                type="text"
                autocomplete="family-name"
                maxlength="100"
                required
                :disabled="estado === 'enviando'"
              >
            </div>
          </div>

          <div class="registro-field">
            <label for="cliente-apellido-materno">Apellido materno <span>(opcional)</span></label>
            <input
              id="cliente-apellido-materno"
              v-model="formulario.apellido_materno"
              name="apellido_materno"
              type="text"
              maxlength="100"
              :disabled="estado === 'enviando'"
            >
          </div>

          <div class="registro-field">
            <label for="cliente-correo">Correo electrónico</label>
            <input
              id="cliente-correo"
              v-model="formulario.correo"
              name="correo"
              type="email"
              inputmode="email"
              autocomplete="email"
              maxlength="320"
              required
              :disabled="estado === 'enviando'"
            >
          </div>

          <div class="registro-field">
            <label for="cliente-contrasena">Contraseña</label>
            <input
              id="cliente-contrasena"
              v-model="formulario.contrasena"
              name="contrasena"
              type="password"
              autocomplete="new-password"
              minlength="10"
              maxlength="128"
              pattern="(?=.*[A-Z]).+"
              title="Usa al menos 10 caracteres e incluye una letra mayúscula."
              required
              :disabled="estado === 'enviando'"
            >
            <ul class="registro-requisitos" aria-label="Requisitos de contraseña">
              <li :class="{ 'registro-requisito--cumplido': cumpleLongitudContrasena }">
                <span class="registro-requisito__punto" aria-hidden="true" />
                <span>Al menos 10 caracteres</span>
              </li>
              <li :class="{ 'registro-requisito--cumplido': cumpleMayusculaContrasena }">
                <span class="registro-requisito__punto" aria-hidden="true" />
                <span>Una letra mayúscula</span>
              </li>
            </ul>
          </div>

          <button class="registro-button" type="submit" :disabled="estado === 'enviando'">
            {{ estado === 'enviando' ? 'Enviando…' : 'Crear cuenta' }}
          </button>
        </template>

        <section v-else class="registro-message registro-message--success" role="status">
          <h2>Solicitud recibida</h2>
          <p>
            Si esta dirección puede registrarse, recibimos la solicitud. En esta fase no
            verificamos el correo ni iniciamos sesión; el acceso de cliente estará
            disponible próximamente.
          </p>
        </section>
      </form>

      <footer class="registro-footer">
        <span>¿Ya tienes una cuenta?</span>
        <RouterLink to="/cliente/login">Inicio de sesión de cliente</RouterLink>
      </footer>
    </section>
  </main>
</template>

<style scoped>
.cliente-registro,
.cliente-registro * {
  box-sizing: border-box;
}

.cliente-registro {
  --registro-background: #f4f3f5;
  --registro-surface: #ffffff;
  --registro-foreground: #27232c;
  --registro-muted: #726d78;
  --registro-border: #e3dfe7;
  --registro-accent: #5c3a86;
  --registro-accent-hover: #6c4a97;
  display: grid;
  min-height: 100vh;
  min-height: 100dvh;
  overflow-y: auto;
  padding: clamp(1rem, 4vw, 3rem);
  place-items: center;
  color: var(--registro-foreground);
  background: var(--registro-background);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
}

.registro-card {
  width: min(100%, 38rem);
  padding: clamp(1.5rem, 5vw, 3rem);
  background: var(--registro-surface);
  border: 1px solid var(--registro-border);
  border-radius: 1.25rem;
  box-shadow: 0 1.25rem 3.5rem rgb(32 24 42 / 9%);
}

.registro-brand {
  display: inline-flex;
  align-items: center;
  gap: 0.75rem;
  color: inherit;
  font-size: 0.95rem;
  font-weight: 700;
  text-decoration: none;
}

.registro-brand__mark {
  display: grid;
  width: 2.5rem;
  height: 2.5rem;
  place-items: center;
  color: #fff;
  background: var(--registro-accent);
  border-radius: 0.75rem;
  font-size: 0.75rem;
  letter-spacing: 0.05em;
}

.registro-header {
  margin: 2rem 0 1.5rem;
}

.registro-eyebrow {
  margin: 0 0 0.5rem;
  color: var(--registro-accent);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.11em;
  text-transform: uppercase;
}

.registro-header h1 {
  margin: 0;
  font-size: clamp(1.8rem, 5vw, 2.25rem);
  letter-spacing: -0.04em;
}

.registro-header > p:last-child {
  margin: 0.65rem 0 0;
  color: var(--registro-muted);
  line-height: 1.55;
}

.registro-form,
.registro-grid {
  display: grid;
  gap: 1rem;
}

.registro-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.registro-field {
  display: grid;
  gap: 0.45rem;
}

.registro-field label {
  font-size: 0.85rem;
  font-weight: 650;
}

.registro-field label span {
  color: var(--registro-muted);
  font-weight: 400;
}

.registro-field input {
  width: 100%;
  min-height: 2.9rem;
  padding: 0.7rem 0.8rem;
  color: var(--registro-foreground);
  background: #fdfcfe;
  border: 1px solid var(--registro-border);
  border-radius: 0.6rem;
  font: inherit;
}

.registro-field input:focus-visible,
.registro-button:focus-visible,
.registro-brand:focus-visible,
.registro-footer a:focus-visible {
  outline: 3px solid rgb(92 58 134 / 24%);
  outline-offset: 2px;
}

.registro-form--intento-envio .registro-field input:invalid {
  border-color: #d6336c;
  box-shadow: 0 0 0 3px rgb(214 51 108 / 15%);
}

.registro-form--intento-envio .registro-field input:invalid:focus-visible {
  outline-color: #d6336c;
}

.registro-field input:disabled {
  opacity: 0.65;
}

.registro-requisitos {
  display: grid;
  gap: 0.4rem;
  margin: -0.55rem 0 0;
  padding: 0;
  color: var(--registro-muted);
  font-size: 0.75rem;
  list-style: none;
}

.registro-requisitos li {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.registro-requisito__punto {
  width: 0.55rem;
  height: 0.55rem;
  flex: 0 0 auto;
  background: #a8a3ad;
  border-radius: 50%;
}

.registro-requisito--cumplido .registro-requisito__punto {
  background: #21834a;
  box-shadow: 0 0 0 0.15rem rgb(33 131 74 / 12%);
}

.registro-requisito--cumplido > span:last-child {
  color: #246b40;
}

.registro-button {
  min-height: 3rem;
  margin-top: 0.25rem;
  padding: 0.75rem 1rem;
  color: #fff;
  background: var(--registro-accent);
  border: 0;
  border-radius: 0.625rem;
  cursor: pointer;
  font: inherit;
  font-weight: 700;
}

.registro-button:hover:not(:disabled) {
  background: var(--registro-accent-hover);
}

.registro-button:disabled {
  cursor: wait;
  opacity: 0.72;
}

.registro-message {
  padding: 0.9rem 1rem;
  border-radius: 0.65rem;
  font-size: 0.9rem;
  line-height: 1.55;
}

.registro-message--error {
  color: #8b2430;
  background: #fff3f3;
  border: 1px solid #efc8cc;
}

.registro-message--success {
  color: #244c35;
  background: #f1f8f3;
  border: 1px solid #c9e2d0;
}

.registro-message h2 {
  margin: 0 0 0.5rem;
  font-size: 1.05rem;
}

.registro-message p {
  margin: 0;
}

.registro-footer {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.35rem;
  margin-top: 1.5rem;
  color: var(--registro-muted);
  font-size: 0.85rem;
}

.registro-footer a {
  color: var(--registro-accent);
  font-weight: 650;
}

@media (max-width: 36rem) {
  .registro-grid {
    grid-template-columns: 1fr;
  }
}
</style>
