<script setup lang="ts">
import type { CajonVision, EstadoVision } from '~/types/vision'
import { ErrorVisionApi, useClienteVision } from '~/utils/vision-api'

const props = defineProps<{
  cajones: CajonVision[]
  pendiente: boolean
  desactualizado: boolean
  mensajeError: string
  ultimaConsulta: string | null
  hayDatos: boolean
  estado: 'cargando' | 'actual' | 'historico' | 'error' | 'sin-sesion'
}>()
const emit = defineEmits<{ actualizar: [] }>()
const api = useClienteVision()
const toast = useToast()

interface EdicionNombre {
  texto: string
  editando: boolean
  guardando: boolean
  error: string
}

const ediciones = reactive<Record<string, EdicionNombre>>({})
const actualizacionManual = ref(false)

watch(
  () => props.pendiente,
  (pendiente) => {
    if (!pendiente) actualizacionManual.value = false
  },
)

function actualizar() {
  if (props.estado === 'sin-sesion' || actualizacionManual.value) return
  actualizacionManual.value = true
  if (props.pendiente) return
  emit('actualizar')
  // Si la consulta no llegó a iniciarse, no dejamos el botón en carga.
  void nextTick(() => {
    if (!props.pendiente) actualizacionManual.value = false
  })
}

watch(
  () => props.cajones,
  (cajones) => {
    const activos = new Set(cajones.map((cajon) => cajon.cajonId))
    for (const id of Object.keys(ediciones)) {
      if (!activos.has(id)) delete ediciones[id]
    }
    for (const cajon of cajones) {
      const edicion = ediciones[cajon.cajonId]
      if (!edicion) {
        ediciones[cajon.cajonId] = {
          texto: cajon.displayName ?? '',
          editando: false,
          guardando: false,
          error: '',
        }
      } else if (!edicion.editando && !edicion.guardando) {
        edicion.texto = cajon.displayName ?? ''
      }
    }
  },
  { immediate: true },
)

function nombreCajon(cajon: CajonVision): string {
  const nombre = cajon.displayName?.trim()
  if (nombre) return nombre
  const numero = /^C(\d+)$/i.exec(cajon.etiqueta)?.[1]
  return numero ? `Cajón ${numero.replace(/^0+(?=\d)/, '')}` : cajon.etiqueta
}

async function iniciarEdicion(cajon: CajonVision) {
  const edicion = ediciones[cajon.cajonId]
  if (!edicion || edicion.guardando) return
  edicion.texto = cajon.displayName ?? ''
  edicion.editando = true
  edicion.error = ''
  await nextTick()
  const campo = document.getElementById(`nombre-cajon-${cajon.cajonId}`)
  if (campo instanceof HTMLInputElement) {
    campo.focus()
    campo.setSelectionRange(campo.value.length, campo.value.length)
  }
}

function devolverFoco(cajonId: string) {
  void nextTick(() => document.getElementById(`editar-nombre-${cajonId}`)?.focus())
}

function cancelarEdicion(cajonId: string) {
  const edicion = ediciones[cajonId]
  if (!edicion || edicion.guardando) return
  edicion.texto = props.cajones.find((cajon) => cajon.cajonId === cajonId)?.displayName ?? ''
  edicion.editando = false
  edicion.error = ''
  devolverFoco(cajonId)
}

async function guardarNombre(cajonId: string) {
  const edicion = ediciones[cajonId]
  if (!edicion || edicion.guardando) return
  edicion.guardando = true
  edicion.error = ''
  try {
    await api.actualizarNombre(cajonId, edicion.texto)
    edicion.editando = false
    toast.add({ title: 'Nombre guardado', color: 'success', duration: 3000 })
    emit('actualizar')
    devolverFoco(cajonId)
  } catch (fallo) {
    edicion.error =
      fallo instanceof ErrorVisionApi ? fallo.message : 'No pudimos confirmar el guardado.'
  } finally {
    edicion.guardando = false
  }
}

