<script setup lang="ts">
import { ref } from 'vue'

import { useSesionCliente } from '~/composables/useSesionCliente'
import {
  mapearErrorLoginCliente,
  obtenerEstadoErrorSesionCliente,
} from '~/utils/sesion-cliente'

definePageMeta({ layout: false })

const { iniciarSesion } = useSesionCliente()
const correo = ref('')
const contrasena = ref('')
const enviando = ref(false)
const mensajeError = ref('')

useHead({
  title: 'Acceso de cliente | Smart Parking',
  meta: [
    { name: 'description', content: 'Inicia sesión en tu cuenta de cliente de Smart Parking.' },
    { name: 'robots', content: 'noindex, nofollow, noarchive' },
  ],
})

async function enviarFormulario() {
  if (enviando.value) {
    return
  }

  enviando.value = true
  mensajeError.value = ''
  try {
    const sesionValida = await iniciarSesion(correo.value, contrasena.value)
    if (!sesionValida) {
      mensajeError.value = 'No fue posible confirmar la sesión. Inténtalo nuevamente.'
      return
    }
    contrasena.value = ''
    await navigateTo('/cliente', { replace: true })
  } catch (error: unknown) {
    mensajeError.value = mapearErrorLoginCliente(obtenerEstadoErrorSesionCliente(error))
  } finally {
    enviando.value = false
  }
}
</script>

<template>
  <main class="cliente-login" aria-labelledby="cliente-login-title">
    <section class="cliente-login__card">
      <NuxtLink class="cliente-login__brand" to="/" aria-label="Smart Parking, inicio">
        <span class="cliente-login__mark" aria-hidden="true">SP</span>
        <span>Smart Parking</span>
      </NuxtLink>
      <header class="cliente-login__header">
        <p class="cliente-login__eyebrow">Cuenta de cliente</p>
        <h1 id="cliente-login-title">Inicia sesión</h1>
        <p>Consulta tu membresía y administra tu cuenta.</p>
      </header>

      <form class="cliente-login__form" @submit.prevent="enviarFormulario">
        <p v-if="mensajeError" class="cliente-login__error" role="alert">
          {{ mensajeError }}
        </p>
        <div class="cliente-login__field">
          <label for="cliente-correo">Correo electrónico</label>
          <input
            id="cliente-correo"
            v-model="correo"
            name="correo"
            type="email"
            inputmode="email"
            autocomplete="username"
            maxlength="320"
            required
            :disabled="enviando"
          >
        </div>
        <div class="cliente-login__field">
          <label for="cliente-contrasena">Contraseña</label>
          <input
            id="cliente-contrasena"
            v-model="contrasena"
            name="contrasena"
            type="password"
            autocomplete="current-password"
            maxlength="128"
            required
            :disabled="enviando"
          >
        </div>
        <button class="cliente-login__submit" type="submit" :disabled="enviando">
          {{ enviando ? 'Verificando…' : 'Iniciar sesión' }}
        </button>
      </form>

      <footer class="cliente-login__footer">
        <span>¿Aún no tienes cuenta?</span>
        <NuxtLink to="/cliente/registro">Crear cuenta</NuxtLink>
      </footer>
    </section>
  </main>
</template>

<style scoped>
.cliente-login,
.cliente-login * { box-sizing: border-box; }
.cliente-login {
  --login-background: #f4f3f5;
  --login-surface: #fff;
  --login-foreground: #27232c;
  --login-muted: #726d78;
  --login-border: #e3dfe7;
  --login-accent: #5c3a86;
  display: grid;
  min-height: 100vh;
  min-height: 100dvh;
  overflow-y: auto;
  padding: clamp(1rem, 4vw, 3rem);
  place-items: center;
  color: var(--login-foreground);
  background: var(--login-background);
  font-family: Manrope, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.cliente-login__card { width: min(100%, 34rem); padding: clamp(1.5rem, 5vw, 3rem); background: var(--login-surface); border: 1px solid var(--login-border); border-radius: 1.25rem; box-shadow: 0 1.25rem 3.5rem rgb(32 24 42 / 9%); }
.cliente-login__brand { display: inline-flex; align-items: center; gap: .75rem; color: inherit; font-size: .95rem; font-weight: 700; text-decoration: none; }
.cliente-login__mark { display: grid; width: 2.5rem; height: 2.5rem; place-items: center; color: #fff; background: var(--login-accent); border-radius: .75rem; font-size: .75rem; font-weight: 800; letter-spacing: .05em; }
.cliente-login__header { margin: 2rem 0 1.5rem; }
.cliente-login__eyebrow { margin: 0 0 .5rem; color: var(--login-accent); font-size: .75rem; font-weight: 700; letter-spacing: .11em; text-transform: uppercase; }
.cliente-login__header h1 { margin: 0; font-size: clamp(1.8rem, 5vw, 2.25rem); letter-spacing: -.04em; }
.cliente-login__header > p:last-child { margin: .65rem 0 0; color: var(--login-muted); line-height: 1.55; }
.cliente-login__form { display: grid; gap: 1rem; }
.cliente-login__field { display: grid; gap: .45rem; }
.cliente-login__field label { font-size: .85rem; font-weight: 650; }
.cliente-login__field input { width: 100%; min-height: 2.9rem; padding: .7rem .8rem; color: var(--login-foreground); background: #fdfcfe; border: 1px solid var(--login-border); border-radius: .6rem; font: inherit; }
.cliente-login__submit { min-height: 3rem; margin-top: .25rem; padding: .75rem 1rem; color: #fff; background: var(--login-accent); border: 0; border-radius: .625rem; cursor: pointer; font: inherit; font-weight: 700; }
.cliente-login__submit:hover:not(:disabled) { background: #4d2f74; }
.cliente-login__submit:disabled { cursor: wait; opacity: .72; }
.cliente-login__error { margin: 0; padding: .85rem 1rem; color: #8b2430; background: #fff3f3; border: 1px solid #efc8cc; border-radius: .65rem; font-size: .85rem; line-height: 1.5; }
.cliente-login__footer { display: flex; flex-wrap: wrap; justify-content: center; gap: .35rem; margin-top: 1.5rem; color: var(--login-muted); font-size: .85rem; }
.cliente-login__footer a { color: var(--login-accent); font-weight: 650; }
.cliente-login__field input:focus-visible, .cliente-login__submit:focus-visible, .cliente-login__brand:focus-visible, .cliente-login__footer a:focus-visible { outline: 3px solid rgb(92 58 134 / 24%); outline-offset: 3px; }
</style>
