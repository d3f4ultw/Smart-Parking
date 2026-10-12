<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { Component } from 'vue'

import ConsultarEstado from '~/components/gestion-propietario/ConsultarEstado.vue'
import DesvincularPropietario from '~/components/gestion-propietario/DesvincularPropietario.vue'
import Navegacion from '~/components/gestion-propietario/Navegacion.vue'
import RegistrarPropietario from '~/components/gestion-propietario/RegistrarPropietario.vue'
import type {
  AccionGestionPropietario,
  EstadoGestionPropietario,
  PanelGestionProps,
} from '~/utils/gestion-propietario'

definePageMeta({ layout: 'gestion-propietario' })

const INTERVALO_ACTUALIZACION_ESTADO_MS = 15_000

type OpcionesCargaEstado = {
  silenciosa?: boolean
  forzar?: boolean
  notificarError?: boolean
}

useHead({
  title: 'Gestión de dueño | Smart Parking',
  meta: [
    { name: 'referrer', content: 'no-referrer' },
    { name: 'robots', content: 'noindex, nofollow, noarchive' },
  ],
})

type EstadoSesion = { activa: boolean }
const sesionActiva = useState<boolean>('gestion-propietario:activa', () => false)
const solicitud = useRequestFetch()
const { data: sesionSSR } = await useAsyncData<EstadoSesion>(
  'gestion-propietario:bootstrap',
  async () => {
    try {
      return await solicitud<EstadoSesion>('/api/gestion-propietario/sesion', {
        retry: 0,
      })
    } catch {
      return { activa: false }
    }
  },
  { default: () => ({ activa: false }) },
)
sesionActiva.value = sesionSSR.value?.activa === true

const paneles: Record<AccionGestionPropietario, Component> = {
  registrar: RegistrarPropietario,
  desvincular: DesvincularPropietario,
  estado: ConsultarEstado,
}
const accionSeleccionada = ref<AccionGestionPropietario>('registrar')
const panelActual = computed(() => paneles[accionSeleccionada.value])
const ticketPendiente = ref('')
const codigoApareamiento = ref('')
const estado = ref<EstadoGestionPropietario | null>(null)
const consultadoEn = ref(0)
const cargando = ref(false)
const enviando = ref(false)
const reenviandoId = ref<number | null>(null)
const { mostrarToast } = useAdminToasts()
let cargaEstadoEnCurso: Promise<void> | null = null
let temporizadorActualizacion: ReturnType<typeof setTimeout> | undefined
let actualizacionAutomaticaEnCurso = false
let paginaMontada = false

function limpiarFragmento() {
  window.history.replaceState(
    window.history.state,
    '',
    window.location.pathname + window.location.search,
  )
}

function leerTicketFragmento() {
  const ticket = window.location.hash.slice(1)
  if (/^[A-Za-z0-9_-]{40,64}$/.test(ticket)) {
    ticketPendiente.value = ticket
  } else if (window.location.hash.length > 0) {
    mostrarToast('El enlace de gestión no tiene un formato válido.', 'error')
  }
}

async function cargarEstado(opciones: OpcionesCargaEstado = {}): Promise<void> {
  if (!sesionActiva.value) {
    return
  }

  if (cargaEstadoEnCurso !== null) {
    await cargaEstadoEnCurso
    if (opciones.forzar && sesionActiva.value) {
      return cargarEstado({ ...opciones, forzar: false })
    }
    return
  }

  const silenciosa = opciones.silenciosa === true
  const notificarError = opciones.notificarError ?? !silenciosa
  if (!silenciosa) {
    cargando.value = true
  }

  const solicitudEstado = (async () => {
    try {
      estado.value = await $fetch<EstadoGestionPropietario>(
        '/api/gestion-propietario/estado',
        { retry: 0 },
      )
      consultadoEn.value = Date.now()
    } catch (error: unknown) {
      const respuesta = error as { status?: number; statusCode?: number }
      if (respuesta.status === 401 || respuesta.statusCode === 401) {
        sesionActiva.value = false
        estado.value = null
      } else if (notificarError) {
        mostrarToast('No se pudo consultar el estado guardado.', 'error')
      }
    } finally {
      if (!silenciosa) {
        cargando.value = false
      }
    }
  })()

  cargaEstadoEnCurso = solicitudEstado
  try {
    await solicitudEstado
  } finally {
    if (cargaEstadoEnCurso === solicitudEstado) {
      cargaEstadoEnCurso = null
    }
  }
}

