<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ResultadoPanel } from '~/composables/usePanelPropietario'

const { sesion, actualizar } = useSesion()
const { data: resultadoPanel } = useNuxtData<ResultadoPanel>('panel-dueno-web')
const panel = computed<ResultadoPanel>(
  () => resultadoPanel.value ?? { estado: 'fallo', sesionVencida: false },
)
const refrescandoPanel = ref(false)
const pendientePanel = computed(() => refrescandoPanel.value || !resultadoPanel.value)
const {
  datos: capacidad,
  pendiente: pendienteCapacidad,
  mensajeError: errorCapacidad,
  desactualizado: capacidadDesactualizada,
  actualizar: actualizarCapacidad,
} = await useCapacidadRfid()

const modalidadEstacionamiento = computed(() => {
  if (panel.value.estado !== 'listo') return ''

  const tipo = panel.value.datos.estacionamiento.tipo
  if (tipo === 'Mixto') return 'Clientes y empleados'
  if (tipo === 'Público') return 'Clientes'
  if (tipo === 'Privado') return 'Empleados'
  return tipo
})

const textoActualizar = computed(() => {
  if (pendienteCapacidad.value) return capacidad.value ? 'Actualizando…' : 'Cargando…'
  return errorCapacidad.value ? 'Reintentar' : 'Actualizar'
})

async function reintentarConfiguracion() {
  if (refrescandoPanel.value) return
  refrescandoPanel.value = true
  try {
    await refreshNuxtData('panel-dueno-web')
  } finally {
    refrescandoPanel.value = false
  }
}
</script>

<template>
  <section v-if="sesion.estado === 'error'" class="estado-error" role="alert">
    <p>No pudimos conectar con Smart Parking. Revisa tu conexión e inténtalo de nuevo.</p>
    <UButton variant="outline" @click="() => actualizar()">Reintentar</UButton>
  </section>
  <section
    v-else-if="sesion.estado === 'autenticada' && sesion.identidad.rol !== 'DUENO'"
    class="acceso-denegado"
    role="alert"
  >
    <UCard>
      <h2>Acceso no disponible</h2>
      <p>Esta sección está disponible solo para el propietario.</p>
    </UCard>
  </section>
  <div v-else-if="pendientePanel" class="contexto-inicio contexto-cargando" role="status">
    Cargando datos del estacionamiento…
  </div>
  <div v-else-if="panel.estado === 'listo'" class="contexto-inicio">
    <span v-if="panel.datos.estacionamiento.nombre">
      <strong>Estacionamiento:</strong> {{ panel.datos.estacionamiento.nombre }}
    </span>
    <span v-if="panel.datos.estacionamiento.horario">
      <strong>Horario:</strong> {{ panel.datos.estacionamiento.horario }}
    </span>
    <span v-if="modalidadEstacionamiento">
      <strong>Modalidad:</strong> {{ modalidadEstacionamiento }}
    </span>
  </div>
  <section v-else class="estado-configuracion" role="alert">
    <p>
      {{
        panel.estado === 'fallo' && panel.sesionVencida
          ? 'Tu acceso venció. Inicia sesión de nuevo.'
          : 'No pudimos cargar la información del estacionamiento. Revisa tu conexión e inténtalo de nuevo.'
      }}
    </p>
    <UButton variant="outline" :loading="refrescandoPanel" @click="reintentarConfiguracion">
      Reintentar
    </UButton>
  </section>

  <section
    v-if="sesion.estado === 'autenticada' && sesion.identidad.rol === 'DUENO'"
    class="estado-estacionamiento"
    aria-labelledby="titulo-estado-estacionamiento"
  >
    <header class="encabezado-estado-estacionamiento">
      <div>
        <h2 id="titulo-estado-estacionamiento">Estado del estacionamiento</h2>
        <p>Estimaciones basadas en accesos RFID registrados; no representan la ocupación física.</p>
      </div>
      <UButton
        type="button"
        color="neutral"
        variant="outline"
        icon="i-lucide-refresh-cw"
        :loading="pendienteCapacidad"
        :disabled="pendienteCapacidad"
        @click="actualizarCapacidad"
      >
        {{ textoActualizar }}
      </UButton>
    </header>

    <dl class="metricas-estacionamiento" aria-label="Indicadores de capacidad RFID">
      <div class="metrica-estacionamiento metrica-disponible">
        <dt>Libres estimados</dt>
        <dd>{{ capacidad?.capacidadDisponible ?? '—' }}</dd>
      </div>
      <div class="metrica-estacionamiento">
        <dt>Vehículos registrados dentro</dt>
        <dd>{{ capacidad?.vehiculosDentro ?? '—' }}</dd>
      </div>
      <div class="metrica-estacionamiento">
        <dt>Capacidad total</dt>
        <dd>{{ capacidad?.capacidadTotal ?? '—' }}</dd>
      </div>
    </dl>

    <p v-if="errorCapacidad" class="estado-capacidad estado-capacidad-error" role="alert">
      {{ errorCapacidad }}
    </p>
    <p v-else-if="capacidadDesactualizada" class="estado-capacidad" role="status">
      La información podría estar desactualizada. Se actualizará automáticamente.
    </p>
    <p v-else-if="pendienteCapacidad" class="estado-capacidad" role="status">
      {{ capacidad ? 'Actualizando la capacidad…' : 'Cargando la capacidad…' }}
    </p>
    <p v-else-if="!capacidad" class="estado-capacidad" role="status">
      La información de capacidad no está disponible todavía.
    </p>
  </section>
