<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import SelectorPersonaRfid1 from '~/components/admin/tarjetas-rfid/SelectorPersonaRfid1.vue'
import { crearRetornoFocoRfid1 } from '~/composables/useRetornoFocoRfid1'
import type {
  CandidatoPersonaRfid1,
  CapturaRfid1,
  EstadoConexionRfid1,
  FiltroTipoEntidadRfid1,
  PersonaRfid1,
  VistaPreviaRfid1,
} from '~/types/rfid1'

const props = defineProps<{
  open: boolean
  paso: 1 | 2 | 3
  tipoEntidad: FiltroTipoEntidadRfid1
  tiposEntidadDisponibles: FiltroTipoEntidadRfid1[]
  busqueda: string
  candidatos: CandidatoPersonaRfid1[]
  seleccionada: CandidatoPersonaRfid1 | null
  persona: PersonaRfid1 | null
  captura: CapturaRfid1 | null
  vistaPrevia: VistaPreviaRfid1 | null
  candidatosPendientes: boolean
  errorBusqueda: string
  fase: string
  mensajeError: string
  mensajeCaptura: string
  segundosRestantes: number | null
  ocupado: boolean
  estadoConexion: EstadoConexionRfid1
  etiquetaConexion: string
}>()

const emit = defineEmits<{
  'update:tipoEntidad': [valor: FiltroTipoEntidadRfid1]
  'update:busqueda': [valor: string]
  seleccionar: [candidato: CandidatoPersonaRfid1]
  cambiarPersona: []
  continuar: []
  iniciar: []
  confirmar: []
  cancelarCaptura: []
  volver: []
  escanearOtra: []
  cerrar: []
}>()

const seleccionValida = computed(() => Boolean(props.seleccionada?.elegible))
const puedeIniciar = computed(
  () =>
    Boolean(props.seleccionada) &&
    !props.ocupado &&
    (!props.captura || !['PENDIENTE', 'ESCANEANDO', 'VISTA_PREVIA'].includes(props.captura.estado)),
)
const puedeConfirmar = computed(
  () =>
    props.captura?.estado === 'VISTA_PREVIA' &&
    Boolean(props.vistaPrevia) &&
    !props.ocupado &&
    (props.segundosRestantes ?? 0) > 0,
)

const encabezadoPaso = ref<HTMLHeadingElement | null>(null)
const uiModal = {
  overlay: 'bg-black/55',
  content: 'max-w-xl rounded-2xl border border-[var(--app-border)] bg-white shadow-xl',
  header: 'px-5 py-4 sm:px-6',
  body: 'px-5 py-4 sm:px-6 sm:py-5',
}

const estadoLectura = computed(() => {
  if (props.fase === 'iniciando') return 'Iniciando lectura'
  if (props.fase === 'cancelando') return 'Cancelando lectura'
  if (props.fase === 'confirmando') return 'Confirmando asociación'
  switch (props.captura?.estado) {
    case 'PENDIENTE':
      return 'Preparando lectura'
    case 'ESCANEANDO':
      return props.captura.codigoError === 'TARJETA_YA_REGISTRADA'
        ? 'Tarjeta ya utilizada'
        : 'Esperando tarjeta'
    case 'VISTA_PREVIA':
      return 'Tarjeta detectada'
    case 'COMPLETADA':
      return 'Asociación confirmada'
    case 'CANCELADA':
      return 'Lectura cancelada'
    case 'EXPIRADA':
      return 'Tiempo agotado'
    case 'RECHAZADA':
      return 'No se pudo continuar'
    default:
      return 'Lista para iniciar'
  }
})

const mensajeLectura = computed(() => {
  if (props.mensajeCaptura) return props.mensajeCaptura
  if (props.fase === 'iniciando') return 'Estamos preparando el lector.'
  if (props.fase === 'cancelando') return 'Estamos cancelando la lectura.'
  if (props.fase === 'confirmando') return 'Estamos guardando la asociación.'
  return 'Inicia la lectura cuando estés frente al lector.'
})

const mensajeConexion = computed(() => {
  if (props.estadoConexion === 'DESCONECTADO') {
    return 'No se detecta conexión con el lector. La lectura puede quedar pendiente; puedes cancelarla.'
  }
  if (props.etiquetaConexion === 'No se pudo verificar') {
    return 'No se pudo comprobar la conexión. El estado no confirma si el lector está listo.'
  }
  if (props.estadoConexion === 'CONECTADO') {
    return 'El lector aparece conectado. Espera la indicación de lectura antes de continuar.'
  }
  return 'Comprobando la conexión con el lector.'
})

