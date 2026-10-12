<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import {
  extraerTokenInvitacionPropietario,
  evaluarRequisitosContrasenaPropietario,
  normalizarCampoNombre,
  recuperarProgresoActivacionPropietario,
  rutaActivacionPropietarioSinToken,
  serializarProgresoActivacionPropietario,
  validarPasoPropietario,
} from '~/utils/activacion-propietario'
import type {
  CredencialesPropietario,
  ErroresPasoPropietario,
  PasoPropietario,
} from '~/utils/activacion-propietario'

useHead({
  title: 'Registro del dueño | Smart Parking',
  meta: [
    { name: 'referrer', content: 'no-referrer' },
    { name: 'robots', content: 'noindex, nofollow' },
  ],
})

const router = useRouter()
const {
  estado,
  tipoCuenta,
  identidadDesafio,
  expiraEn,
  mensajeError,
  canjearEnlace,
  revisarDesafio,
  completar,
} = useActivacionPropietario()
const enlaceNoDisponible = computed(() => estado.value === 'invalido' || estado.value === 'requerido')
const claveBorrador = 'smart-parking.owner-activation-progress.v1'
const credenciales = reactive<CredencialesPropietario>({
  nombre: '',
  apellidoPaterno: '',
  apellidoMaterno: '',
  contrasenaAdmin: '',
  confirmarContrasenaAdmin: '',
  contrasenaLogin: '',
  confirmarContrasenaLogin: '',
})
const contrasenasVisibles = reactive({
  login: false,
  confirmarLogin: false,
  admin: false,
  confirmarAdmin: false,
})
const pasoActual = ref<PasoPropietario>(1)
const pasoIntentado = ref(false)
let progresoRestaurado = false

const totalPasos = computed(() => tipoCuenta.value === 'nueva' ? 3 : 2)
const nombresPasos = computed(() => tipoCuenta.value === 'nueva'
  ? ['Datos personales', 'Contraseña', 'Administración']
  : ['Datos personales', 'Administración'])
const erroresPaso = computed<ErroresPasoPropietario>(() => {
  if (tipoCuenta.value === null) {
    return {}
  }
  return validarPasoPropietario(tipoCuenta.value, pasoActual.value, credenciales)
})

const requisitosContrasenaLogin = computed(() => {
  const requisitos = evaluarRequisitosContrasenaPropietario(credenciales.contrasenaLogin)
  return [
    { nombre: 'Mínimo 10 caracteres', cumple: requisitos.longitudValida && requisitos.caracteresImprimibles },
    { nombre: 'Incluye una letra mayúscula', cumple: requisitos.incluyeMayuscula },
  ]
})

const requisitosContrasenaAdmin = computed(() => {
  const requisitos = evaluarRequisitosContrasenaPropietario(credenciales.contrasenaAdmin)
  return [
    { nombre: 'Mínimo 10 caracteres', cumple: requisitos.longitudValida && requisitos.caracteresImprimibles },
    { nombre: 'Incluye una letra mayúscula', cumple: requisitos.incluyeMayuscula },
    ...(tipoCuenta.value === 'nueva'
      ? [{
          nombre: 'Es distinta de la contraseña de acceso',
          cumple: credenciales.contrasenaAdmin.length > 0
            && credenciales.contrasenaAdmin !== credenciales.contrasenaLogin,
        }]
      : []),
  ]
})

function errorVisible(campo: keyof CredencialesPropietario): string {
  return pasoIntentado.value ? erroresPaso.value[campo] ?? '' : ''
}

function limpiarBorrador() {
  if (!import.meta.client) {
    return
  }
  try {
    window.localStorage.removeItem(claveBorrador)
  } catch {
    // El almacenamiento del navegador es opcional para continuar el registro.
  }
}

function limpiarCampos() {
  credenciales.nombre = ''
  credenciales.apellidoPaterno = ''
  credenciales.apellidoMaterno = ''
  credenciales.contrasenaAdmin = ''
  credenciales.confirmarContrasenaAdmin = ''
  credenciales.contrasenaLogin = ''
  credenciales.confirmarContrasenaLogin = ''
  contrasenasVisibles.login = false
  contrasenasVisibles.confirmarLogin = false
  contrasenasVisibles.admin = false
  contrasenasVisibles.confirmarAdmin = false
}

