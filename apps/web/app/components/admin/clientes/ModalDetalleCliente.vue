<script setup lang="ts">
import { nextTick, onScopeDispose, watch } from 'vue'
import type { EstadoMembresiaCliente } from '~/types/cliente'
import type { DetalleClienteAdministracion } from '~/types/cliente-admin'
import {
  ErrorClientesAdministracionApi,
  useClienteAdministracionClientes,
} from '~/utils/clientes-admin-api'

const abierta = defineModel<boolean>('open', { required: true })
const props = defineProps<{ codigo: string | null; actualizacion?: number }>()
const clienteApi = useClienteAdministracionClientes()
const sesion = useSesion()
const detalle = ref<DetalleClienteAdministracion | null>(null)
const cargando = ref(false)
const mensajeError = ref('')
let codigoFoco: string | null = props.codigo
let solicitud = 0
let controlador: AbortController | undefined
const zonaHoraria = 'America/Mexico_City'
const uiModal = {
  overlay: 'bg-black/55',
  content: 'max-w-xl rounded-2xl border border-[var(--app-border)] bg-white shadow-xl',
  header: 'px-5 py-4 sm:px-6',
  title: 'text-lg font-semibold',
  description: 'mt-1 text-sm',
  body: 'px-5 py-4 sm:px-6 sm:py-5',
}

const etiquetasEstado: Record<EstadoMembresiaCliente, string> = {
  SIN_MEMBRESIA: 'Sin membresía',
  PENDIENTE: 'Pendiente',
  ACTIVA: 'Activa',
  PAGO_VENCIDO: 'Pago vencido',
  CANCELADA: 'Cancelada',
  INACTIVA: 'Inactiva',
}

function cancelarSolicitud() {
  solicitud += 1
  controlador?.abort()
  controlador = undefined
  cargando.value = false
}

async function cargar(codigo: string) {
  cancelarSolicitud()
  const actual = ++solicitud
  const nuevoControlador = new AbortController()
  controlador = nuevoControlador
  codigoFoco = codigo
  cargando.value = true
  mensajeError.value = ''
  try {
    const respuesta = await clienteApi.consultar(codigo, nuevoControlador.signal)
    if (actual === solicitud && abierta.value && props.codigo === codigo) detalle.value = respuesta
  } catch (fallo) {
    if (nuevoControlador.signal.aborted || actual !== solicitud) return
    if (fallo instanceof ErrorClientesAdministracionApi && fallo.estado === 401) {
      await sesion.limpiar()
      await navigateTo('/panel')
      return
    }
    mensajeError.value =
      fallo instanceof ErrorClientesAdministracionApi
        ? fallo.message
        : 'No pudimos cargar la información de este cliente. Inténtalo de nuevo.'
  } finally {
    if (actual === solicitud) {
      cargando.value = false
      controlador = undefined
    }
  }
}

function limpiar() {
  cancelarSolicitud()
  detalle.value = null
  mensajeError.value = ''
}

function reintentar() {
  if (props.codigo) void cargar(props.codigo)
}

watch(
  [abierta, () => props.codigo, () => props.actualizacion],
  ([visible, codigo], [antesVisible]) => {
    if (visible && codigo) {
      void cargar(codigo)
    } else if (antesVisible) {
      limpiar()
    }
  },
  { immediate: true },
)

async function restaurarFoco(evento: Event) {
  evento.preventDefault()
  await nextTick()
  if (codigoFoco) document.getElementById(`cliente-detalle-${codigoFoco}`)?.focus()
  if (!document.activeElement || document.activeElement === document.body) {
    document.getElementById('titulo-clientes')?.focus()
  }
}

function formatoFecha(fecha: string | null) {
  if (!fecha) return '—'
  const fechaSoloDia = /^(\d{4})-(\d{2})-(\d{2})$/.exec(fecha)
  let valor: Date
  if (fechaSoloDia) {
    const anio = Number(fechaSoloDia[1])
    const mes = Number(fechaSoloDia[2])
    const dia = Number(fechaSoloDia[3])
    valor = new Date(Date.UTC(anio, mes - 1, dia, 12))
    if (
      valor.getUTCFullYear() !== anio ||
      valor.getUTCMonth() !== mes - 1 ||
      valor.getUTCDate() !== dia
    ) {
      return '—'
    }
  } else {
    valor = new Date(fecha)
  }
  if (Number.isNaN(valor.getTime())) return '—'
  return new Intl.DateTimeFormat('es-MX', {
    dateStyle: 'medium',
    timeZone: zonaHoraria,
  }).format(valor)
}

