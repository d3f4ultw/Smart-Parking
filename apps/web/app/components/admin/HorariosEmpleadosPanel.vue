<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'

import {
  crearHorariosConfigurables,
  TURNO_SIN_RESTRICCION,
  TURNOS_CONFIGURABLES,
  validarHorariosConfigurables,
  type HorariosConfigurables,
  type RespuestaHorariosEmpleados,
} from '~/utils/horarios-empleados'
import { obtenerCodigoErrorHttp } from '~/utils/configuracion-estacionamiento'

const CLAVE_DATOS = 'admin-configuracion-horarios-empleados'
const fetchConCookies = useRequestFetch()
const guardando = ref(false)
const mensajeError = ref('')
const mensajeExito = ref('')
const horariosEditados = ref<HorariosConfigurables | null>(null)

type ResultadoCarga =
  | { tipo: 'exito'; configuracion: RespuestaHorariosEmpleados }
  | { tipo: 'error'; mensaje: string }

function mensajeErrorHorario(error: unknown): string {
  const codigo = obtenerCodigoErrorHttp(error)
  if (codigo === 401 || codigo === 403) {
    return 'La sesión del Dueño o sus permisos cambiaron. Vuelve a ingresar para continuar.'
  }
  if (codigo === 409) {
    return 'Los horarios cambiaron en otra sesión. Actualiza los datos antes de guardar.'
  }
  if (codigo === 422) {
    return 'Revisa los intervalos ingresados e intenta de nuevo.'
  }
  return 'No fue posible consultar o guardar los horarios. Inténtalo de nuevo.'
}

const carga = await useAsyncData<ResultadoCarga>(
  CLAVE_DATOS,
  async (_nuxtApp, { signal }) => {
    try {
      const configuracion = await fetchConCookies<RespuestaHorariosEmpleados>(
        '/api/admin/configuracion/horarios-empleados',
        {
          credentials: 'same-origin',
          cache: 'no-store',
          signal,
        },
      )
      return { tipo: 'exito', configuracion }
    } catch (error: unknown) {
      return { tipo: 'error', mensaje: mensajeErrorHorario(error) }
    }
  },
  { dedupe: 'defer' },
)

const configuracionActual = computed(() =>
  carga.data.value?.tipo === 'exito' ? carga.data.value.configuracion : null,
)
const horariosGuardados = computed(() => configuracionActual.value
  ? crearHorariosConfigurables(configuracionActual.value)
  : null)
const horarios = computed<HorariosConfigurables | null>({
  get: () => horariosEditados.value ?? horariosGuardados.value,
  set: (valor) => { horariosEditados.value = valor },
})
const errores = computed(() => horarios.value
  ? validarHorariosConfigurables(horarios.value)
  : {})
const tieneErrores = computed(() => Object.keys(errores.value).length > 0)
const hayCambios = computed(() => {
  if (horarios.value === null || horariosGuardados.value === null) {
    return false
  }
  return TURNOS_CONFIGURABLES.some(({ codigo }) =>
    horarios.value?.[codigo].hora_inicio !== horariosGuardados.value?.[codigo].hora_inicio
    || horarios.value?.[codigo].hora_fin !== horariosGuardados.value?.[codigo].hora_fin)
})
const puedeGuardar = computed(() =>
  horarios.value !== null
  && configuracionActual.value !== null
  && hayCambios.value
  && !tieneErrores.value
  && !guardando.value,
)

function actualizarHora(
  codigo: keyof HorariosConfigurables,
  campo: 'hora_inicio' | 'hora_fin',
  valor: string,
) {
  if (horarios.value === null) {
    return
  }
  const actual = horarios.value
  horariosEditados.value = {
    ...actual,
    [codigo]: {
      ...actual[codigo],
      [campo]: valor === '' ? null : valor,
    },
  }
  mensajeError.value = ''
  mensajeExito.value = ''
}

async function actualizarDatosAutoritativos(): Promise<boolean> {
  await carga.refresh()
  const resultado = carga.data.value
  if (resultado?.tipo !== 'exito') {
    mensajeError.value = resultado?.tipo === 'error'
      ? resultado.mensaje
      : 'No fue posible actualizar los horarios guardados.'
    return false
  }

  horariosEditados.value = null
  return true
}

