<script setup lang="ts">
import { nextTick } from 'vue'
import type { AccionAdministracionOperador, DetalleOperador } from '~/types/operador'

const abierta = defineModel<boolean>('open', { required: true })
const accion = defineModel<AccionAdministracionOperador | null>('accion', { required: true })
const props = defineProps<{
  detalle: DetalleOperador | null
  cargando: boolean
  ocupado?: boolean
  error?: string
  puedeReintentar?: boolean
  indiceFoco: number | null
}>()
const emit = defineEmits<{
  confirmar: [accion: AccionAdministracionOperador]
  reintentar: []
}>()

const nombreCompleto = computed(() => {
  const detalle = props.detalle
  if (!detalle) return ''
  return [detalle.nombres, detalle.primerApellido, detalle.segundoApellido]
    .filter((parte): parte is string => Boolean(parte))
    .join(' ')
})

const mostrarInvitacion = computed(() => {
  const detalle = props.detalle
  return Boolean(
    detalle &&
    (detalle.estado === 'PENDIENTE' ||
      detalle.estadoInvitacion === 'EXPIRADA' ||
      detalle.estadoInvitacion === 'CONSUMIDA'),
  )
})

const tituloAccion = computed(() => {
  if (accion.value === 'REEMITIR_INVITACION') return 'Reenviar invitación'
  if (accion.value === 'DESACTIVAR') return 'Desactivar operador'
  if (accion.value === 'REACTIVAR') return 'Reactivar operador'
  if (accion.value === 'SOLICITAR_RECUPERACION') return 'Enviar enlace para cambiar contraseña'
  return 'Detalles del operador'
})

const descripcionAccion = computed(() => {
  if (accion.value === 'REEMITIR_INVITACION') {
    return 'El enlace anterior dejará de funcionar y se enviará una invitación nueva.'
  }
  if (accion.value === 'DESACTIVAR') {
    return 'La persona no podrá entrar en esta cuenta mientras esté desactivada.'
  }
  if (accion.value === 'REACTIVAR') {
    return 'La persona tendrá que crear una contraseña nueva antes de volver a entrar.'
  }
  if (accion.value === 'SOLICITAR_RECUPERACION') {
    return 'Le enviaremos un enlace para crear una contraseña nueva.'
  }
  return ''
})

function textoEstado(estado: DetalleOperador['estado']) {
  return { PENDIENTE: 'Por activar', ACTIVA: 'Activa', INACTIVA: 'Desactivada' }[estado]
}

function colorEstado(estado: DetalleOperador['estado']): 'warning' | 'success' | 'neutral' {
  if (estado === 'PENDIENTE') return 'warning'
  if (estado === 'ACTIVA') return 'success'
  return 'neutral'
}

function textoInvitacion(estado: DetalleOperador['estadoInvitacion']) {
  if (!estado) return 'No hay una invitación activa'
  return {
    ENVIANDO: 'Enviando',
    ENVIADO: 'Enviado',
    FALLIDO: 'No se pudo enviar',
    DESCONOCIDO: 'No sabemos si se envió',
    DESHABILITADO: 'No se enviará',
    EXPIRADA: 'Venció',
    CONSUMIDA: 'Usada',
  }[estado]
}

function colorInvitacion(
  estado: DetalleOperador['estadoInvitacion'],
): 'success' | 'error' | 'primary' | 'warning' | 'neutral' {
  if (estado === 'ENVIADO' || estado === 'CONSUMIDA') return 'success'
  if (estado === 'EXPIRADA' || estado === 'FALLIDO') return 'error'
  if (estado === 'ENVIANDO') return 'primary'
  if (estado === 'DESCONOCIDO') return 'warning'
  return 'neutral'
}