const nombrePlan = computed(() => {
  const nombre = detalle.value?.membresia?.plan.nombre
  return typeof nombre === 'string' && nombre.trim() ? nombre.trim() : '—'
})

const precio = computed(() => {
  const plan = detalle.value?.membresia?.plan
  if (
    !plan ||
    !Number.isFinite(plan.importeMenorUnidad) ||
    typeof plan.moneda !== 'string' ||
    !plan.moneda.trim()
  ) {
    return '—'
  }
  const moneda = plan.moneda.toUpperCase()
  try {
    const formato = new Intl.NumberFormat('es-MX', {
      style: 'currency',
      currency: moneda,
      currencyDisplay: 'code',
    })
    const digitos = formato.resolvedOptions().maximumFractionDigits ?? 2
    return formato.format(plan.importeMenorUnidad / 10 ** digitos)
  } catch {
    return `${plan.importeMenorUnidad} ${moneda}`
  }
})

const frecuencia = computed(() => {
  const plan = detalle.value?.membresia?.plan
  if (
    !plan ||
    typeof plan.intervalo !== 'string' ||
    !Number.isInteger(plan.intervaloCantidad) ||
    plan.intervaloCantidad < 1
  ) {
    return '—'
  }
  const unidad = plan.intervalo.toLowerCase()
  const unidades: Record<string, [string, string]> = {
    day: ['día', 'días'],
    week: ['semana', 'semanas'],
    month: ['mes', 'meses'],
    year: ['año', 'años'],
    dia: ['día', 'días'],
    semana: ['semana', 'semanas'],
    mes: ['mes', 'meses'],
    anio: ['año', 'años'],
  }
  const etiquetas = unidades[unidad]
  if (!etiquetas) return '—'
  const cantidad = plan.intervaloCantidad
  return `Cada ${cantidad} ${etiquetas[cantidad === 1 ? 0 : 1]}`
})

function claseEstado(estado: EstadoMembresiaCliente) {
  return `estado-detalle-cliente--${estado.toLowerCase().replaceAll('_', '-')}`
}

onScopeDispose(limpiar)
</script>

<template>
  <UModal
    v-model:open="abierta"
    title="Detalles del cliente"
    :description="props.codigo ? `Código ${props.codigo}` : 'Código no disponible'"
    :content="{ onCloseAutoFocus: restaurarFoco }"
    :ui="uiModal"
  >
    <template #body>
      <div v-if="cargando" class="estado-detalle" role="status">
        <UIcon name="i-lucide-loader-circle" class="icono-cargando" aria-hidden="true" />
        <p>Cargando la información del cliente…</p>
      </div>
      <div v-else-if="mensajeError" class="estado-detalle estado-detalle--error">
        <p role="alert">{{ mensajeError }}</p>
        <UButton color="neutral" variant="outline" icon="i-lucide-refresh-cw" @click="reintentar">
          Reintentar
        </UButton>
      </div>
      <div v-else-if="detalle" class="detalle-cliente">
        <div class="identidad-cliente">
          <h2>{{ detalle.nombreCompleto }}</h2>
          <span class="estado-detalle-cliente" :class="claseEstado(detalle.estadoMembresia)">
            <span class="punto-estado-detalle" aria-hidden="true" />
            {{ etiquetasEstado[detalle.estadoMembresia] }}
          </span>
        </div>
        <p v-if="!detalle.membresia" class="sin-membresia">Este cliente no tiene una membresía.</p>
        <div v-else class="datos-membresia">
          <div class="plan-membresia">
            <span>Plan</span>
            <p>{{ nombrePlan }}</p>
          </div>
          <dl class="precio-frecuencia">
            <div>
              <dt>Precio</dt>
              <dd class="precio-destacado">{{ precio }}</dd>
            </div>
            <div>
              <dt>Frecuencia</dt>
              <dd>{{ frecuencia }}</dd>
            </div>
          </dl>
          <dl class="fechas-membresia">
            <div>
              <dt>Periodo actual</dt>
              <dd class="rango-periodo">
                <time
                  v-if="detalle.membresia.periodoInicio"
                  :datetime="detalle.membresia.periodoInicio"
                >
                  {{ formatoFecha(detalle.membresia.periodoInicio) }}
                </time>
                <span v-else>—</span>
                <span aria-hidden="true">–</span>
                <time v-if="detalle.membresia.periodoFin" :datetime="detalle.membresia.periodoFin">
                  {{ formatoFecha(detalle.membresia.periodoFin) }}
                </time>
                <span v-else>—</span>
              </dd>
            </div>
            <div>
              <dt>Próximo cobro</dt>
              <dd>
                <time
                  v-if="detalle.membresia.siguienteCobroEn"
                  :datetime="detalle.membresia.siguienteCobroEn"
                >
                  {{ formatoFecha(detalle.membresia.siguienteCobroEn) }}
                </time>
                <span v-else>—</span>
              </dd>
            </div>
          </dl>
        </div>
        <p v-if="detalle.membresia?.cancelacionAlFinal" class="aviso-cancelacion" role="status">
          La membresía terminará al finalizar el periodo actual.
        </p>
      </div>
    </template>
  </UModal>