function programarActualizacionAutomatica() {
  if (temporizadorActualizacion !== undefined) {
    clearTimeout(temporizadorActualizacion)
    temporizadorActualizacion = undefined
  }
  if (!paginaMontada || !sesionActiva.value) {
    return
  }
  temporizadorActualizacion = setTimeout(() => {
    void actualizarEstadoAutomaticamente()
  }, INTERVALO_ACTUALIZACION_ESTADO_MS)
}

async function actualizarEstadoAutomaticamente() {
  if (!paginaMontada || !sesionActiva.value) {
    return
  }
  if (
    document.visibilityState !== 'visible'
    || cargando.value
    || enviando.value
    || reenviandoId.value !== null
    || actualizacionAutomaticaEnCurso
  ) {
    programarActualizacionAutomatica()
    return
  }

  actualizacionAutomaticaEnCurso = true
  try {
    await cargarEstado({ silenciosa: true, notificarError: false })
  } finally {
    actualizacionAutomaticaEnCurso = false
    programarActualizacionAutomatica()
  }
}

function actualizarAlVolver() {
  if (document.visibilityState !== 'visible' || !sesionActiva.value) {
    return
  }
  if (temporizadorActualizacion !== undefined) {
    clearTimeout(temporizadorActualizacion)
    temporizadorActualizacion = undefined
  }
  void actualizarEstadoAutomaticamente()
}

async function sincronizarSesion() {
  try {
    const respuesta = await $fetch<EstadoSesion>(
      '/api/gestion-propietario/sesion',
      { retry: 0 },
    )
    sesionActiva.value = respuesta.activa
  } catch {
    sesionActiva.value = false
  }

  if (sesionActiva.value) {
    if (window.location.hash) {
      limpiarFragmento()
    }
    ticketPendiente.value = ''
    codigoApareamiento.value = ''
    await cargarEstado()
    programarActualizacionAutomatica()
    return
  }
  estado.value = null
  leerTicketFragmento()
}

async function reclamarAcceso() {
  if (!ticketPendiente.value || !codigoApareamiento.value.trim()) {
    mostrarToast('Escribe el código que mostró el lanzador.', 'error')
    return
  }

  enviando.value = true
  try {
    await $fetch('/api/gestion-propietario/claim', {
      method: 'POST',
      body: {
        ticket: ticketPendiente.value,
        codigo_apareamiento: codigoApareamiento.value.trim(),
      },
      retry: 0,
    })
    limpiarFragmento()
    ticketPendiente.value = ''
    codigoApareamiento.value = ''
    sesionActiva.value = true
    mostrarToast('Este navegador quedó autorizado para la sesión temporal.')
    await cargarEstado({ forzar: true })
  } catch {
    mostrarToast(
      'No se pudo autorizar el navegador. Revisa el código o genera un enlace nuevo.',
      'error',
    )
  } finally {
    enviando.value = false
  }
}

async function iniciarInscripcion(correo: string) {
  enviando.value = true
  try {
    await $fetch('/api/gestion-propietario/inscripciones', {
      method: 'POST',
      body: { correo },
      retry: 0,
    })
    mostrarToast('Se envió el correo de verificación.')
    await cargarEstado({ forzar: true })
  } catch (error: unknown) {
    const respuesta = error as { status?: number; statusCode?: number }
    const mensajeError = respuesta.status === 409 || respuesta.statusCode === 409
      ? 'No se puede iniciar: revisa si ya hay un proceso vigente o un dueño activo.'
      : respuesta.status === 429 || respuesta.statusCode === 429
        ? 'El reenvío aún está dentro del periodo de espera.'
        : 'No se pudo enviar el correo de verificación.'
    mostrarToast(mensajeError, 'error')
  } finally {
    enviando.value = false
  }
}