function guardarProgreso() {
  if (
    !import.meta.client
    || !progresoRestaurado
    || estado.value !== 'formulario'
    || tipoCuenta.value === null
    || expiraEn.value === null
  ) {
    return
  }
  try {
    window.localStorage.setItem(
      claveBorrador,
      serializarProgresoActivacionPropietario(
        tipoCuenta.value,
        expiraEn.value,
        pasoActual.value,
        credenciales,
      ),
    )
  } catch {
    // No se guardan credenciales; el usuario puede continuar sin este borrador.
  }
}

function restaurarProgreso() {
  const tipo = tipoCuenta.value
  const vence = expiraEn.value
  if (!import.meta.client || tipo === null || vence === null) {
    return
  }

  let contenido: string | null = null
  try {
    contenido = window.localStorage.getItem(claveBorrador)
  } catch {
    contenido = null
  }
  const borrador = recuperarProgresoActivacionPropietario(
    contenido,
    tipo,
    vence,
    totalPasos.value as 2 | 3,
  )
  credenciales.nombre = borrador?.nombre ?? identidadDesafio.value.nombre ?? ''
  credenciales.apellidoPaterno = borrador?.apellidoPaterno
    ?? identidadDesafio.value.apellidoPaterno
    ?? ''
  credenciales.apellidoMaterno = borrador?.apellidoMaterno
    ?? identidadDesafio.value.apellidoMaterno
    ?? ''
  pasoActual.value = borrador?.paso ?? 1
  pasoIntentado.value = false
  if (borrador === null) {
    limpiarBorrador()
  }
  progresoRestaurado = true
  guardarProgreso()
}

watch(
  [
    pasoActual,
    () => credenciales.nombre,
    () => credenciales.apellidoPaterno,
    () => credenciales.apellidoMaterno,
  ],
  guardarProgreso,
  { flush: 'sync' },
)

watch(estado, (nuevoEstado) => {
  if (nuevoEstado === 'invalido' || nuevoEstado === 'requerido' || nuevoEstado === 'exito') {
    limpiarBorrador()
    progresoRestaurado = false
    limpiarCampos()
  }
})

async function quitarTokenDeLaUrl() {
  if (window.location.pathname === '/activar-propietario' && window.location.search) {
    await router.replace(rutaActivacionPropietarioSinToken())
  }
}

onMounted(async () => {
  const url = new URL(window.location.href)
  if (url.searchParams.has('token')) {
    const token = extraerTokenInvitacionPropietario(url)
    if (token === null) {
      await quitarTokenDeLaUrl()
      estado.value = 'invalido'
      return
    }

    limpiarBorrador()
    progresoRestaurado = false
    try {
      await canjearEnlace(token)
    } finally {
      await quitarTokenDeLaUrl()
    }
    if (estado.value === 'formulario') {
      restaurarProgreso()
    }
    return
  }

  await revisarDesafio()
  if (estado.value === 'formulario') {
    restaurarProgreso()
  }
})

function validarPasoActual(): boolean {
  pasoIntentado.value = true
  if (Object.keys(erroresPaso.value).length > 0) {
    return false
  }
  return true
}

function avanzar() {
  if (estado.value !== 'formulario' || !validarPasoActual()) {
    return
  }
  if (pasoActual.value < totalPasos.value) {
    pasoActual.value = (pasoActual.value + 1) as PasoPropietario
    pasoIntentado.value = false
    mensajeError.value = ''
    guardarProgreso()
  }
}

function anterior() {
  if (estado.value !== 'formulario' || pasoActual.value <= 1) {
    return
  }
  pasoActual.value = (pasoActual.value - 1) as PasoPropietario
  pasoIntentado.value = false
  mensajeError.value = ''
  guardarProgreso()
}