</template>

<style scoped>
.contexto-inicio {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 20px;
  margin: -12px 0 24px;
  color: var(--app-muted);
  font-size: 0.9rem;
  line-height: 1.5;
}

.contexto-inicio strong {
  color: var(--app-foreground);
  font-weight: 600;
}

.contexto-cargando {
  color: var(--app-muted);
}

.estado-configuracion {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
  margin-bottom: 24px;
  color: var(--app-error);
}

.estado-configuracion p {
  margin: 0;
}

.estado-estacionamiento {
  display: grid;
  width: 100%;
  gap: 20px;
  border: 1px solid var(--app-border);
  border-radius: 16px;
  padding: clamp(16px, 2.5vw, 24px);
  background: var(--app-surface);
  color: var(--app-foreground);
  box-shadow: 0 2px 8px rgb(41 37 47 / 4%);
}

.encabezado-estado-estacionamiento {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.encabezado-estado-estacionamiento h2 {
  margin: 0;
  color: var(--app-foreground);
  font-size: 1.25rem;
  font-weight: 600;
  letter-spacing: -0.025em;
}

.encabezado-estado-estacionamiento p {
  margin: 5px 0 0;
  color: var(--app-muted);
  line-height: 1.5;
}

.metricas-estacionamiento {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 0;
}

.metrica-estacionamiento {
  display: grid;
  min-width: 0;
  min-height: 112px;
  align-content: center;
  gap: 8px;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  padding: 16px;
  background: var(--app-surface);
}

.metrica-estacionamiento dt {
  color: var(--app-muted);
  font-size: 0.88rem;
  line-height: 1.4;
}

.metrica-estacionamiento dd {
  margin: 0;
  color: var(--app-foreground);
  font-size: 1.9rem;
  font-variant-numeric: tabular-nums;
  font-weight: 650;
  line-height: 1.1;
}

.metrica-disponible {
  border-color: var(--app-primary);
  background: var(--app-surface-hover);
}

.metrica-disponible dd {
  color: var(--app-primary);
  font-size: 2.2rem;
}

.estado-capacidad {
  margin: -4px 0 0;
  color: var(--app-muted);
  font-size: 0.88rem;
  line-height: 1.5;
}

.estado-capacidad-error {
  color: var(--app-error);
}

@media (max-width: 900px) {
  .metricas-estacionamiento {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .metrica-disponible {
    grid-column: 1 / -1;
  }
}

@media (max-width: 600px) {
  .contexto-inicio {
    display: grid;
    gap: 4px;
    margin-top: -16px;
  }

  .encabezado-estado-estacionamiento {
    align-items: flex-start;
    flex-direction: column;
  }

  .metricas-estacionamiento {
    grid-template-columns: minmax(0, 1fr);
  }

  .metrica-disponible {
    grid-column: auto;
  }

  .metrica-estacionamiento {
    min-height: 92px;
  }
}
</style>