async function reenviarInscripcion(id: number) {
  reenviandoId.value = id
  try {
    await $fetch(`/api/gestion-propietario/inscripciones/${id}/reenviar`, {
      method: 'POST',
      retry: 0,
    })
    mostrarToast('Se envió el nuevo correo de verificación.')
    await cargarEstado({ forzar: true })
  } catch (error: unknown) {
    const respuesta = error as { status?: number; statusCode?: number }
    if (respuesta.status === 429 || respuesta.statusCode === 429) {
      await cargarEstado({ forzar: true })
    }
    const mensajeError = respuesta.status === 429 || respuesta.statusCode === 429
      ? 'El reenvío aún está dentro del periodo de espera.'
      : respuesta.status === 409 || respuesta.statusCode === 409
        ? 'El reenvío ya no está disponible para este proceso.'
        : 'No se pudo reenviar el correo de verificación.'
    mostrarToast(mensajeError, 'error')
  } finally {
    reenviandoId.value = null
  }
}

async function iniciarDesvinculacion(contrasenaAdmin: string) {
  if (!sesionActiva.value || estado.value?.owner === null || !estado.value?.owner) {
    return
  }

  enviando.value = true
  try {
    await $fetch('/api/gestion-propietario/desvinculacion', {
      method: 'POST',
      body: { contrasena_admin: contrasenaAdmin },
      retry: 0,
    })
    mostrarToast('Se envió el enlace de confirmación al correo del dueño.')
    await cargarEstado({ forzar: true, silenciosa: true, notificarError: false })
  } catch (error: unknown) {
    const respuesta = error as { status?: number; statusCode?: number }
    const codigo = respuesta.status ?? respuesta.statusCode
    if (codigo === 409 || codigo === 429) {
      await cargarEstado({ forzar: true, silenciosa: true, notificarError: false })
    }
    const mensaje = codigo === 401
      ? 'La contraseña administrativa no es correcta.'
      : codigo === 409
        ? 'No se puede iniciar la desvinculación o ya hay un enlace vigente.'
        : codigo === 429
          ? 'Espera antes de solicitar otro correo de confirmación.'
          : codigo === 503
            ? 'No se pudo enviar el correo de confirmación.'
            : 'No se pudo solicitar la desvinculación.'
    mostrarToast(mensaje, 'error')
  } finally {
    enviando.value = false
  }
}

const propsPanel = computed<PanelGestionProps>(() => ({
  estado: estado.value,
  cargando: cargando.value,
  enviando: enviando.value,
  reenviandoId: reenviandoId.value,
  consultadoEn: consultadoEn.value,
}))

onMounted(() => {
  paginaMontada = true
  window.addEventListener('focus', actualizarAlVolver)
  document.addEventListener('visibilitychange', actualizarAlVolver)
  void sincronizarSesion()
})

onBeforeUnmount(() => {
  paginaMontada = false
  window.removeEventListener('focus', actualizarAlVolver)
  document.removeEventListener('visibilitychange', actualizarAlVolver)
  if (temporizadorActualizacion !== undefined) {
    clearTimeout(temporizadorActualizacion)
  }
})
</script>