function tiempoRestante(segundos: number | null) {
  if (segundos === null) return 'Calculando…'
  return `${Math.floor(segundos / 60)}:${String(segundos % 60).padStart(2, '0')} restantes`
}

function enfocarContenido(evento: Event) {
  if (!import.meta.client) return
  evento.preventDefault()
  void nextTick(() => {
    if (props.paso !== 1) {
      encabezadoPaso.value?.focus()
      return
    }
    const campo = document.getElementById('rfid-busqueda-persona')
    if (!(campo instanceof HTMLInputElement)) return
    campo.focus()
    campo.setSelectionRange(campo.value.length, campo.value.length)
  })
}

watch(
  () => props.paso,
  (pasoNuevo, pasoAnterior) => {
    if (!props.open || !import.meta.client || (pasoAnterior === 2 && pasoNuevo === 3)) return
    void nextTick(() => encabezadoPaso.value?.focus())
  },
)

const devolverFoco = crearRetornoFocoRfid1(() => document.getElementById('rfid-abrir-asociacion'))
</script>

<template>
  <UModal
    :open="props.open"
    :close="false"
    :dismissible="true"
    title="Asociar tarjeta"
    description="Selecciona a quién asociarla y revisa la lectura antes de confirmar."
    :ui="uiModal"
    :content="{ onOpenAutoFocus: enfocarContenido, onCloseAutoFocus: devolverFoco }"
    @update:open="(abierta) => !abierta && emit('cerrar')"
  >
    <template #body>
      <div class="flujo-asociacion-rfid">
        <ol class="pasos-asociacion-rfid" aria-label="Progreso de la asociación">
          <li
            v-for="(titulo, indice) in ['Persona', 'Lectura RFID', 'Confirmar']"
            :key="titulo"
            :class="{ 'paso-asociacion-rfid--actual': props.paso === indice + 1 }"
            :aria-current="props.paso === indice + 1 ? 'step' : undefined"
            :aria-label="`Paso ${indice + 1}: ${titulo}`"
          >
            <span class="paso-asociacion-rfid__numero" :aria-hidden="true">{{ indice + 1 }}</span>
            <span class="paso-asociacion-rfid__titulo">{{ titulo }}</span>
          </li>
        </ol>

        <section v-if="props.paso === 1" aria-labelledby="titulo-paso-persona">
          <h2 id="titulo-paso-persona" ref="encabezadoPaso" tabindex="-1">Elige una persona</h2>
          <SelectorPersonaRfid1
            :tipo-entidad="props.tipoEntidad"
            :tipos-entidad-disponibles="props.tiposEntidadDisponibles"
            :busqueda="props.busqueda"
            :candidatos="props.candidatos"
            :seleccionada="props.seleccionada"
            :pendientes="props.candidatosPendientes"
            :error="props.errorBusqueda"
            @update:tipo-entidad="emit('update:tipoEntidad', $event)"
            @update:busqueda="emit('update:busqueda', $event)"
            @seleccionar="emit('seleccionar', $event)"
            @cambiar-persona="emit('cambiarPersona')"
            @cerrar="emit('cerrar')"
          />
        </section>

        <section v-else-if="props.paso === 2" aria-labelledby="titulo-paso-escaneo">
          <h2 id="titulo-paso-escaneo" ref="encabezadoPaso" tabindex="-1">Lee la tarjeta</h2>
          <div v-if="props.persona" class="identidad-captura-rfid">
            <span>Persona seleccionada</span>
            <strong>{{ props.persona.nombreCompleto }}</strong>
            <span>{{ props.persona.tipoEntidad }} · {{ props.persona.codigo }}</span>
          </div>
          <div class="panel-estados-rfid">
            <div
              class="estado-conexion-modal-rfid"
              role="status"
              aria-live="polite"
              aria-atomic="true"
              aria-label="Estado de conexión con el lector"
            >
              <span class="etiqueta-estado-rfid">Conexión con el lector</span>
              <strong>{{ props.etiquetaConexion }}</strong>
              <p>{{ mensajeConexion }}</p>
            </div>
            <div
              class="estado-captura-rfid"
              role="status"
              aria-labelledby="estado-lectura-label"
              aria-live="polite"
              aria-atomic="true"
            >
              <UIcon
                :name="props.ocupado ? 'i-lucide-loader-circle' : 'i-lucide-radio'"
                :class="{ 'icono-cargando': props.ocupado }"
                aria-hidden="true"
              />
              <div>
                <span id="estado-lectura-label" class="etiqueta-estado-rfid">
                  Estado de la lectura
                </span>
                <strong>{{ estadoLectura }}</strong>
                <p>{{ mensajeLectura }}</p>
              </div>
            </div>
          </div>
          <p
            v-if="props.captura && ['PENDIENTE', 'ESCANEANDO'].includes(props.captura.estado)"
            class="tiempo-captura-rfid"
            aria-label="Tiempo restante de lectura"
          >
            {{ tiempoRestante(props.segundosRestantes) }}
          </p>
          <p v-if="props.mensajeError" class="mensaje-error-rfid" role="alert">
            {{ props.mensajeError }}
          </p>
        </section>

        <section v-else aria-labelledby="titulo-paso-confirmacion">
          <h2 id="titulo-paso-confirmacion" ref="encabezadoPaso" tabindex="-1">
            Revisa la tarjeta
          </h2>
          <dl v-if="props.persona && props.vistaPrevia" class="resumen-asociacion-rfid">
            <div>
              <dt>Persona</dt>
              <dd>{{ props.persona.nombreCompleto }}</dd>
            </div>
            <div>
              <dt>Tipo</dt>
              <dd>{{ props.persona.tipoEntidad === 'CLIENTE' ? 'Cliente' : 'Empleado' }}</dd>
            </div>
            <div>
              <dt>Código</dt>
              <dd>{{ props.persona.codigo }}</dd>
            </div>
            <div>
              <dt>UID</dt>
              <dd>
                <code>{{ props.vistaPrevia.uid }}</code>
              </dd>
            </div>
          </dl>
          <p v-else class="estado-captura-rfid" role="status">
            Consultando la lectura de forma segura…
          </p>
          <p
            v-if="props.persona && props.vistaPrevia"
            class="aviso-confirmacion-rfid"
            role="status"
            aria-live="polite"
          >
            Tarjeta detectada. Se asociará solo si confirmas.
          </p>
          <p class="tiempo-captura-rfid" aria-live="polite">
            {{ tiempoRestante(props.segundosRestantes) }}
          </p>
          <p v-if="props.mensajeError" class="mensaje-error-rfid" role="alert">
            {{ props.mensajeError }}
          </p>
        </section>

        <footer class="acciones-asociacion-rfid">
          <UButton
            type="button"
            color="neutral"
            variant="ghost"
            :disabled="props.ocupado"
            @click="emit('cerrar')"
            >Cerrar</UButton
          >
          <UButton v-if="props.paso === 1" :disabled="!seleccionValida" @click="emit('continuar')">
            Siguiente
          </UButton>
          <template v-else-if="props.paso === 2">
            <UButton
              v-if="props.captura && ['PENDIENTE', 'ESCANEANDO'].includes(props.captura.estado)"
              color="error"
              variant="outline"
              :disabled="props.ocupado"
              @click="emit('cancelarCaptura')"
            >
              Cancelar lectura
            </UButton>
            <UButton
              v-if="props.captura && ['EXPIRADA', 'CANCELADA'].includes(props.captura.estado)"
              color="neutral"
              variant="outline"
              :disabled="!props.seleccionada || props.ocupado"
              @click="emit('iniciar')"
            >
              Iniciar otra lectura
            </UButton>
            <UButton
              v-else-if="!props.captura || props.captura.estado === 'COMPLETADA'"
              :disabled="!puedeIniciar"
              :loading="props.fase === 'iniciando'"
              @click="emit('iniciar')"
            >
              Iniciar lectura
            </UButton>
            <UButton
              color="neutral"
              variant="outline"
              :disabled="props.ocupado"
              @click="emit('volver')"
            >
              Volver
            </UButton>
          </template>
          <template v-else>
            <UButton
              color="error"
              variant="outline"
              :disabled="props.ocupado"
              @click="emit('cancelarCaptura')"
            >
              Cancelar lectura
            </UButton>
            <UButton
              color="neutral"
              variant="outline"
              :disabled="props.ocupado"
              @click="emit('escanearOtra')"
            >
              Escanear otra tarjeta
            </UButton>
            <UButton
              :disabled="!puedeConfirmar"
              color="primary"
              variant="solid"
              :loading="props.fase === 'confirmando'"
              @click="emit('confirmar')"
            >
              Confirmar asociación
            </UButton>
          </template>
        </footer>
      </div>
    </template>
  </UModal>
