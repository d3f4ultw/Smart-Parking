<script setup lang="ts">
import { nextTick, onScopeDispose, watch } from 'vue'
import type { Empleado } from '~/types/empleado'
import { ErrorEmpleadoApi, useClienteEmpleados } from '~/utils/empleados-api'
import { generarUuidV4 } from '~/utils/uuid'

type AccionConfirmada = 'PROMOCIONAR' | 'DESACTIVAR'

const abierta = defineModel<boolean>('open', { required: true })
const props = defineProps<{ idTexto: string | null }>()
const emit = defineEmits<{ actualizado: [] }>()
const cliente = useClienteEmpleados()
const csrf = useCsrf()
const sesion = useSesion()
const toast = useToast()
const uiModal = {
  overlay: 'bg-black/55',
  content: 'w-full max-w-lg rounded-2xl border border-[var(--app-border)] bg-white shadow-xl',
  header: 'px-5 py-4 sm:px-6',
  title: 'text-lg font-semibold',
  description: 'text-sm text-[var(--app-muted)]',
  body: 'px-5 pb-5 pt-0 sm:px-6 sm:pb-6',
}
const detalle = ref<Empleado | null>(null)
const etag = ref<string | null>(null)
const correoEdicion = ref('')
const cargando = ref(false)
const ocupado = ref(false)
const error = ref('')
const errorCorreo = ref('')
const accionPendiente = ref<AccionConfirmada | null>(null)
const claveCorreo = ref('')
const clavesAccion = reactive<Record<AccionConfirmada, string>>({
  PROMOCIONAR: '',
  DESACTIVAR: '',
})
let controladorDetalle: AbortController | null = null

const cuentaOperador = computed(() => {
  const estado = detalle.value?.operador?.estado
  if (!estado) return 'Sin cuenta de operador'
  return {
    PENDIENTE: 'Por activar',
    ACTIVA: 'Activa',
    INACTIVA: 'Desactivada',
  }[estado]
})

const claseCuentaOperador = computed(() => {
  const estado = detalle.value?.operador?.estado
  if (estado === 'ACTIVA') return 'estado-cuenta--activa'
  if (estado === 'PENDIENTE') return 'estado-cuenta--pendiente'
  if (estado === 'INACTIVA') return 'estado-cuenta--inactiva'
  return 'estado-cuenta--sin-cuenta'
})

const correoNormalizado = computed(() => correoEdicion.value.trim())
const correoCambio = computed(
  () => detalle.value !== null && correoNormalizado.value !== (detalle.value.correo ?? ''),
)
const correoFormatoValido = computed(() => {
  const correo = correoNormalizado.value
  return correo.length === 0 || (Array.from(correo).length <= 254 && /^\S+@\S+\.\S+$/.test(correo))
})
const mensajeErrorCorreo = computed(
  () =>
    errorCorreo.value ||
    (correoCambio.value && !correoFormatoValido.value ? 'Escribe un correo válido.' : ''),
)
const puedeGuardarCorreo = computed(
  () => !ocupado.value && correoCambio.value && correoFormatoValido.value,
)

const puedePromocionar = computed(
  () =>
    detalle.value?.estado === 'ACTIVO' &&
    detalle.value.correo !== null &&
    (!detalle.value.operador || detalle.value.operador.estado === 'INACTIVA'),
)

const puedeDesactivar = computed(
  () =>
    detalle.value?.estado === 'ACTIVO' &&
    Boolean(detalle.value.operador && detalle.value.operador.estado !== 'INACTIVA'),
)

const etiquetaPromocion = computed(() =>
  detalle.value?.operador?.estado === 'INACTIVA'
    ? 'Reactivar cuenta de operador'
    : 'Crear cuenta de operador',
)

function nombreCompleto(empleado: Empleado) {
  return [empleado.nombres, empleado.primerApellido, empleado.segundoApellido]
    .filter((parte): parte is string => Boolean(parte))
    .join(' ')
}

function mensajeFallo(fallo: unknown) {
  return fallo instanceof ErrorEmpleadoApi
    ? fallo.message
    : 'No pudimos completar el cambio. Revisa el estado antes de volver a intentarlo.'
}

function textoInvitacion(estado: string | null) {
  if (!estado) return ''
  const etiquetas: Record<string, string> = {
    ENVIANDO: 'Enviando',
    ENVIADO: 'Enviado',
    FALLIDO: 'No se pudo enviar',
    DESCONOCIDO: 'No sabemos si se envió',
    DESHABILITADO: 'No se enviará',
  }
  return etiquetas[estado] ?? 'Sin invitación activa'
}