<template>
  <main class="owner-management-page">
    <section v-if="!sesionActiva" class="claim-panel" aria-labelledby="claim-title">
      <p class="eyebrow">
        {{ ticketPendiente ? 'Acceso temporal' : 'Acceso restringido' }}
      </p>
      <h1 id="claim-title">
        {{ ticketPendiente ? 'Autorizar navegador' : 'Navegador no autorizado' }}
      </h1>

      <form v-if="ticketPendiente" class="claim-form" @submit.prevent="reclamarAcceso">
        <p class="claim-copy">Ingresa el código del lanzador.</p>
        <label for="pairing-code">Código de acceso</label>
        <input
          id="pairing-code"
          v-model="codigoApareamiento"
          autocomplete="off"
          autocapitalize="characters"
          maxlength="20"
          name="codigo_apareamiento"
          spellcheck="false"
          required
        >
        <button class="primary-button" type="submit" :disabled="enviando">
          {{ enviando ? 'Autorizando…' : 'Autorizar' }}
        </button>
      </form>
      <p v-else class="waiting-copy">
        Abre el enlace en el navegador donde autorizaste la gestión.
      </p>
    </section>

    <section v-else class="authorized-management" aria-label="Gestión de dueño">
      <div class="intro-row">
        <div>
          <p class="eyebrow">Acceso temporal autorizado</p>
          <h1>Gestión de la cuenta del dueño</h1>
        </div>
        <button class="refresh-button" type="button" :disabled="cargando" @click="cargarEstado({ forzar: true })">
          {{ cargando ? 'Actualizando…' : 'Actualizar estado' }}
        </button>
      </div>

      <Navegacion
        :seleccionada="accionSeleccionada"
        @seleccionar="accionSeleccionada = $event"
      />

      <component
        :is="panelActual"
        v-bind="propsPanel"
        @iniciar="iniciarInscripcion"
        @reenviar="reenviarInscripcion"
        @solicitar="iniciarDesvinculacion"
      />
    </section>
  </main>
</template>

<style scoped>
.owner-management-page {
  display: grid;
  gap: 1rem;
}

.authorized-management {
  display: grid;
  gap: 1.5rem;
}

.claim-panel {
  width: min(100%, 32rem);
  margin: clamp(1rem, 8vh, 5rem) auto 2rem;
  padding: clamp(1.25rem, 4vw, 1.5rem);
  background: #ffffff;
  border: 1px solid #e5e0e9;
  border-radius: 0.9rem;
}

.eyebrow {
  margin: 0 0 0.35rem;
  color: #74647f;
  font-size: 0.69rem;
  font-weight: 750;
  letter-spacing: 0.11em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  color: #30263b;
  font-size: clamp(1.45rem, 4vw, 2rem);
  letter-spacing: -0.03em;
}

.claim-panel h1 {
  font-size: clamp(1.35rem, 3.5vw, 1.7rem);
}

.claim-copy,
.waiting-copy {
  margin: 0.75rem 0 0;
  color: #655d6c;
  font-size: 0.92rem;
  line-height: 1.6;
}

.claim-form {
  display: grid;
  gap: 0.65rem;
  margin-top: 1rem;
}

.claim-form .claim-copy {
  margin: 0 0 0.25rem;
}

.claim-form label {
  color: #41364b;
  font-size: 0.84rem;
  font-weight: 700;
}

.claim-form input {
  min-height: 3rem;
  padding: 0.7rem 0.8rem;
  color: #30263b;
  background: #ffffff;
  border: 1px solid #cfc7d7;
  border-radius: 0.65rem;
  font-size: 1rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.claim-form input:focus-visible {
  border-color: #67488b;
  outline: 3px solid rgb(103 72 139 / 18%);
}

.primary-button,
.refresh-button {
  min-height: 2.8rem;
  padding: 0.65rem 1rem;
  border-radius: 0.65rem;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}

.primary-button {
  justify-self: start;
  color: #ffffff;
  background: #523775;
  border: 1px solid #523775;
}

.primary-button:disabled,
.refresh-button:disabled {
  cursor: wait;
  opacity: 0.7;
}

.intro-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.refresh-button {
  color: #51356e;
  background: #ffffff;
  border: 1px solid #9b83b0;
  white-space: nowrap;
}

@media (max-width: 43rem) {
  .intro-row {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