async function guardarHorarios() {
  const datos = configuracionActual.value
  const valores = horarios.value
  if (!puedeGuardar.value || datos === null || valores === null) {
    return
  }

  guardando.value = true
  mensajeError.value = ''
  mensajeExito.value = ''
  try {
    const actualizados = await fetchConCookies<RespuestaHorariosEmpleados>(
      '/api/admin/configuracion/horarios-empleados',
      {
        method: 'PUT',
        credentials: 'same-origin',
        cache: 'no-store',
        body: {
          revision_esperada: datos.revision,
          turnos: {
            MATUTINO: valores.MATUTINO,
            VESPERTINO: valores.VESPERTINO,
            NOCTURNO: valores.NOCTURNO,
          },
        },
      },
    )
    carga.data.value = { tipo: 'exito', configuracion: actualizados }
    horariosEditados.value = null
    mensajeExito.value = 'Los horarios compartidos quedaron guardados.'
  } catch (error: unknown) {
    if (obtenerCodigoErrorHttp(error) === 409) {
      const actualizado = await actualizarDatosAutoritativos()
      mensajeError.value = actualizado
        ? 'Otro cambio guardó primero. Se actualizaron los horarios; revísalos antes de continuar.'
        : 'Los horarios cambiaron en otra sesión. Actualiza la página antes de volver a intentarlo.'
    } else {
      mensajeError.value = mensajeErrorHorario(error)
    }
  } finally {
    guardando.value = false
  }
}

onBeforeUnmount(() => {
  clearNuxtData(CLAVE_DATOS)
})
</script>