</template>

<style scoped>
.flujo-asociacion-rfid {
  display: grid;
  gap: 16px;
}
.pasos-asociacion-rfid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
  padding: 0;
  color: var(--app-muted);
  font-size: 0.8rem;
  list-style: none;
}
.pasos-asociacion-rfid li {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 2px;
  text-align: center;
}
.paso-asociacion-rfid__numero {
  display: grid;
  width: 28px;
  height: 28px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid var(--app-border);
  border-radius: 50%;
  color: var(--app-foreground);
  font-size: 0.8rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.paso-asociacion-rfid--actual .paso-asociacion-rfid__numero,
.pasos-asociacion-rfid [aria-current='step'] .paso-asociacion-rfid__numero {
  border-color: var(--app-primary);
  background: var(--app-primary);
  color: white;
}
.paso-asociacion-rfid__titulo {
  max-width: 100%;
  color: var(--app-muted);
  font-size: 0.68rem;
  font-weight: 500;
  line-height: 1.2;
}
.pasos-asociacion-rfid [aria-current='step'] .paso-asociacion-rfid__titulo {
  color: var(--app-primary);
  font-weight: 700;
}
.flujo-asociacion-rfid h2 {
  margin: 0 0 14px;
  color: var(--app-foreground);
  font-size: 1.08rem;
  font-weight: 650;
}
.flujo-asociacion-rfid h2:focus {
  outline: 2px solid var(--app-focus, var(--app-accent));
  outline-offset: 4px;
}
.panel-estados-rfid {
  display: grid;
  gap: 10px;
}
.estado-conexion-modal-rfid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 4px 12px;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  padding: 12px 14px;
  background: var(--app-surface);
}
.estado-conexion-modal-rfid strong {
  color: var(--app-foreground);
  font-weight: 650;
}
.estado-conexion-modal-rfid p {
  grid-column: 1 / -1;
  margin: 0;
  color: var(--app-muted);
  font-size: 0.88rem;
}
.etiqueta-estado-rfid {
  color: var(--app-muted);
  font-size: 0.82rem;
}
.identidad-captura-rfid,
.estado-captura-rfid {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  padding: 12px 14px;
  background: var(--app-surface);
}
.identidad-captura-rfid {
  display: grid;
  gap: 3px;
  margin-bottom: 12px;
}
.identidad-captura-rfid span,
.tiempo-captura-rfid {
  color: var(--app-muted);
  font-size: 0.86rem;
}
.identidad-captura-rfid strong,
.estado-captura-rfid strong {
  color: var(--app-foreground);
  font-weight: 650;
}
.estado-captura-rfid p {
  margin: 3px 0 0;
  color: var(--app-muted);
  font-size: 0.88rem;
}
.estado-captura-rfid > div {
  display: grid;
  gap: 3px;
}
.tiempo-captura-rfid {
  margin: 10px 0 0;
  font-variant-numeric: tabular-nums;
}
.resumen-asociacion-rfid {
  display: grid;
  gap: 0;
  margin: 0;
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  background: var(--app-surface);
}
.resumen-asociacion-rfid > div {
  display: grid;
  grid-template-columns: minmax(7rem, 0.7fr) minmax(0, 1fr);
  gap: 8px 12px;
  border-bottom: 1px solid var(--app-border);
  padding: 10px 14px;
}
.resumen-asociacion-rfid > div:last-child {
  border-bottom: 0;
}
.resumen-asociacion-rfid dt {
  color: var(--app-muted);
  font-size: 0.86rem;
}
.resumen-asociacion-rfid dd {
  margin: 0;
  color: var(--app-foreground);
  overflow-wrap: anywhere;
  font-weight: 550;
}
.resumen-asociacion-rfid code {
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}
.mensaje-error-rfid {
  margin: 12px 0 0;
  color: var(--app-error);
}
.aviso-confirmacion-rfid {
  margin: 12px 0 0;
  color: var(--app-muted);
  font-size: 0.9rem;
}
.acciones-asociacion-rfid {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
  border-top: 1px solid var(--app-border);
  padding-top: 16px;
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
  .pasos-asociacion-rfid li {
    min-height: 30px;
  }
  .acciones-asociacion-rfid {
    flex-direction: column;
  }
  .acciones-asociacion-rfid :deep(button) {
    width: 100%;
    justify-content: center;
  }
  .resumen-asociacion-rfid > div {
    grid-template-columns: minmax(0, 1fr);
    gap: 3px;
  }
}
</style>
