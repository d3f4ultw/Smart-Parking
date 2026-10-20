<script setup lang="ts">
import { computed, ref } from 'vue'

import { useClientesMembresias } from '~/composables/useClientesMembresias'
import { useSesionCliente } from '~/composables/useSesionCliente'
import { obtenerEstadoErrorSesionCliente } from '~/utils/sesion-cliente'

definePageMeta({
  layout: 'cliente',
  middleware: 'sesion-cliente',
})

const { cambiarContrasenaCliente } = useClientesMembresias()
const { cliente, limpiarSesion } = useSesionCliente()
const contrasenaActual = ref('')
const contrasenaNueva = ref('')
const enviando = ref(false)
const mensaje = ref('')
const tipoMensaje = ref<'exito' | 'error' | ''>('')

const nombreCompleto = computed(() => {
  if (cliente.value === null) return ''
  return [
    cliente.value.nombre,
    cliente.value.apellido_paterno,
    cliente.value.apellido_materno,
  ]
    .filter((parte): parte is string => parte !== null && parte.length > 0)
    .join(' ')
})

useHead({
  title: 'Mi cuenta | Cuenta de cliente',
  meta: [{ name: 'robots', content: 'noindex, nofollow, noarchive' }],
})

async function cambiarContrasena() {
  if (enviando.value) return
  enviando.value = true
  mensaje.value = ''
  tipoMensaje.value = ''

  try {
    await cambiarContrasenaCliente(contrasenaActual.value, contrasenaNueva.value)
    contrasenaActual.value = ''
    contrasenaNueva.value = ''
    tipoMensaje.value = 'exito'
    mensaje.value = 'La contraseña se actualizó correctamente.'
  } catch (error: unknown) {
    const codigo = obtenerEstadoErrorSesionCliente(error)
    if (codigo === 401) {
      limpiarSesion()
      clearNuxtData()
      await navigateTo('/cliente/login', { replace: true })
      return
    }
    tipoMensaje.value = 'error'
    mensaje.value = codigo === 422
      ? 'La contraseña actual no coincide o la nueva no cumple los requisitos.'
      : codigo === 429
        ? 'Se alcanzó el límite de solicitudes. Inténtalo más tarde.'
        : 'No fue posible cambiar la contraseña. Inténtalo nuevamente.'
  } finally {
    enviando.value = false
  }
}
</script>

<template>
  <section class="settings-page" aria-labelledby="settings-title">
    <header class="page-heading">
      <p class="eyebrow">CUENTA DE CLIENTE</p>
      <h1 id="settings-title">Mi cuenta</h1>
      <p>Consulta tu información y administra tu contraseña.</p>
    </header>

    <section class="panel" aria-labelledby="profile-title">
      <div class="panel-heading">
        <h2 id="profile-title">Información de la cuenta</h2>
        <p>Estos datos son de solo lectura.</p>
      </div>
      <dl class="profile-details">
        <div>
          <dt>Nombre</dt>
          <dd>{{ nombreCompleto }}</dd>
        </div>
        <div>
          <dt>Correo electrónico</dt>
          <dd>{{ cliente?.correo }}</dd>
        </div>
      </dl>
    </section>

    <section class="panel" aria-labelledby="password-title">
      <div class="panel-heading">
        <h2 id="password-title">Cambiar contraseña</h2>
        <p>Elige una contraseña que no uses en otros servicios.</p>
      </div>
      <form class="password-form" @submit.prevent="cambiarContrasena">
        <p
          v-if="mensaje"
          class="form-message"
          :class="`form-message--${tipoMensaje}`"
          :role="tipoMensaje === 'error' ? 'alert' : 'status'"
        >
          {{ mensaje }}
        </p>
        <div class="field">
          <label for="contrasena-actual">Contraseña actual</label>
          <input
            id="contrasena-actual"
            v-model="contrasenaActual"
            name="contrasena_actual"
            type="password"
            autocomplete="current-password"
            maxlength="128"
            required
            :disabled="enviando"
          >
        </div>
        <div class="field">
          <label for="contrasena-nueva">Contraseña nueva</label>
          <input
            id="contrasena-nueva"
            v-model="contrasenaNueva"
            name="contrasena_nueva"
            type="password"
            autocomplete="new-password"
            minlength="10"
            maxlength="128"
            pattern="(?=.*[A-Z]).+"
            title="Usa al menos 10 caracteres e incluye una letra mayúscula."
            required
            :disabled="enviando"
          >
          <span class="field-hint">Al menos 10 caracteres y una letra mayúscula.</span>
        </div>
        <button class="primary-button" type="submit" :disabled="enviando">
          {{ enviando ? 'Actualizando…' : 'Actualizar contraseña' }}
        </button>
      </form>
    </section>
  </section>