const esActual = computed(() => props.estado === 'actual' && !props.desactualizado)
const observacionComun = computed(() => {
  const primera = props.cajones[0]?.observadoEn
  return primera && props.cajones.every((cajon) => cajon.observadoEn === primera) ? primera : null
})
const indicadores = computed(() => {
  const resumen = { registrados: props.cajones.length, ocupados: 0, libres: 0, noVerificables: 0 }
  for (const cajon of props.cajones) {
    if (cajon.estado === 'OCUPADO') resumen.ocupados++
    else if (cajon.estado === 'LIBRE') resumen.libres++
    else resumen.noVerificables++
  }
  return [
    { etiqueta: 'Cajones registrados', valor: resumen.registrados, registro: true },
    { etiqueta: 'Ocupados físicamente', valor: resumen.ocupados, registro: false },
    { etiqueta: 'Libres físicamente', valor: resumen.libres, registro: false },
    { etiqueta: 'No verificables', valor: resumen.noVerificables, registro: false },
  ]
})

function estadoEfectivo(cajon: CajonVision): EstadoVision {
  return esActual.value ? cajon.estado : 'NO_VERIFICABLE'
}

function etiquetaEstado(estado: EstadoVision): string {
  return {
    LIBRE: 'Libre',
    OCUPADO: 'Ocupado',
    NO_VERIFICABLE: 'No verificable',
  }[estado]
}

function iconoEstado(estado: EstadoVision): string {
  return {
    LIBRE: 'i-lucide-circle-check',
    OCUPADO: 'i-lucide-circle-x',
    NO_VERIFICABLE: 'i-lucide-circle-help',
  }[estado]
}

function fechaLegible(valor: string): string {
  if (!/(?:Z|[+-]\d{2}:\d{2})$/i.test(valor)) return valor.replace('T', ' ')
  const fecha = new Date(valor)
  if (!Number.isFinite(fecha.getTime())) return valor.replace('T', ' ')
  const meses = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
  const dosDigitos = (numero: number) => String(numero).padStart(2, '0')
  const dia = `${dosDigitos(fecha.getUTCDate())} ${meses[fecha.getUTCMonth()]} ${fecha.getUTCFullYear()}`
  const hora = `${dosDigitos(fecha.getUTCHours())}:${dosDigitos(fecha.getUTCMinutes())}:${dosDigitos(fecha.getUTCSeconds())}`
  return `${dia}, ${hora} UTC`
}
</script>