</template>

<style scoped>
.estado-detalle {
  display: grid;
  min-height: 10rem;
  gap: 12px;
  place-content: center;
  justify-items: center;
  text-align: center;
  color: var(--app-muted);
}
.estado-detalle p,
.identidad-cliente h2,
.sin-membresia,
.aviso-cancelacion {
  margin: 0;
}
.estado-detalle--error {
  color: var(--app-error);
}
.icono-cargando {
  animation: girar 1s linear infinite;
}
.detalle-cliente {
  display: grid;
  gap: 18px;
}
.identidad-cliente {
  display: grid;
  justify-items: start;
  gap: 10px;
}
.identidad-cliente h2 {
  margin: 0;
  color: var(--app-foreground);
  font-size: 1.2rem;
  line-height: 1.3;
}
.estado-detalle-cliente {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 0.8rem;
  font-weight: 700;
}
.estado-detalle-cliente--sin-membresia,
.estado-detalle-cliente--pendiente,
.estado-detalle-cliente--inactiva {
  background: #f0edf2;
  color: #625b68;
}
.estado-detalle-cliente--activa {
  background: #e7f5ed;
  color: #176b42;
}
.estado-detalle-cliente--pago-vencido {
  background: #fff2df;
  color: #8a4b08;
}
.estado-detalle-cliente--cancelada {
  background: #fbe9e8;
  color: #9f3833;
}
.punto-estado-detalle {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}
.datos-membresia {
  display: grid;
  gap: 12px;
  margin: 0;
}
.plan-membresia > span,
.precio-frecuencia dt,
.fechas-membresia dt {
  color: var(--app-muted);
  font-size: 0.84rem;
}
.plan-membresia,
.precio-frecuencia > div {
  border: 1px solid var(--app-border);
  border-radius: 12px;
  padding: 13px 14px;
  background: var(--app-surface-muted);
}
.plan-membresia p,
.precio-frecuencia dd {
  margin: 4px 0 0;
  color: var(--app-foreground);
  font-weight: 600;
  overflow-wrap: anywhere;
}
.plan-membresia p {
  margin-bottom: 0;
}
.precio-frecuencia {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin: 0;
}
.precio-frecuencia > div {
  display: grid;
  align-content: start;
  gap: 4px;
}
.precio-frecuencia .precio-destacado {
  margin-top: 0;
  font-size: 1.15rem;
  font-weight: 750;
}
.fechas-membresia {
  display: grid;
  gap: 12px;
  margin: 0;
}
.fechas-membresia > div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 18px;
  border-top: 1px solid var(--app-border);
  padding-top: 12px;
}
.fechas-membresia dd {
  margin: 0;
  color: var(--app-foreground);
  font-weight: 600;
  text-align: right;
  overflow-wrap: anywhere;
}
.rango-periodo {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 5px;
}
.sin-membresia {
  border-radius: 12px;
  padding: 16px;
  background: var(--app-surface-muted);
  color: var(--app-muted);
}
.aviso-cancelacion {
  border-radius: 12px;
  padding: 14px;
  background: #fff2df;
  color: #8a4b08;
}
@keyframes girar {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .icono-cargando {
    animation-duration: 3s;
  }
}
@media (max-width: 28rem) {
  .precio-frecuencia {
    grid-template-columns: 1fr;
  }
  .fechas-membresia > div {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }
  .fechas-membresia dd {
    text-align: left;
  }
  .rango-periodo {
    justify-content: flex-start;
  }
}
</style>