async function manejarFallo(fallo: unknown) {
  if (!(fallo instanceof ErrorEmpleadoApi)) return
  if (fallo.estado === 401) {
    await sesion.limpiar()
    await navigateTo('/panel')
  } else if (fallo.estado === 403 && fallo.codigo === 'CSRF_RECHAZADO') {
    csrf.limpiar()
  }
}

async function cargarDetalle(posicionarCursorAlFinal = false) {
  const idTexto = props.idTexto
  if (!idTexto || !abierta.value) return
  controladorDetalle?.abort()
  const controlador = new AbortController()
  controladorDetalle = controlador
  let detalleCargado = false
  cargando.value = true
  error.value = ''
  errorCorreo.value = ''
  try {
    const respuesta = await cliente.detalle(idTexto, controlador.signal)
    if (controlador.signal.aborted || idTexto !== props.idTexto) return
    detalle.value = respuesta.datos
    etag.value = respuesta.etag
    correoEdicion.value = respuesta.datos.correo ?? ''
    detalleCargado = true
  } catch (fallo) {
    if (controlador.signal.aborted) return
    if (fallo instanceof ErrorEmpleadoApi && fallo.estado === 401) {
      await sesion.limpiar()
      await navigateTo('/panel')
      return
    }
    error.value = mensajeFallo(fallo)
  } finally {
    if (controladorDetalle === controlador) {
      controladorDetalle = null
      cargando.value = false
    }
  }
  if (posicionarCursorAlFinal && detalleCargado) await enfocarCorreoAlFinal()
}

async function enfocarCorreoAlFinal() {
  if (!import.meta.client) return
  await nextTick()
  const campo = document.getElementById('administrar-empleado-correo')
  if (!(campo instanceof HTMLInputElement) || campo.disabled) return
  campo.focus({ preventScroll: true })
  campo.setSelectionRange(campo.value.length, campo.value.length)
}

function limpiarDetalle() {
  controladorDetalle?.abort()
  controladorDetalle = null
  detalle.value = null
  etag.value = null
  correoEdicion.value = ''
  error.value = ''
  errorCorreo.value = ''
  accionPendiente.value = null
  claveCorreo.value = ''
  clavesAccion.PROMOCIONAR = ''
  clavesAccion.DESACTIVAR = ''
  cargando.value = false
}

watch(abierta, (valor) => {
  if (valor) void cargarDetalle(true)
  else limpiarDetalle()
})

watch(
  () => props.idTexto,
  () => {
    if (abierta.value) void cargarDetalle(true)
  },
)

watch(correoEdicion, () => {
  claveCorreo.value = ''
  errorCorreo.value = ''
})

onScopeDispose(() => controladorDetalle?.abort())

async function restaurarFoco(evento: Event) {
  evento.preventDefault()
  await nextTick()
  const idTexto = props.idTexto
  if (idTexto) document.getElementById(`empleado-administrar-${idTexto}`)?.focus()
}

async function guardarCorreo() {
  const empleado = detalle.value
  const revision = etag.value
  if (!empleado || !revision || ocupado.value) return
  error.value = ''
  errorCorreo.value = ''
  const correo = correoNormalizado.value || null
  if (!correoFormatoValido.value) {
    errorCorreo.value = 'Escribe un correo válido.'
    return
  }
  if (correo === empleado.correo) return

  let reenfocarCorreo = false
  ocupado.value = true
  try {
    if (!claveCorreo.value) claveCorreo.value = generarUuidV4()
    const token = await csrf.obtener()
    const respuesta = await cliente.cambiarCorreo(
      empleado.idTexto,
      correo,
      revision,
      claveCorreo.value,
      token,
    )
    claveCorreo.value = ''
    if (empleado.operador?.estado === 'ACTIVA') {
      toast.add({
        title: 'Correo actualizado',
        description: 'La persona deberá iniciar sesión de nuevo.',
        color: 'success',
      })
    } else if (respuesta.estadoInvitacion) {
      toast.add({
        title: 'Correo actualizado',
        description: `Invitación: ${textoInvitacion(respuesta.estadoInvitacion)}.`,
        color: respuesta.estadoInvitacion === 'ENVIADO' ? 'success' : 'warning',
      })
    } else {
      toast.add({ title: 'Correo actualizado', color: 'success' })
    }
    await cargarDetalle()
    reenfocarCorreo = true
    emit('actualizado')
  } catch (fallo) {
    await manejarFallo(fallo)
    errorCorreo.value = mensajeFallo(fallo)
    reenfocarCorreo = true
    if (fallo instanceof ErrorEmpleadoApi && fallo.estado === 412) {
      const correoSolicitado = correoEdicion.value
      claveCorreo.value = ''
      await cargarDetalle()
      correoEdicion.value = correoSolicitado
      errorCorreo.value = mensajeFallo(fallo)
    }
  } finally {
    ocupado.value = false
  }
  if (reenfocarCorreo) await enfocarCorreoAlFinal()
}