function formatoFecha(fecha: string | null) {
  if (!fecha) return '—'
  const valor = new Date(fecha)
  if (Number.isNaN(valor.getTime())) return '—'
  return new Intl.DateTimeFormat('es-MX', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(valor)
}

function fechaEsFutura(fecha: string | null) {
  if (!fecha) return false
  const valor = new Date(fecha).getTime()
  return Number.isFinite(valor) && valor > Date.now()
}

async function restaurarFoco(evento: Event) {
  evento.preventDefault()
  await nextTick()
  if (props.indiceFoco !== null) {
    document.getElementById(`operador-administrar-${props.indiceFoco}`)?.focus()
  }
}
</script>

<template>
  <UModal
    v-model:open="abierta"
    :title="tituloAccion"
    :description="accion ? descripcionAccion : undefined"
    :dismissible="!props.ocupado"
    :close="!props.ocupado"
    :ui="{ overlay: 'bg-black/55 backdrop-blur-none' }"
    :content="{ onCloseAutoFocus: restaurarFoco }"
  >
    <template #body>
      <div v-if="props.cargando" class="estado-detalle" role="status">
        <UIcon name="i-lucide-loader-circle" class="icono-cargando" aria-hidden="true" />
        <p>Cargando la información…</p>
      </div>
      <div v-else-if="!props.detalle" class="estado-detalle estado-detalle--error">
        <p role="alert">{{ props.error || 'No pudimos cargar esta cuenta.' }}</p>
        <UButton
          v-if="props.puedeReintentar"
          color="neutral"
          variant="outline"
          icon="i-lucide-refresh-cw"
          @click="emit('reintentar')"
        >
          Reintentar
        </UButton>
      </div>
      <div v-else-if="accion" class="contenido-confirmacion">
        <p>
          {{ descripcionAccion }}
          <strong>{{ props.detalle.correo }}</strong>
        </p>
        <p v-if="props.error" class="error-operador" role="alert">{{ props.error }}</p>
        <footer class="acciones-modal-operador">
          <UButton
            color="neutral"
            variant="outline"
            :disabled="props.ocupado"
            @click="accion = null"
          >
            Cancelar
          </UButton>
          <UButton
            :color="accion === 'DESACTIVAR' ? 'error' : 'primary'"
            :loading="props.ocupado"
            :disabled="props.ocupado"
            @click="emit('confirmar', accion)"
          >
            Confirmar
          </UButton>
        </footer>
      </div>
      <div v-else class="detalle-operador">
        <header class="encabezado-detalle">
          <div class="identidad-operador">
            <h3>{{ nombreCompleto }}</h3>
            <p>{{ props.detalle.correo }}</p>
          </div>
          <UBadge :color="colorEstado(props.detalle.estado)" variant="soft" class="estado-cuenta">
            {{ textoEstado(props.detalle.estado) }}
          </UBadge>
        </header>
        <dl class="datos-operador">
          <div>
            <dt>Vínculo con empleado</dt>
            <dd>
              <UBadge
                :color="props.detalle.estadoConciliacion === 'VINCULADO' ? 'success' : 'neutral'"
                variant="soft"
              >
                {{ props.detalle.estadoConciliacion === 'VINCULADO' ? 'Vinculado' : 'Sin vínculo' }}
              </UBadge>
            </dd>
          </div>
          <div v-if="mostrarInvitacion">
            <dt>Invitación</dt>
            <dd>
              <UBadge :color="colorInvitacion(props.detalle.estadoInvitacion)" variant="soft">
                {{ textoInvitacion(props.detalle.estadoInvitacion) }}
              </UBadge>
            </dd>
          </div>
        </dl>
        <p v-if="fechaEsFutura(props.detalle.reenvioDisponibleEn)" class="ayuda-reenvio">
          Podrás reenviar la invitación después del
          {{ formatoFecha(props.detalle.reenvioDisponibleEn) }}.
        </p>
        <p v-if="fechaEsFutura(props.detalle.recuperacionDisponibleEn)" class="ayuda-reenvio">
          Podrás pedir otro enlace después del
          {{ formatoFecha(props.detalle.recuperacionDisponibleEn) }}.
        </p>
        <p
          v-if="
            props.detalle.estadoConciliacion === 'LEGADO_SIN_VINCULO' &&
            props.detalle.estado === 'INACTIVA'
          "
          class="ayuda-reenvio"
        >
          Vincula esta cuenta con un empleado antes de reactivarla.
        </p>
        <p v-if="props.error" class="error-operador" role="alert">{{ props.error }}</p>
        <div class="acciones-operador">
          <UButton
            v-if="props.detalle.estado === 'PENDIENTE' && props.detalle.puedeReemitirInvitacion"
            color="neutral"
            variant="outline"
            icon="i-lucide-mail-check"
            :disabled="props.ocupado"
            @click="accion = 'REEMITIR_INVITACION'"
          >
            Reenviar invitación
          </UButton>
          <UButton
            v-if="props.detalle.puedeDesactivar"
            color="error"
            variant="outline"
            icon="i-lucide-user-round-x"
            :disabled="props.ocupado"
            @click="accion = 'DESACTIVAR'"
          >
            Desactivar cuenta
          </UButton>
          <UButton
            v-if="props.detalle.puedeReactivar && props.detalle.estadoConciliacion === 'VINCULADO'"
            color="primary"
            variant="outline"
            icon="i-lucide-user-round-check"
            :disabled="props.ocupado"
            @click="accion = 'REACTIVAR'"
          >
            Reactivar cuenta
          </UButton>
          <UButton
            v-if="props.detalle.puedeSolicitarRecuperacion"
            color="neutral"
            variant="outline"
            icon="i-lucide-key-round"
            :disabled="props.ocupado"
            @click="accion = 'SOLICITAR_RECUPERACION'"
          >
            Recuperar contraseña
          </UButton>
        </div>
      </div>
    </template>
  </UModal>
</template>

<style scoped>
.detalle-operador,
.contenido-confirmacion {
  display: grid;
  gap: 20px;
}
.encabezado-detalle {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--app-border);
  padding-bottom: 18px;
}
.identidad-operador {
  min-width: 0;
}
.identidad-operador h3 {
  margin: 0;
  color: var(--app-foreground);
  font-size: 1.125rem;
  font-weight: 650;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.identidad-operador p {
  margin: 6px 0 0;
  color: var(--app-muted);
  overflow-wrap: anywhere;
}
.estado-cuenta {
  flex: 0 0 auto;
}
.datos-operador {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  margin: 0;
}
.datos-operador > div {
  min-width: 0;
}
.datos-operador dt {
  margin-bottom: 7px;
  color: var(--app-muted);
  font-size: 0.82rem;
}
.datos-operador dd {
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--app-foreground);
}
.datos-operador dd :deep(.u-badge) {
  vertical-align: middle;
}
.ayuda-reenvio,
.contenido-confirmacion > p {
  margin: 0;
  color: var(--app-muted);
  line-height: 1.55;
}
.contenido-confirmacion strong {
  color: var(--app-foreground);
}
.acciones-operador {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  border-top: 1px solid var(--app-border);
  padding-top: 16px;
}
.acciones-modal-operador {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.estado-detalle {
  display: grid;
  min-height: 9rem;
  gap: 12px;
  place-content: center;
  justify-items: center;
  color: var(--app-muted);
  text-align: center;
}
.estado-detalle p {
  margin: 0;
}
.estado-detalle--error,
.error-operador {
  color: var(--app-error);
}
.icono-cargando {
  animation: girar 1s linear infinite;
}
@keyframes girar {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 38rem) {
  .encabezado-detalle {
    flex-direction: column;
  }
  .datos-operador {
    grid-template-columns: 1fr;
  }
  .acciones-operador,
  .acciones-modal-operador {
    flex-direction: column-reverse;
  }
  .acciones-operador :deep(button),
  .acciones-modal-operador :deep(button) {
    width: 100%;
    justify-content: center;
  }
}
</style>