async function finalizarConfiguracion() {
  const tipo = tipoCuenta.value
  if (
    estado.value !== 'formulario'
    || tipo === null
    || pasoActual.value !== totalPasos.value
    || !validarPasoActual()
  ) {
    return
  }

  const solicitud: {
    nombre: string
    apellido_paterno: string
    apellido_materno: string | null
    contrasena_admin: string
    confirmar_contrasena_admin: string
    contrasena_login?: string
    confirmar_contrasena_login?: string
  } = {
    nombre: normalizarCampoNombre(credenciales.nombre),
    apellido_paterno: normalizarCampoNombre(credenciales.apellidoPaterno),
    apellido_materno: credenciales.apellidoMaterno.trim()
      ? normalizarCampoNombre(credenciales.apellidoMaterno)
      : null,
    contrasena_admin: credenciales.contrasenaAdmin,
    confirmar_contrasena_admin: credenciales.confirmarContrasenaAdmin,
  }
  if (tipo === 'nueva') {
    solicitud.contrasena_login = credenciales.contrasenaLogin
    solicitud.confirmar_contrasena_login = credenciales.confirmarContrasenaLogin
  }

  await completar(solicitud)
}

function continuar() {
  if (pasoActual.value < totalPasos.value) {
    avanzar()
  } else {
    void finalizarConfiguracion()
  }
}
</script>