<template>
  <section class="schedule-panel" aria-labelledby="employee-schedule-title">
    <div class="panel-heading">
      <div>
        <p class="eyebrow">Dueño · Acceso de empleados</p>
        <h2 id="employee-schedule-title">Horarios de empleados</h2>
      </div>
      <p v-if="configuracionActual" class="timezone-badge">
        Zona horaria: {{ configuracionActual.zona_horaria }}
      </p>
    </div>

    <p class="intro-copy">
      Configura los turnos compartidos que podrán asignarse a los empleados.
      Los cambios se aplican a todas las asignaciones de cada turno.
    </p>

    <p v-if="carga.status.value === 'pending'" class="feedback" role="status" aria-live="polite">
      Cargando los horarios guardados…
    </p>
    <p v-else-if="carga.data.value?.tipo === 'error'" class="feedback feedback--error" role="alert">
      {{ carga.data.value.mensaje }}
    </p>

    <div v-if="horarios" class="schedule-list">
      <fieldset
        v-for="turno in TURNOS_CONFIGURABLES"
        :key="turno.codigo"
        class="schedule-row"
        :disabled="guardando"
        :aria-describedby="`schedule-help-${turno.codigo}`"
      >
        <legend>{{ turno.etiqueta }}</legend>
        <label class="time-field">
          <span>Inicio</span>
          <input
            type="time"
            step="60"
            :value="horarios[turno.codigo].hora_inicio ?? ''"
            :aria-invalid="Boolean(errores[turno.codigo])"
            :aria-describedby="`schedule-error-${turno.codigo}`"
            @input="actualizarHora(turno.codigo, 'hora_inicio', ($event.target as HTMLInputElement).value)"
          >
        </label>
        <label class="time-field">
          <span>Fin</span>
          <input
            type="time"
            step="60"
            :value="horarios[turno.codigo].hora_fin ?? ''"
            :aria-invalid="Boolean(errores[turno.codigo])"
            :aria-describedby="`schedule-error-${turno.codigo}`"
            @input="actualizarHora(turno.codigo, 'hora_fin', ($event.target as HTMLInputElement).value)"
          >
        </label>
        <p
          :id="`schedule-help-${turno.codigo}`"
          class="schedule-help"
        >
          Si el turno termina al día siguiente, escribe las horas normalmente. Ejemplo: inicia a las 10:00 p. m. y termina a las 6:00 a. m.
        </p>
        <p
          :id="`schedule-error-${turno.codigo}`"
          class="field-error"
          aria-live="polite"
        >
          {{ errores[turno.codigo] ?? '' }}
        </p>
      </fieldset>

      <div class="unrestricted-row" aria-label="Turno sin restricción, fijo y no editable">
        <div>
          <strong>{{ TURNO_SIN_RESTRICCION.etiqueta }}</strong>
          <p>Permanece disponible y no requiere horas.</p>
        </div>
        <span class="fixed-badge">Fijo</span>
      </div>
    </div>

    <p class="boundary-note">
      Si un turno configurable queda sin horas, no autoriza el acceso mientras no se configure.
    </p>

    <div class="form-footer">
      <div class="form-messages" aria-live="polite">
        <p v-if="mensajeError" class="feedback feedback--error" role="alert">
          {{ mensajeError }}
        </p>
        <p v-else-if="mensajeExito" class="feedback feedback--success" role="status">
          {{ mensajeExito }}
        </p>
      </div>
      <button
        class="primary-button"
        type="button"
        :disabled="!puedeGuardar"
        :aria-busy="guardando"
        @click="guardarHorarios"
      >
        {{ guardando ? 'Guardando…' : 'Guardar horarios' }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.schedule-panel {
  display: grid;
  gap: 1.1rem;
  min-width: 0;
  padding: clamp(1.1rem, 2.5vw, 1.8rem);
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 1rem;
  box-shadow: 0 0.75rem 2rem rgb(37 28 47 / 4%);
}

.panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.eyebrow {
  margin: 0 0 0.45rem;
  color: #6b4a89;
  font-size: 0.7rem;
  font-weight: 750;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h2 {
  margin: 0;
  color: #29252f;
  font-size: 1.12rem;
  letter-spacing: -0.035em;
  line-height: 1.35;
}

.intro-copy,
.boundary-note {
  margin: 0;
  color: #746f7b;
  font-size: 0.9rem;
  line-height: 1.55;
}

.timezone-badge,
.fixed-badge {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  padding: 0.45rem 0.7rem;
  color: #5c3a86;
  font-size: 0.76rem;
  font-weight: 700;
  background: #f7f3fa;
  border: 1px solid #e8e0ef;
  border-radius: 999px;
}

.schedule-list {
  display: grid;
  gap: 0.8rem;
}

.schedule-row {
  display: grid;
  grid-template-columns: minmax(8rem, 1fr) repeat(2, minmax(8rem, 0.7fr));
  align-items: end;
  gap: 0.8rem;
  min-width: 0;
  margin: 0;
  padding: 0.95rem;
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 0.75rem;
}

.schedule-row legend {
  grid-column: 1 / -1;
  padding: 0;
  color: #29252f;
  font-size: 0.92rem;
  font-weight: 700;
}

.time-field {
  display: grid;
  gap: 0.35rem;
  color: #625d68;
  font-size: 0.8rem;
  font-weight: 650;
}

.time-field input {
  min-height: 2.65rem;
  min-width: 0;
  padding: 0.5rem 0.65rem;
  color: #29252f;
  font: inherit;
  font-size: 0.95rem;
  background: #ffffff;
  border: 1px solid #d9d5de;
  border-radius: 0.55rem;
}

.time-field input:focus-visible {
  outline: 3px solid rgb(92 58 134 / 22%);
  outline-offset: 1px;
  border-color: #7955a0;
}

.time-field input[aria-invalid='true'] {
  border-color: #a12636;
}

.schedule-help,
.field-error {
  grid-column: 1 / -1;
  margin: 0;
  font-size: 0.78rem;
  line-height: 1.45;
}

.schedule-help {
  margin-top: 0.1rem;
  color: #746f7b;
}

.field-error {
  color: #a12636;
}

.unrestricted-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.9rem 1rem;
  background: #f7f3fa;
  border: 1px solid #e8e0ef;
  border-radius: 0.75rem;
}

.unrestricted-row strong {
  color: #29252f;
  font-size: 0.9rem;
}

.unrestricted-row p {
  margin: 0.2rem 0 0;
  color: #746f7b;
  font-size: 0.8rem;
}

.form-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding-top: 0.25rem;
  border-top: 1px solid #efedf1;
}

.form-messages {
  min-width: 0;
}

.feedback {
  margin: 0;
  color: #625d68;
  font-size: 0.88rem;
  line-height: 1.5;
}

.feedback--error {
  color: #a12636;
}

.feedback--success {
  color: #246b43;
}

.primary-button {
  display: inline-flex;
  min-height: 2.75rem;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  padding: 0.65rem 1rem;
  color: #ffffff;
  font: inherit;
  font-size: 0.88rem;
  font-weight: 700;
  background: #5c3a86;
  border: 1px solid #5c3a86;
  border-radius: 0.65rem;
  cursor: pointer;
}

.primary-button:disabled {
  background: #a79aaf;
  border-color: #a79aaf;
  cursor: not-allowed;
}

.primary-button:focus-visible {
  outline: 3px solid rgb(92 58 134 / 25%);
  outline-offset: 2px;
}

@media (max-width: 650px) {
  .panel-heading,
  .form-footer {
    align-items: stretch;
    flex-direction: column;
  }

  .timezone-badge {
    align-self: flex-start;
  }

  .schedule-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .schedule-row legend {
    grid-column: 1 / -1;
  }

  .primary-button {
    width: 100%;
  }
}
</style>