async function confirmarAccion() {
  const empleado = detalle.value
  const revision = etag.value
  const accion = accionPendiente.value
  if (!empleado || !revision || !accion || ocupado.value) return
  error.value = ''
  ocupado.value = true
  try {
    const clave = clavesAccion[accion] || (clavesAccion[accion] = generarUuidV4())
    const token = await csrf.obtener()
    if (accion === 'PROMOCIONAR') {
      const resultado = await cliente.promocionar(empleado.idTexto, revision, clave, token)
      toast.add({
        title: 'Acceso de operador actualizado',
        description: resultado.estadoInvitacion
          ? `Invitación: ${textoInvitacion(resultado.estadoInvitacion)}.`
          : 'La cuenta quedó activa.',
        color:
          resultado.estadoInvitacion && resultado.estadoInvitacion !== 'ENVIADO'
            ? 'warning'
            : 'success',
      })
    } else {
      await cliente.desactivarAcceso(empleado.idTexto, revision, clave, token)
      toast.add({
        title: 'Acceso de operador desactivado',
        description: 'El empleado y su número se conservaron.',
        color: 'success',
      })
    }
    clavesAccion[accion] = ''
    await cargarDetalle()
    accionPendiente.value = null
    emit('actualizado')
  } catch (fallo) {
    await manejarFallo(fallo)
    error.value = mensajeFallo(fallo)
    if (fallo instanceof ErrorEmpleadoApi && (fallo.estado === 409 || fallo.estado === 412)) {
      clavesAccion[accion] = ''
      accionPendiente.value = null
      const mensaje = mensajeFallo(fallo)
      await cargarDetalle()
      error.value = mensaje
    }
  } finally {
    ocupado.value = false
  }
}
</script>

<template>
  <UModal
    v-model:open="abierta"
    title="Administrar empleado"
    :description="
      detalle && detalle.idTexto === idTexto ? 'Número de empleado: ' + detalle.codigo : undefined
    "
    :ui="uiModal"
    :dismissible="!ocupado"
    :close="!ocupado"
    :content="{ onCloseAutoFocus: restaurarFoco }"
  >
    <template #body>
      <div
        v-if="cargando && (!detalle || detalle.idTexto !== idTexto)"
        class="estado-carga"
        role="status"
      >
        Cargando información actual…
      </div>
      <div v-else-if="detalle && detalle.idTexto === idTexto" class="contenido-administracion">
        <div class="identidad-empleado">
          <h2 class="nombre-empleado">{{ nombreCompleto(detalle) }}</h2>
          <span
            class="estado-empleado"
            :class="
              detalle.estado === 'ACTIVO' ? 'estado-empleado--activo' : 'estado-empleado--inactivo'
            "
          >
            {{ detalle.estado === 'ACTIVO' ? 'Activo' : 'Inactivo' }}
          </span>
        </div>

        <form class="formulario-correo" @submit.prevent="guardarCorreo">
          <UFormField label="Correo del empleado" name="correo" :error="mensajeErrorCorreo">
            <UInput
              id="administrar-empleado-correo"
              v-model="correoEdicion"
              type="text"
              inputmode="email"
              autocomplete="email"
              maxlength="254"
              placeholder="Agrega un correo"
              class="w-full"
              :disabled="ocupado"
              :aria-invalid="Boolean(mensajeErrorCorreo)"
            />
          </UFormField>
          <div class="acciones-correo">
            <UButton
              type="submit"
              color="neutral"
              variant="outline"
              :loading="ocupado"
              :disabled="!puedeGuardarCorreo"
            >
              Guardar correo
            </UButton>
          </div>
        </form>

        <section class="seccion-acceso" aria-labelledby="titulo-acceso-operador">
          <dl class="estado-cuenta">
            <div>
              <dt id="titulo-acceso-operador">Cuenta de operador</dt>
              <dd :class="claseCuentaOperador">{{ cuentaOperador }}</dd>
            </div>
          </dl>
          <p v-if="detalle.estado === 'INACTIVO'" class="ayuda-acceso">
            Activa primero al empleado para administrar su acceso.
          </p>
          <p
            v-else-if="
              detalle.correo === null &&
              (!detalle.operador || detalle.operador.estado === 'INACTIVA')
            "
            class="ayuda-acceso"
          >
            Guarda un correo para crear o reactivar la cuenta de operador.
          </p>
          <p v-else-if="detalle.operador?.estado === 'INACTIVA'" class="ayuda-acceso">
            Reactivar el acceso conserva la misma cuenta y envía una invitación nueva.
          </p>

          <div
            v-if="accionPendiente"
            class="confirmacion-accion"
            role="group"
            aria-label="Confirmar acción"
          >
            <p>
              {{
                accionPendiente === 'PROMOCIONAR'
                  ? 'Se creará o reactivará la cuenta de operador de esta persona.'
                  : 'Se desactivará la cuenta de operador vinculada. El empleado y su número se conservarán.'
              }}
            </p>
            <div class="acciones-confirmacion">
              <UButton
                color="neutral"
                variant="outline"
                :disabled="ocupado"
                @click="accionPendiente = null"
                >Cancelar</UButton
              >
              <UButton :loading="ocupado" :disabled="ocupado" @click="confirmarAccion">
                Confirmar
              </UButton>
            </div>
          </div>
          <div v-else class="acciones-acceso">
            <UButton
              v-if="puedePromocionar"
              icon="i-lucide-user-round-plus"
              :disabled="ocupado"
              @click="accionPendiente = 'PROMOCIONAR'"
            >
              {{ etiquetaPromocion }}
            </UButton>
            <UButton
              v-if="puedeDesactivar"
              color="error"
              variant="outline"
              :disabled="ocupado"
              @click="accionPendiente = 'DESACTIVAR'"
            >
              Desactivar acceso
            </UButton>
          </div>
        </section>

        <p v-if="error" class="error-administracion" role="alert">{{ error }}</p>
      </div>
      <div v-else class="contenido-administracion">
        <p class="error-administracion" role="alert">
          {{ error || 'No pudimos cargar la información.' }}
        </p>
        <UButton color="neutral" variant="outline" :disabled="cargando" @click="cargarDetalle()">
          Reintentar
        </UButton>
      </div>
    </template>
  </UModal>
