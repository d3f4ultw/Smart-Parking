<script setup lang="ts">
import type { PortalCliente } from '~/types/cliente'
import AccionCheckoutMembresia from '~/components/clientes/AccionCheckoutMembresia.vue'

/** Información del cliente y su membresía; también indica cuál de las dos secciones mostrar. */
interface Props {
  seccion: 'cuenta' | 'membresia'
  portal: {
    cliente: Pick<
      PortalCliente['cliente'],
      'nombres' | 'primerApellido' | 'segundoApellido' | 'correo'
    >
    membresia: {
      estado: PortalCliente['membresia']['estado']
      periodoInicio: string | null
      periodoFin: string | null
      siguienteCobroEn: string | null
      cancelacionAlFinal: boolean
      puedeComprar: boolean
      checkoutPendiente: PortalCliente['membresia']['checkoutPendiente']
      plan: Pick<
        PortalCliente['membresia']['plan'],
        'nombre' | 'importeMenorUnidad' | 'moneda' | 'intervalo' | 'intervaloCantidad'
      >
    }
  }
}

const props = defineProps<Props>()
const nombreCompleto = computed(() =>
  [
    props.portal.cliente.nombres,
    props.portal.cliente.primerApellido,
    props.portal.cliente.segundoApellido,
  ]
    .filter(Boolean)
    .join(' '),
)
/** Muestra el importe, la moneda y cada cuánto se cobra el plan con un formato legible. */
const precioMembresia = computed(() => {
  const plan = props.portal.membresia.plan
  const precio = new Intl.NumberFormat('es-MX', {
    style: 'currency',
    currency: plan.moneda,
    currencyDisplay: 'symbol',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(plan.importeMenorUnidad / 100)
  const unidad =
    ({ day: 'día', week: 'semana', month: 'mes', year: 'año' } as Record<string, string>)[
      plan.intervalo
    ] ?? 'periodo'
  const cantidad = plan.intervaloCantidad || 1
  const plural = unidad === 'día' ? 'días' : unidad === 'año' ? 'años' : unidad + 's'
  const intervalo = cantidad === 1 ? unidad : cantidad + ' ' + plural
  return precio + ' ' + plan.moneda.toUpperCase() + ' / ' + intervalo
})
const etiquetaEstadoMembresia = computed(
  () =>
    ({
      SIN_MEMBRESIA: 'Sin membresía activa',
      PENDIENTE: 'Membresía pendiente',
      ACTIVA: 'Membresía activa',
      PAGO_VENCIDO: 'Pago pendiente',
      CANCELADA: 'Membresía cancelada',
      INACTIVA: 'Membresía inactiva',
    })[props.portal.membresia.estado] ?? 'Estado no disponible',
)
const claseEstadoMembresia = computed(() => {
  const estado = props.portal.membresia.estado
  if (estado === 'ACTIVA') return 'activa'
  if (estado === 'SIN_MEMBRESIA' || estado === 'INACTIVA' || estado === 'CANCELADA') {
    return 'inactiva'
  }
  if (estado === 'PENDIENTE' || estado === 'PAGO_VENCIDO') return 'pendiente'
  return 'desconocida'
})
const periodoActual = computed(() => {
  const inicio = formatearFecha(props.portal.membresia.periodoInicio)
  const fin = formatearFecha(props.portal.membresia.periodoFin)
  if (inicio && fin) return `${inicio} – ${fin}`
  return inicio ?? fin
})
const fechaSiguienteCobro = computed(() =>
  props.portal.membresia.cancelacionAlFinal
    ? null
    : formatearFecha(props.portal.membresia.siguienteCobroEn),
)
const fechaExpiracionCheckout = computed(() =>
  formatearFecha(props.portal.membresia.checkoutPendiente?.expiraEn ?? null),
)

/** Muestra las fechas según la hora de Ciudad de México, aunque el estacionamiento
 * tenga configurada otra zona.
 */
function formatearFecha(valor: string | null): string | null {
  if (!valor) return null
  const fecha = new Date(valor)
  if (Number.isNaN(fecha.getTime())) return null
  return new Intl.DateTimeFormat('es-MX', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'America/Mexico_City',
  }).format(fecha)
}
</script>

<template>
  <section
    v-if="seccion === 'cuenta'"
    class="panel-portal panel-cuenta"
    aria-labelledby="titulo-perfil"
  >
    <header class="encabezado-panel-portal">
      <div>
        <h2 id="titulo-perfil">Información personal</h2>
      </div>
    </header>
    <dl class="datos-perfil-cliente">
      <div>
        <dt>Nombre completo</dt>
        <dd>{{ nombreCompleto }}</dd>
      </div>
      <div>
        <dt>Correo electrónico</dt>
        <dd>{{ portal.cliente.correo }}</dd>
      </div>
    </dl>
  </section>

  <section
    v-else
    class="panel-portal panel-membresia"
    :data-estado-membresia="portal.membresia.estado"
    aria-labelledby="titulo-membresia"
  >
    <header class="encabezado-panel-portal">
      <div>
        <h2 id="titulo-membresia">Plan y facturación</h2>
      </div>
      <span class="estado-membresia" :class="`estado-membresia--${claseEstadoMembresia}`">
        <span class="indicador-estado-membresia" aria-hidden="true"></span>
        {{ etiquetaEstadoMembresia }}
      </span>
    </header>
    <div class="datos-plan-cliente">
      <div>
        <h3>{{ portal.membresia.plan.nombre }}</h3>
        <p>Precio</p>
      </div>
      <p class="precio-plan-cliente">{{ precioMembresia }}</p>
    </div>
    <dl
      v-if="periodoActual || fechaSiguienteCobro || portal.membresia.cancelacionAlFinal"
      class="datos-facturacion"
    >
      <div v-if="periodoActual">
        <dt>Periodo actual</dt>
        <dd>{{ periodoActual }}</dd>
      </div>
      <div v-if="fechaSiguienteCobro">
        <dt>Siguiente cobro</dt>
        <dd>{{ fechaSiguienteCobro }}</dd>
      </div>
      <div v-if="portal.membresia.cancelacionAlFinal">
        <dt>Cancelación</dt>
        <dd>Al finalizar el periodo actual</dd>
      </div>
    </dl>
    <div v-if="portal.membresia.checkoutPendiente" class="checkout-pendiente" role="status">
      <p>
        Tienes un Checkout pendiente. Puedes retomarlo
        <template v-if="fechaExpiracionCheckout">hasta el {{ fechaExpiracionCheckout }}</template
        >.
      </p>
    </div>
    <p
      v-if="!portal.membresia.puedeComprar && !portal.membresia.checkoutPendiente"
      class="compra-no-disponible"
    >
      La compra no está disponible con el estado actual de tu membresía.
    </p>
    <AccionCheckoutMembresia
      :puede-comprar="portal.membresia.puedeComprar"
      :checkout-pendiente="portal.membresia.checkoutPendiente"
    />
  </section>
</template>

<style scoped>
.panel-portal {
  border: 1px solid var(--app-border);
  border-radius: 15px;
  background: var(--app-surface);
  padding: clamp(20px, 3vw, 30px);
}
.encabezado-panel-portal,
.datos-plan-cliente {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}
.encabezado-panel-portal {
  align-items: flex-start;
}
.encabezado-panel-portal h2 {
  margin: 5px 0;
  font-size: 1.28rem;
  letter-spacing: -0.04em;
}
.sobrelinea-portal {
  margin: 0;
  color: var(--app-primary);
  font-size: 0.75rem;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.estado-membresia {
  display: inline-flex;
  min-height: 34px;
  align-items: center;
  gap: 7px;
  border-radius: 999px;
  padding: 5px 11px;
  font-size: 0.8rem;
  font-weight: 700;
  white-space: nowrap;
}
.estado-membresia {
  border: 1px solid color-mix(in srgb, var(--app-primary) 22%, var(--app-border));
  background: color-mix(in srgb, var(--app-primary) 7%, var(--app-surface));
  color: var(--app-primary);
}
.estado-membresia--activa {
  border-color: color-mix(in srgb, var(--app-success) 30%, var(--app-border));
  background: color-mix(in srgb, var(--app-success) 8%, var(--app-surface));
  color: var(--app-success);
}
.estado-membresia--inactiva {
  border-color: var(--app-border);
  background: color-mix(in srgb, var(--app-muted) 8%, var(--app-surface));
  color: var(--app-muted);
}
.estado-membresia--pendiente {
  border-color: color-mix(in srgb, var(--app-primary) 28%, var(--app-border));
  background: color-mix(in srgb, var(--app-primary) 8%, var(--app-surface));
  color: var(--app-primary);
}
.indicador-estado-membresia {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--app-primary);
}
.estado-membresia--activa .indicador-estado-membresia {
  background: var(--app-success);
}
.estado-membresia--inactiva .indicador-estado-membresia {
  background: var(--app-muted);
}
.datos-facturacion {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 28px;
  margin: 18px 0 0;
}
.datos-facturacion > div {
  min-width: 0;
}
.datos-facturacion dt {
  color: var(--app-muted);
  font-size: 0.83rem;
}
.datos-facturacion dd {
  margin: 4px 0 0;
  font-weight: 650;
}
.checkout-pendiente {
  margin-top: 18px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--app-primary) 7%, var(--app-surface));
  padding: 12px 14px;
  color: var(--app-foreground);
}
.checkout-pendiente p {
  margin: 0;
  font-size: 0.9rem;
  line-height: 1.5;
}
.compra-no-disponible {
  margin: 18px 0 0;
  color: var(--app-muted);
  font-size: 0.9rem;
}
.datos-perfil-cliente {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px 28px;
  margin: 22px 0 0;
}
.datos-perfil-cliente > div {
  min-width: 0;
  border-top: 1px solid var(--app-border);
  padding-top: 14px;
}
.datos-perfil-cliente dt,
.datos-plan-cliente p:first-of-type {
  color: var(--app-muted);
  font-size: 0.83rem;
}
.datos-perfil-cliente dd {
  margin: 5px 0 0;
  font-weight: 650;
  overflow-wrap: anywhere;
}
.datos-plan-cliente {
  margin-top: 22px;
  border-top: 1px solid var(--app-border);
  padding-top: 20px;
}
.datos-plan-cliente h3 {
  margin: 0;
  font-size: 1.05rem;
}
.datos-plan-cliente p:first-of-type {
  margin: 6px 0 0;
}
.precio-plan-cliente {
  margin: 0;
  color: var(--app-foreground);
  font-size: clamp(1.1rem, 2.5vw, 1.35rem);
  font-weight: 750;
  text-align: right;
  white-space: nowrap;
}
@media (max-width: 36rem) {
  .datos-perfil-cliente {
    grid-template-columns: minmax(0, 1fr);
  }
  .datos-plan-cliente {
    align-items: flex-start;
    flex-direction: column;
  }
  .precio-plan-cliente {
    text-align: left;
  }
}
</style>