<template>
  <section class="ocupacion-vision" aria-labelledby="titulo-ocupacion-vision">
    <header class="encabezado-ocupacion">
      <div>
        <h2 id="titulo-ocupacion-vision">Ocupación física</h2>
        <p class="descripcion-ocupacion">
          La ocupación física no confirma disponibilidad para ingreso.
        </p>
      </div>
      <UButton
        type="button"
        color="neutral"
        variant="outline"
        icon="i-lucide-refresh-cw"
        :loading="actualizacionManual && pendiente"
        :disabled="estado === 'sin-sesion' || actualizacionManual"
        @click="actualizar"
      >
        {{ estado === 'error' || estado === 'historico' ? 'Reintentar' : 'Actualizar' }}
      </UButton>
    </header>

    <dl class="indicadores-ocupacion" aria-label="Resumen de ocupación física">
      <div v-for="indicador in indicadores" :key="indicador.etiqueta" class="indicador-ocupacion">
        <dt>{{ indicador.etiqueta }}</dt>
        <dd>
          {{
            esActual || (indicador.registro && hayDatos && estado !== 'sin-sesion')
              ? indicador.valor
              : '—'
          }}
        </dd>
      </div>
    </dl>

    <p v-if="estado === 'cargando' && !hayDatos" class="aviso-ocupacion" role="status">
      Consultando la ocupación física…
    </p>
    <p
      v-else-if="!esActual"
      class="aviso-ocupacion"
      :role="estado === 'error' ? 'alert' : 'status'"
    >
      {{ mensajeError || 'No pudimos actualizar la ocupación física.' }}
      <span v-if="hayDatos && estado !== 'sin-sesion'">Los datos mostrados son históricos.</span>
    </p>

    <template v-if="hayDatos && estado !== 'sin-sesion'">
      <p v-if="observacionComun" class="hora-observacion">
        Última observación:
        <time :datetime="observacionComun">{{ fechaLegible(observacionComun) }}</time>
      </p>
      <p v-if="cajones.length === 0 && esActual" class="vacio-ocupacion">
        Todavía no hay cajones registrados.
      </p>
      <p v-else-if="cajones.length === 0" class="vacio-ocupacion">
        En la última consulta no había cajones registrados.
      </p>
      <ul v-if="cajones.length" class="cajones-vision" aria-label="Cajones registrados">
        <li v-for="cajon in cajones" :key="cajon.cajonId" class="cajon-vision">
          <h3>{{ nombreCajon(cajon) }}</h3>
          <p class="estado-cajon" :class="`estado-cajon--${estadoEfectivo(cajon).toLowerCase()}`">
            <UIcon :name="iconoEstado(estadoEfectivo(cajon))" aria-hidden="true" />
            {{ etiquetaEstado(estadoEfectivo(cajon)) }}
          </p>
          <p
            v-if="!esActual && !cajon.ultimoEstadoConfirmado && cajon.estado !== 'NO_VERIFICABLE'"
            class="detalle-cajon"
          >
            Último estado informado: {{ etiquetaEstado(cajon.estado) }}
          </p>
          <p
            v-if="cajon.ultimoEstadoConfirmado && estadoEfectivo(cajon) === 'NO_VERIFICABLE'"
            class="detalle-cajon"
          >
            Última confirmación: {{ etiquetaEstado(cajon.ultimoEstadoConfirmado) }}
          </p>
          <p v-if="!observacionComun" class="detalle-cajon">
            <template v-if="cajon.observadoEn">
              Observado:
              <time :datetime="cajon.observadoEn">{{ fechaLegible(cajon.observadoEn) }}</time>
            </template>
            <template v-else>Sin observaciones</template>
          </p>
          <form
            v-if="ediciones[cajon.cajonId]?.editando"
            class="nombre-cajon"
            @submit.prevent="guardarNombre(cajon.cajonId)"
          >
            <label :for="`nombre-cajon-${cajon.cajonId}`">Nombre visible</label>
            <input
              :id="`nombre-cajon-${cajon.cajonId}`"
              v-model="ediciones[cajon.cajonId]!.texto"
              type="text"
              :disabled="ediciones[cajon.cajonId]!.guardando"
              :placeholder="nombreCajon({ ...cajon, displayName: null })"
              :aria-invalid="!!ediciones[cajon.cajonId]!.error"
              :aria-describedby="
                ediciones[cajon.cajonId]!.error ? `error-nombre-${cajon.cajonId}` : undefined
              "
            />
            <div class="acciones-nombre">
              <UButton
                type="submit"
                color="primary"
                size="sm"
                :loading="ediciones[cajon.cajonId]!.guardando"
                :disabled="ediciones[cajon.cajonId]!.guardando"
              >
                Guardar
              </UButton>
              <UButton
                type="button"
                color="neutral"
                variant="outline"
                size="sm"
                :disabled="ediciones[cajon.cajonId]!.guardando"
                @click="cancelarEdicion(cajon.cajonId)"
              >
                Cancelar
              </UButton>
            </div>
            <p
              v-if="ediciones[cajon.cajonId]!.error"
              :id="`error-nombre-${cajon.cajonId}`"
              role="alert"
            >
              {{ ediciones[cajon.cajonId]!.error }}
            </p>
          </form>
          <template v-else-if="ediciones[cajon.cajonId]">
            <UButton
              :id="`editar-nombre-${cajon.cajonId}`"
              class="accion-editar-nombre"
              type="button"
              color="neutral"
              variant="ghost"
              size="sm"
              icon="i-lucide-pencil"
              :aria-label="`Cambiar nombre de ${nombreCajon(cajon)}`"
              @click="iniciarEdicion(cajon)"
            >
              Cambiar nombre
            </UButton>
          </template>
        </li>
      </ul>
      <p v-if="ultimaConsulta && !esActual" class="ultima-consulta">
        Última consulta correcta:
        <time :datetime="ultimaConsulta">{{ fechaLegible(ultimaConsulta) }}</time>
      </p>
    </template>
  </section>