<template>
  <main class="owner-page">
    <section
      class="owner-card"
      :class="{
        'owner-card--link-unavailable': enlaceNoDisponible,
        'owner-card--success': estado === 'exito',
      }"
      :aria-labelledby="enlaceNoDisponible ? 'link-unavailable-title' : 'owner-title'"
    >
      <template v-if="enlaceNoDisponible">
        <div class="link-unavailable-state" role="alert">
          <h1 id="link-unavailable-title">Enlace no disponible</h1>
          <p>El enlace venció o ya se usó. Pide otro en Gestión del dueño y ábrelo para continuar.</p>
        </div>
      </template>
      <template v-else>
        <p class="eyebrow">Smart Parking</p>
        <h1 id="owner-title">{{ estado === 'exito' ? 'Dueño establecido' : 'Establecer dueño' }}</h1>

        <div v-if="estado === 'verificando' || estado === 'intercambiando'" class="state" role="status">
          <p>Verificando el enlace…</p>
        </div>
        <div v-else-if="estado === 'error'" class="state error" role="alert">
          <p>No fue posible verificar el enlace. Intenta abrirlo nuevamente desde el correo.</p>
        </div>
        <div v-else-if="estado === 'exito'" class="state success" role="status">
          <p>Tu cuenta está lista.</p>
          <NuxtLink class="button" to="/login">Iniciar sesión</NuxtLink>
        </div>

        <form v-else class="owner-form" novalidate @submit.prevent="continuar">
          <p v-if="tipoCuenta === 'nueva'" class="form-intro">
            Completa tus datos.
          </p>
          <p v-else class="form-intro">
            Revisa tus datos.
          </p>

          <div class="step-heading">
            <span>Paso {{ pasoActual }} de {{ totalPasos }}</span>
          </div>
          <ol class="step-progress" aria-label="Progreso de configuración">
            <li
              v-for="(nombrePaso, indice) in nombresPasos"
              :key="nombrePaso"
              :class="{
                'is-current': pasoActual === indice + 1,
                'is-complete': pasoActual > indice + 1,
              }"
              :aria-current="pasoActual === indice + 1 ? 'step' : undefined"
            >
              <span class="step-number" aria-hidden="true">{{ pasoActual > indice + 1 ? '✓' : indice + 1 }}</span>
              <span>{{ nombrePaso }}</span>
            </li>
          </ol>

          <div v-if="mensajeError" class="state error" role="alert">
            {{ mensajeError }}
          </div>

          <section v-if="pasoActual === 1" class="step-content" aria-labelledby="personal-heading">
            <h2 id="personal-heading">Datos personales</h2>
            <div class="personal-grid">
              <div class="field-group field-group--wide">
                <label for="owner-nombre">Nombre(s)</label>
                <input
                  id="owner-nombre"
                  v-model="credenciales.nombre"
                  type="text"
                  name="nombre"
                  autocomplete="given-name"
                  maxlength="100"
                  :aria-invalid="Boolean(errorVisible('nombre'))"
                  :aria-describedby="errorVisible('nombre') ? 'owner-nombre-error' : undefined"
                  required
                >
                <p v-if="errorVisible('nombre')" id="owner-nombre-error" class="field-error" role="alert">
                  {{ errorVisible('nombre') }}
                </p>
              </div>
              <div class="field-group">
                <label for="owner-apellido-paterno">Apellido paterno</label>
                <input
                  id="owner-apellido-paterno"
                  v-model="credenciales.apellidoPaterno"
                  type="text"
                  name="apellido_paterno"
                  autocomplete="family-name"
                  maxlength="100"
                  :aria-invalid="Boolean(errorVisible('apellidoPaterno'))"
                  :aria-describedby="errorVisible('apellidoPaterno') ? 'owner-apellido-paterno-error' : undefined"
                  required
                >
                <p v-if="errorVisible('apellidoPaterno')" id="owner-apellido-paterno-error" class="field-error" role="alert">
                  {{ errorVisible('apellidoPaterno') }}
                </p>
              </div>
              <div class="field-group">
                <label for="owner-apellido-materno">Apellido materno (opcional)</label>
                <input
                  id="owner-apellido-materno"
                  v-model="credenciales.apellidoMaterno"
                  type="text"
                  name="apellido_materno"
                  maxlength="100"
                  :aria-invalid="Boolean(errorVisible('apellidoMaterno'))"
                  :aria-describedby="errorVisible('apellidoMaterno') ? 'owner-apellido-materno-error' : undefined"
                >
                <p v-if="errorVisible('apellidoMaterno')" id="owner-apellido-materno-error" class="field-error" role="alert">
                  {{ errorVisible('apellidoMaterno') }}
                </p>
              </div>
            </div>
          </section>

          <section
            v-else-if="tipoCuenta === 'nueva' && pasoActual === 2"
            class="step-content"
            aria-labelledby="login-heading"
          >
            <h2 id="login-heading" class="visually-hidden">Contraseña</h2>
            <div class="field-group">
              <label for="owner-login-password">Contraseña</label>
              <div class="password-control">
                <input
                  id="owner-login-password"
                  v-model="credenciales.contrasenaLogin"
                  :type="contrasenasVisibles.login ? 'text' : 'password'"
                  autocomplete="new-password"
                  minlength="10"
                  maxlength="128"
                  :aria-invalid="Boolean(errorVisible('contrasenaLogin'))"
                  aria-describedby="owner-login-password-hint"
                  required
                >
                <button
                  class="password-toggle"
                  type="button"
                  :aria-label="contrasenasVisibles.login ? 'Ocultar contraseña' : 'Mostrar contraseña'"
                  :aria-pressed="contrasenasVisibles.login"
                  aria-controls="owner-login-password"
                  @click="contrasenasVisibles.login = !contrasenasVisibles.login"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" />
                    <circle v-if="!contrasenasVisibles.login" cx="12" cy="12" r="3" />
                    <path v-else d="m3 3 18 18" />
                  </svg>
                </button>
              </div>
              <p v-if="errorVisible('contrasenaLogin')" class="field-error" role="alert">
                {{ errorVisible('contrasenaLogin') }}
              </p>
              <ul id="owner-login-password-hint" class="password-requirements" role="list">
                <li v-for="requisito in requisitosContrasenaLogin" :key="requisito.nombre" :class="{ 'is-met': requisito.cumple }">
                  <span class="requirement-mark" aria-hidden="true">{{ requisito.cumple ? '✓' : '•' }}</span>
                  <span>{{ requisito.nombre }}</span>
                  <span class="visually-hidden">{{ requisito.cumple ? 'Cumple' : 'Pendiente' }}</span>
                </li>
              </ul>
            </div>
            <div class="field-group">
              <label for="owner-login-confirm">Confirmar contraseña</label>
              <div class="password-control">
                <input
                  id="owner-login-confirm"
                  v-model="credenciales.confirmarContrasenaLogin"
                  :type="contrasenasVisibles.confirmarLogin ? 'text' : 'password'"
                  autocomplete="new-password"
                  minlength="10"
                  maxlength="128"
                  :aria-invalid="Boolean(errorVisible('confirmarContrasenaLogin'))"
                  aria-describedby="owner-login-confirm-hint"
                  required
                >
                <button
                  class="password-toggle"
                  type="button"
                  :aria-label="contrasenasVisibles.confirmarLogin ? 'Ocultar contraseña' : 'Mostrar contraseña'"
                  :aria-pressed="contrasenasVisibles.confirmarLogin"
                  aria-controls="owner-login-confirm"
                  @click="contrasenasVisibles.confirmarLogin = !contrasenasVisibles.confirmarLogin"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" />
                    <circle v-if="!contrasenasVisibles.confirmarLogin" cx="12" cy="12" r="3" />
                    <path v-else d="m3 3 18 18" />
                  </svg>
                </button>
              </div>
              <ul id="owner-login-confirm-hint" class="password-requirements" role="list">
                <li :class="{ 'is-met': credenciales.contrasenaLogin.length > 0 && credenciales.contrasenaLogin === credenciales.confirmarContrasenaLogin }">
                  <span class="requirement-mark" aria-hidden="true">{{ credenciales.contrasenaLogin.length > 0 && credenciales.contrasenaLogin === credenciales.confirmarContrasenaLogin ? '✓' : '•' }}</span>
                  <span>La contraseña coincide</span>
                </li>
              </ul>
              <p v-if="errorVisible('confirmarContrasenaLogin')" class="field-error" role="alert">
                {{ errorVisible('confirmarContrasenaLogin') }}
              </p>
            </div>
          </section>

          <section
            v-else
            class="step-content"
            aria-labelledby="admin-heading"
          >
            <h2 id="admin-heading" class="visually-hidden">Contraseña administrativa</h2>
            <div class="field-group">
              <label for="owner-admin-password">Contraseña administrativa</label>
              <div class="password-control">
                <input
                  id="owner-admin-password"
                  v-model="credenciales.contrasenaAdmin"
                  :type="contrasenasVisibles.admin ? 'text' : 'password'"
                  autocomplete="new-password"
                  minlength="10"
                  maxlength="128"
                  :aria-invalid="Boolean(errorVisible('contrasenaAdmin'))"
                  aria-describedby="owner-admin-password-hint"
                  required
                >
                <button
                  class="password-toggle"
                  type="button"
                  :aria-label="contrasenasVisibles.admin ? 'Ocultar contraseña' : 'Mostrar contraseña'"
                  :aria-pressed="contrasenasVisibles.admin"
                  aria-controls="owner-admin-password"
                  @click="contrasenasVisibles.admin = !contrasenasVisibles.admin"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" />
                    <circle v-if="!contrasenasVisibles.admin" cx="12" cy="12" r="3" />
                    <path v-else d="m3 3 18 18" />
                  </svg>
                </button>
              </div>
              <p v-if="errorVisible('contrasenaAdmin')" class="field-error" role="alert">
                {{ errorVisible('contrasenaAdmin') }}
              </p>
              <ul id="owner-admin-password-hint" class="password-requirements" role="list">
                <li v-for="requisito in requisitosContrasenaAdmin" :key="requisito.nombre" :class="{ 'is-met': requisito.cumple }">
                  <span class="requirement-mark" aria-hidden="true">{{ requisito.cumple ? '✓' : '•' }}</span>
                  <span>{{ requisito.nombre }}</span>
                  <span class="visually-hidden">{{ requisito.cumple ? 'Cumple' : 'Pendiente' }}</span>
                </li>
              </ul>
            </div>
            <div class="field-group">
              <label for="owner-admin-confirm">Confirmar contraseña administrativa</label>
              <div class="password-control">
                <input
                  id="owner-admin-confirm"
                  v-model="credenciales.confirmarContrasenaAdmin"
                  :type="contrasenasVisibles.confirmarAdmin ? 'text' : 'password'"
                  autocomplete="new-password"
                  minlength="10"
                  maxlength="128"
                  :aria-invalid="Boolean(errorVisible('confirmarContrasenaAdmin'))"
                  aria-describedby="owner-admin-confirm-hint"
                  required
                >
                <button
                  class="password-toggle"
                  type="button"
                  :aria-label="contrasenasVisibles.confirmarAdmin ? 'Ocultar contraseña' : 'Mostrar contraseña'"
                  :aria-pressed="contrasenasVisibles.confirmarAdmin"
                  aria-controls="owner-admin-confirm"
                  @click="contrasenasVisibles.confirmarAdmin = !contrasenasVisibles.confirmarAdmin"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" />
                    <circle v-if="!contrasenasVisibles.confirmarAdmin" cx="12" cy="12" r="3" />
                    <path v-else d="m3 3 18 18" />
                  </svg>
                </button>
              </div>
              <ul id="owner-admin-confirm-hint" class="password-requirements" role="list">
                <li :class="{ 'is-met': credenciales.contrasenaAdmin.length > 0 && credenciales.contrasenaAdmin === credenciales.confirmarContrasenaAdmin }">
                  <span class="requirement-mark" aria-hidden="true">{{ credenciales.contrasenaAdmin.length > 0 && credenciales.contrasenaAdmin === credenciales.confirmarContrasenaAdmin ? '✓' : '•' }}</span>
                  <span>La contraseña coincide</span>
                </li>
              </ul>
              <p v-if="errorVisible('confirmarContrasenaAdmin')" class="field-error" role="alert">
                {{ errorVisible('confirmarContrasenaAdmin') }}
              </p>
            </div>
          </section>

          <div class="wizard-actions">
            <button
              v-if="pasoActual > 1"
              class="button button--secondary"
              type="button"
              :disabled="estado === 'enviando'"
              @click="anterior"
            >
              Anterior
            </button>
            <button class="button" type="submit" :disabled="estado === 'enviando'">
              {{ estado === 'enviando' ? 'Guardando…' : pasoActual < totalPasos ? 'Siguiente' : 'Establecer dueño' }}
            </button>
          </div>
        </form>
      </template>
    </section>
  </main>
