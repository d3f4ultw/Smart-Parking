<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'

import { obtenerEstadoErrorOperador } from '~/utils/operadores'
import {
  etiquetaEstadoCuentaOperador,
  obtenerPaginaSolicitadaOperadores,
  mapearErrorGestionOperador,
  puedeReenviarInvitacionOperador,
  puedeRegenerarContrasenaOperador,
  type Operador,
} from '~/utils/gestion-operadores'

definePageMeta({
  middleware: 'sesion-admin',
})

const CLAVE_LISTA_OPERADORES = 'admin-operadores-lista'
const route = useRoute()
const operadorId = String(route.params.id)
const paginaLista = obtenerPaginaSolicitadaOperadores(route.query.pagina)
const rutaListaOperadores = computed(() => paginaLista > 1
  ? { path: '/admin/operadores', query: { pagina: String(paginaLista) } }
  : '/admin/operadores')
const claveDetalle = `admin-operador-${operadorId}`
const {
  desactivarOperador,
  obtenerOperador,
  reactivarOperador,
  reenviarInvitacionOperador,
  regenerarContrasenaOperador,
} = useOperadores()
const { limpiarSesion } = useSesion()
const mensajeError = ref('')
const mensajeEstado = ref('')
const procesando = ref(false)

const { data: operador, error, pending, refresh } = await useAsyncData<Operador | null>(
  claveDetalle,
  () => obtenerOperador(operadorId),
  {
    default: () => null,
    dedupe: 'defer',
  },
)

async function atenderError(errorActual: unknown) {
  const codigo = obtenerEstadoErrorOperador(errorActual)
  if (codigo === 401) {
    limpiarSesion()
    clearNuxtData(CLAVE_LISTA_OPERADORES)
    clearNuxtData(claveDetalle)
    await navigateTo('/login', { replace: true })
    return
  }
  mensajeError.value = mapearErrorGestionOperador(codigo)
}

if (error.value) {
  await atenderError(error.value)
}

async function guardarEstado(accion: 'desactivar' | 'reactivar') {
  if (procesando.value || operador.value === null) {
    return
  }

  const confirmacion = accion === 'desactivar'
    ? '¿Desactivar esta cuenta? Sus sesiones actuales dejarán de funcionar.'
    : '¿Reactivar esta cuenta? Una cuenta pendiente necesitará una invitación nueva.'
  if (!window.confirm(confirmacion)) {
    return
  }

  procesando.value = true
  mensajeError.value = ''
  mensajeEstado.value = ''
  try {
    if (accion === 'desactivar') {
      await desactivarOperador(operador.value.id)
      mensajeEstado.value = 'Operador desactivado.'
    } else {
      await reactivarOperador(operador.value.id)
      mensajeEstado.value = 'Operador reactivado.'
    }
    clearNuxtData(CLAVE_LISTA_OPERADORES)
    await refresh()
  } catch (errorActual: unknown) {
    await atenderError(errorActual)
    if (obtenerEstadoErrorOperador(errorActual) === 409) {
      await refresh()
    }
  } finally {
    procesando.value = false
  }
}

async function regenerarContrasena() {
  if (
    procesando.value
    || operador.value === null
    || !puedeRegenerarContrasenaOperador(operador.value)
  ) {
    return
  }
  if (!window.confirm(
    '¿Regenerar la contraseña de este operador? Si el envío se completa, la contraseña anterior dejará de funcionar y sus sesiones activas se cerrarán. La contraseña nueva se enviará al correo registrado y no se mostrará en este panel. Si falla la entrega, se conserva la contraseña actual.',
  )) {
    return
  }

  procesando.value = true
  mensajeError.value = ''
  mensajeEstado.value = ''
  try {
    await regenerarContrasenaOperador(operador.value.id)
    mensajeEstado.value = 'La contraseña nueva se envió al correo registrado.'
  } catch (errorActual: unknown) {
    await atenderError(errorActual)
  } finally {
    procesando.value = false
  }
}

async function reenviarInvitacion() {
  if (
    procesando.value
    || operador.value === null
    || !puedeReenviarInvitacionOperador(operador.value)
  ) {
    return
  }

  procesando.value = true
  mensajeError.value = ''
  mensajeEstado.value = ''
  try {
    await reenviarInvitacionOperador(operador.value.id)
    mensajeEstado.value = 'La invitación se envió al correo registrado.'
  } catch (errorActual: unknown) {
    if (obtenerEstadoErrorOperador(errorActual) === 503) {
      mensajeError.value = 'No fue posible enviar el correo. La invitación anterior sigue vigente.'
    } else {
      await atenderError(errorActual)
    }
  } finally {
    procesando.value = false
  }
}

async function actualizarDetalle() {
  mensajeError.value = ''
  await refresh()
  if (error.value) {
    await atenderError(error.value)
  }
}