</template>

<style scoped>
.contenido-administracion {
  display: grid;
  gap: 18px;
  min-width: 0;
}
.identidad-empleado {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.nombre-empleado {
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--app-foreground);
  font-size: 1.125rem;
  font-weight: 600;
  line-height: 1.35;
}
.estado-empleado,
.estado-cuenta dd {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  width: fit-content;
  max-width: 100%;
  margin: 0;
  padding: 4px 9px;
  border: 1px solid var(--app-border);
  border-radius: 999px;
  font-size: 0.8125rem;
  font-weight: 600;
  line-height: 1.35;
}
.estado-empleado--activo,
.estado-cuenta--activa {
  border-color: color-mix(in srgb, var(--app-success) 28%, var(--app-border));
  background: color-mix(in srgb, var(--app-success) 9%, var(--app-surface));
  color: var(--app-success);
}
.estado-empleado--inactivo,
.estado-cuenta--sin-cuenta,
.estado-cuenta--inactiva {
  border-color: var(--app-border);
  background: var(--app-surface-hover);
  color: var(--app-muted);
}
.estado-cuenta--pendiente {
  border-color: color-mix(in srgb, var(--app-primary) 28%, var(--app-border));
  background: color-mix(in srgb, var(--app-primary) 8%, var(--app-surface));
  color: var(--app-primary);
}
.formulario-correo,
.seccion-acceso {
  display: grid;
  gap: 10px;
  min-width: 0;
}
.acciones-correo {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.seccion-acceso {
  border-top: 1px solid var(--app-border);
  padding-top: 16px;
}
.estado-cuenta {
  margin: 0;
}
.estado-cuenta > div {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px 16px;
}
.estado-cuenta dt {
  color: var(--app-foreground);
  font-size: 1rem;
  font-weight: 600;
}
.estado-cuenta dd {
  overflow-wrap: anywhere;
}
.ayuda-acceso,
.confirmacion-accion p {
  margin: 0;
  color: var(--app-muted);
  line-height: 1.5;
}
.error-administracion {
  margin: 0;
  color: var(--app-error);
  line-height: 1.5;
}
.acciones-acceso,
.acciones-confirmacion {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.confirmacion-accion {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  background: var(--app-surface);
}
.acciones-confirmacion {
  justify-content: flex-end;
}
.estado-carga {
  color: var(--app-muted);
}
@media (max-width: 34rem) {
  .identidad-empleado {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }
  .acciones-correo {
    align-items: stretch;
    flex-direction: column;
  }
  .acciones-acceso,
  .acciones-confirmacion {
    flex-direction: column-reverse;
    align-items: stretch;
  }
  .acciones-acceso :deep(button),
  .acciones-confirmacion :deep(button),
  .acciones-correo :deep(button) {
    width: 100%;
    justify-content: center;
  }
}
</style>