</template>

<style scoped>
:global(*) { box-sizing: border-box; }
:global(body) { margin: 0; color: #29252f; background: #f6f5f7; font-family: Manrope, ui-sans-serif, system-ui, sans-serif; }
.owner-page { display: grid; min-height: 100vh; padding: 1rem; place-items: center; }
.owner-card { width: min(100%, 42rem); padding: clamp(1.35rem, 4vw, 2.75rem); background: #fff; border: 1px solid #e8e5eb; border-radius: 1.1rem; box-shadow: 0 1.25rem 3rem rgb(29 23 37 / 10%); }
.owner-card--link-unavailable { width: min(100%, 27rem); padding: 1.25rem 1.5rem; box-shadow: none; }
.owner-card--success { width: min(100%, 30rem); padding: 1.5rem; box-shadow: none; }
.owner-card--success h1 { margin-bottom: .75rem; font-size: clamp(1.5rem, 4vw, 1.9rem); }
.link-unavailable-state h1 { margin: 0 0 .6rem; font-size: 1.2rem; }
.link-unavailable-state p { margin: 0; color: #675d70; font-size: .92rem; line-height: 1.55; }
.eyebrow { margin: 0 0 .45rem; color: #5c3a86; font-size: .8rem; font-weight: 750; letter-spacing: .12em; text-transform: uppercase; }
h1 { margin: 0 0 1.1rem; font-size: clamp(1.7rem, 5vw, 2.25rem); }
.owner-form, .field-group { display: grid; gap: .85rem; }
.form-intro { margin: 0; color: #675d70; line-height: 1.5; }
.step-heading { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: .45rem; color: #493d54; font-weight: 700; }
.step-heading span:first-child { color: #675d70; font-size: .84rem; font-weight: 600; }
.step-progress { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 0; padding: 0; gap: .45rem; list-style: none; }
.step-progress li { display: flex; min-width: 0; align-items: center; gap: .45rem; color: #756b7e; font-size: .75rem; line-height: 1.25; }
.step-progress li.is-current, .step-progress li.is-complete { color: #4c2d71; font-weight: 700; }
.step-number { display: grid; width: 1.7rem; height: 1.7rem; flex: 0 0 1.7rem; color: #6c6274; background: #efedf1; border-radius: 50%; font-size: .75rem; place-items: center; }
.is-current .step-number, .is-complete .step-number { color: #fff; background: #5c3a86; }
.step-content { display: grid; gap: 1rem; }
.step-content h2 { margin: .35rem 0 0; font-size: 1.08rem; }
.personal-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .9rem; }
.personal-grid > .field-group { align-self: start; }
.field-group { min-width: 0; gap: .4rem; }
.field-group--wide { grid-column: 1 / -1; }
label { color: #493d54; font-size: .93rem; font-weight: 650; }
.password-control { position: relative; }
input { width: 100%; min-height: 2.9rem; padding: .7rem .8rem; color: #29252f; background: #fdfcfe; border: 1px solid #c9c2d0; border-radius: .55rem; font: inherit; }
.password-control input { padding-right: 3.1rem; }
input:focus { border-color: #5c3a86; outline: 3px solid rgb(92 58 134 / 18%); }
input[aria-invalid="true"] { border-color: #ad4435; }
.password-toggle { position: absolute; top: 50%; right: .35rem; display: grid; width: 2.25rem; height: 2.25rem; padding: .45rem; color: #5c3a86; background: transparent; border: 0; border-radius: .4rem; place-items: center; transform: translateY(-50%); cursor: pointer; }
.password-toggle:focus-visible { outline: 3px solid rgb(92 58 134 / 28%); }
.password-toggle svg { width: 1.25rem; height: 1.25rem; fill: none; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.8; }
.password-requirements { display: grid; margin: 0; padding: 0; color: #675d70; font-size: .82rem; gap: .2rem; list-style: none; }
.password-requirements li { display: flex; align-items: baseline; gap: .45rem; }
.password-requirements li.is-met { color: #237346; }
.requirement-mark { width: 1rem; flex: 0 0 1rem; font-weight: 800; text-align: center; }
.field-error { margin: 0; color: #9b3024; font-size: .84rem; line-height: 1.35; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; clip-path: inset(50%); }
.wizard-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: .65rem; padding-top: .25rem; }
.button { display: inline-flex; min-height: 2.9rem; align-items: center; justify-content: center; padding: .7rem 1rem; color: #fff; background: #5c3a86; border: 0; border-radius: .55rem; font: inherit; font-weight: 700; text-decoration: none; cursor: pointer; }
.button--secondary { color: #4c2d71; background: #f2eef6; border: 1px solid #ded5e8; }
.button:disabled { cursor: wait; opacity: .65; }
.state { padding: 1rem; background: #f8f7f9; border: 1px solid #e8e5eb; border-radius: .7rem; }
.state p:last-child { margin-bottom: 0; }
.state.error { background: #fff5f3; border-color: #edc2ba; }
.state.success { display: grid; padding: 0; background: transparent; border: 0; gap: .85rem; }
.state.success p { margin: 0; }
@media (max-width: 38rem) {
  .owner-card--link-unavailable { padding: 1.1rem 1.2rem; }
  .step-progress { grid-template-columns: 1fr; gap: .35rem; }
  .step-progress li { font-size: .82rem; }
}
@media (max-width: 30rem) {
  .owner-page { padding: .65rem; }
  .owner-card { padding: 1.1rem; }
  .personal-grid { grid-template-columns: 1fr; }
  .field-group--wide { grid-column: auto; }
  .wizard-actions { justify-content: stretch; }
  .wizard-actions .button { flex: 1 1 100%; }
}
</style>