</template>

<style scoped>
.ocupacion-vision {
  width: 100%;
  border: 1px solid var(--app-border);
  border-radius: 14px;
  background: var(--app-surface);
  padding: clamp(20px, 3vw, 32px);
  color: var(--app-foreground);
  box-shadow: 0 2px 8px rgb(41 37 47 / 4%);
}
.encabezado-ocupacion {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px 24px;
}
.encabezado-ocupacion h2 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 700;
  letter-spacing: -0.025em;
}
.descripcion-ocupacion {
  margin: 8px 0 0;
  color: var(--app-muted);
  font-size: 0.88rem;
  line-height: 1.5;
}
.indicadores-ocupacion {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 9rem), 1fr));
  gap: 12px;
  margin: 20px 0 0;
}
.indicador-ocupacion {
  min-width: 0;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: var(--app-surface-hover);
  padding: 12px 14px;
}
.indicador-ocupacion dt {
  color: var(--app-muted);
  font-size: 0.82rem;
  line-height: 1.35;
}
.indicador-ocupacion dd {
  margin: 7px 0 0;
  font-size: 1.35rem;
  font-weight: 700;
  line-height: 1.2;
}
.aviso-ocupacion,
.vacio-ocupacion {
  margin: 20px 0 0;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: var(--app-surface-hover);
  padding: 12px 14px;
  color: var(--app-muted);
  font-size: 0.88rem;
  line-height: 1.5;
}
.cajones-vision {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 12rem), 1fr));
  gap: 12px;
  margin: 16px 0 0;
  padding: 0;
  list-style: none;
}
.cajon-vision {
  min-width: 0;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  padding: 14px;
  overflow-wrap: anywhere;
}
.cajon-vision h3 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 700;
}
.nombre-cajon {
  display: grid;
  gap: 7px;
  margin-top: 12px;
  font-size: 0.78rem;
}
.nombre-cajon label {
  color: var(--app-muted);
}
.nombre-cajon input {
  min-width: 0;
  width: 100%;
  border: 1px solid var(--app-border);
  border-radius: 6px;
  background: var(--app-surface);
  padding: 7px 9px;
  color: var(--app-foreground);
}
.nombre-cajon input:focus-visible {
  outline: 2px solid var(--app-focus);
  outline-offset: 2px;
}
.acciones-nombre {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.nombre-cajon p {
  margin: 0;
  color: var(--app-error);
}
.estado-cajon {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 10px 0 0;
  font-size: 0.86rem;
  font-weight: 700;
}
.estado-cajon--libre {
  color: var(--app-success);
}
.estado-cajon--ocupado {
  color: var(--app-error);
}
.estado-cajon--no_verificable {
  color: var(--app-muted);
}
.detalle-cajon,
.ultima-consulta,
.hora-observacion {
  margin: 9px 0 0;
  color: var(--app-muted);
  font-size: 0.78rem;
  line-height: 1.45;
}
.ultima-consulta {
  margin-top: 16px;
}
.hora-observacion {
  margin-top: 16px;
}
.accion-editar-nombre {
  margin-top: 10px;
}
</style>