</template>

<style scoped>
.settings-page { display: grid; gap: 1.2rem; max-width: 58rem; margin: 0 auto; color: #29252f; }
.page-heading { margin-bottom: .2rem; }
.eyebrow { margin: 0 0 .45rem; color: #765b92; font-size: .68rem; font-weight: 800; letter-spacing: .12em; }
h1 { margin: 0; font-size: clamp(1.7rem, 3vw, 2.2rem); letter-spacing: -.045em; }
.page-heading > p:last-child { margin: .45rem 0 0; color: #746f7b; font-size: .86rem; line-height: 1.5; }
.panel { overflow: hidden; border: 1px solid #e8e5eb; border-radius: 1rem; background: #fff; box-shadow: 0 10px 30px rgb(31 20 42 / 4%); }
.panel-heading { padding: 1.15rem 1.35rem; border-bottom: 1px solid #eeeaf1; }
.panel-heading h2 { margin: 0; font-size: 1rem; }
.panel-heading p { margin: .3rem 0 0; color: #746f7b; font-size: .78rem; }
.profile-details { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .9rem; margin: 0; padding: 1.25rem 1.35rem; }
.profile-details > div { min-width: 0; padding: .8rem; background: #fcfbfd; border: 1px solid #eee9f1; border-radius: .7rem; }
.profile-details dt { margin-bottom: .35rem; color: #776f7e; font-size: .7rem; font-weight: 700; }
.profile-details dd { overflow-wrap: anywhere; margin: 0; color: #30283a; font-size: .86rem; font-weight: 750; }
.password-form { display: grid; gap: 1rem; max-width: 34rem; padding: 1.25rem 1.35rem 1.4rem; }
.field { display: grid; gap: .45rem; }
.field label { font-size: .85rem; font-weight: 650; }
.field input { width: 100%; min-height: 2.9rem; padding: .7rem .8rem; color: #29252f; background: #fdfcfe; border: 1px solid #e3dfe7; border-radius: .6rem; font: inherit; }
.field input:focus-visible, .primary-button:focus-visible { outline: 3px solid rgb(92 58 134 / 24%); outline-offset: 2px; }
.field input:disabled { opacity: .65; }
.field-hint { color: #746f7b; font-size: .73rem; }
.primary-button { min-height: 3rem; justify-self: start; padding: .7rem 1rem; color: #fff; background: #674187; border: 0; border-radius: .65rem; cursor: pointer; font: inherit; font-size: .84rem; font-weight: 800; }
.primary-button:hover:not(:disabled) { background: #56336f; }
.primary-button:disabled { cursor: wait; opacity: .7; }
.form-message { margin: 0; padding: .8rem .9rem; border-radius: .65rem; font-size: .83rem; line-height: 1.5; }
.form-message--exito { color: #245f3d; background: #f1f8f3; border: 1px solid #c9e2d0; }
.form-message--error { color: #8b2430; background: #fff3f3; border: 1px solid #efc8cc; }
@media (max-width: 42rem) { .profile-details { grid-template-columns: 1fr; } .primary-button { width: 100%; } }
</style>