onUnmounted(() => clearNuxtData(claveDetalle))
</script>

<template>
  <main class="operator-page">
    <section class="operator-card" aria-labelledby="operator-title">
      <header class="page-header">
        <div>
          <p class="eyebrow">Smart Parking · Administración</p>
          <h1 id="operator-title">Detalle del operador</h1>
        </div>
        <NuxtLink class="button secondary" :to="rutaListaOperadores">
          Volver a operadores
        </NuxtLink>
      </header>

      <p v-if="pending" role="status">Cargando operador…</p>
      <div v-else-if="operador" class="operator-details">
        <dl>
          <div>
            <dt>Nombre</dt>
            <dd>{{ [operador.nombre, operador.apellido_paterno, operador.apellido_materno].filter(Boolean).join(' ') }}</dd>
          </div>
          <div>
            <dt>Correo</dt>
            <dd>{{ operador.correo }}</dd>
          </div>
          <div>
            <dt>Estado de cuenta</dt>
            <dd>
              <span class="state" :class="operador.estado_cuenta">
                {{ etiquetaEstadoCuentaOperador(operador.estado_cuenta) }}
              </span>
            </dd>
          </div>
        </dl>

        <div v-if="mensajeEstado" class="notice success" role="status">
          {{ mensajeEstado }}
        </div>
        <div v-if="mensajeError" class="notice error" role="alert">
          {{ mensajeError }}
        </div>

        <div class="actions">
          <button
            v-if="puedeReenviarInvitacionOperador(operador)"
            class="button secondary"
            type="button"
            :disabled="procesando"
            @click="reenviarInvitacion"
          >
            {{ procesando ? 'Procesando…' : 'Reenviar invitación' }}
          </button>
          <button
            class="button primary"
            type="button"
            :disabled="procesando"
            @click="guardarEstado(operador.esta_activo ? 'desactivar' : 'reactivar')"
          >
            {{ operador.esta_activo ? 'Desactivar operador' : 'Reactivar operador' }}
          </button>
          <button
            v-if="puedeRegenerarContrasenaOperador(operador)"
            class="button secondary"
            type="button"
            :disabled="procesando"
            @click="regenerarContrasena"
          >
            {{ procesando ? 'Procesando…' : 'Regenerar contraseña' }}
          </button>
          <button class="button secondary" type="button" :disabled="procesando" @click="actualizarDetalle">
            Actualizar detalle
          </button>
        </div>
      </div>
      <div v-else class="notice error" role="alert">
        {{ mensajeError || 'No se encontró el operador solicitado.' }}
      </div>
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
  min-height: 100vh;
  padding: clamp(0.75rem, 3vw, 2rem);
  place-items: center;
}

.operator-card {
  width: min(100%, 48rem);
  padding: clamp(1.25rem, 4vw, 2.5rem);
  background: #ffffff;
  border: 1px solid #d6e5ea;
  border-radius: 1.25rem;
  box-shadow: 0 1.5rem 4rem rgb(24 50 75 / 10%);
}

.page-header,
.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.page-header {
  margin-bottom: 1.5rem;
}

.eyebrow {
  margin: 0 0 0.45rem;
  color: #0d7286;
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  color: #102a43;
  font-size: clamp(1.8rem, 5vw, 2.5rem);
}

.operator-details dl {
  display: grid;
  gap: 0.75rem;
  margin: 0 0 1.5rem;
}

.operator-details dl div {
  padding: 1rem;
  background: #f7fafb;
  border: 1px solid #d6e5ea;
  border-radius: 0.75rem;
}

dt {
  color: #5c7487;
  font-size: 0.85rem;
  font-weight: 700;
}

dd {
  margin: 0.3rem 0 0;
  color: #102a43;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.actions {
  justify-content: flex-start;
  margin-top: 1.25rem;
}

.button {
  display: inline-flex;
  min-height: 2.75rem;
  align-items: center;
  justify-content: center;
  padding: 0.65rem 0.95rem;
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

.secondary:hover:not(:disabled),
.secondary:focus-visible {
  background: #d6e5ea;
}

.state {
  display: inline-block;
  padding: 0.35rem 0.65rem;
  border-radius: 999px;
  font-size: 0.85rem;
  font-weight: 700;
}

.state.acceso_habilitado {
  color: #23613a;
  background: #e5f5e9;
}

.state.inactivo {
  color: #7b3333;
  background: #fff0ed;
}

.state.pendiente_activacion {
  color: #805b16;
  background: #fff4d7;
}

.notice {
  margin: 1rem 0;
  padding: 0.9rem 1rem;
  border: 1px solid #d6e5ea;
  border-radius: 0.7rem;
}

.notice.success {
  color: #23613a;
  background: #eef9f2;
  border-color: #b8dfc3;
}

.notice.error {
  color: #7b3333;
  background: #fff5f3;
  border-color: #edc2ba;
}
</style>
