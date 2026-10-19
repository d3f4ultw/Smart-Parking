<script setup lang="ts">
import { computed, ref } from 'vue'

import {
  construirCapacidadesEmpleados,
  construirNombreCompletoEmpleado,
  construirSolicitudRegistrarEmpleado,
  mapearErrorEmpleados,
  obtenerEstadoErrorEmpleado,
  obtenerPaginaSolicitadaEmpleados,
  validarDatosEmpleado,
  type CapacidadesEmpleados,
  type DatosFormularioEmpleado,
  type Empleado,
  type ErroresFormularioEmpleado,
  type RespuestaListaEmpleados,
} from '~/utils/empleados'

definePageMeta({
  layout: 'admin',
  middleware: 'sesion-owner-operadores',
})

type ResultadoCarga =
  | { tipo: 'exito'; lista: RespuestaListaEmpleados }
  | { tipo: 'error'; codigo: number | undefined; mensaje: string }

const CLAVE_LISTA_EMPLEADOS = 'admin-empleados-lista'
const route = useRoute()
const router = useRouter()
const { listarEmpleados, registrarEmpleado, cambiarEstadoEmpleado } = useEmpleados()
const { usuario, limpiarSesion } = useSesion()
const { mostrarToast } = useAdminToasts()
const dialogoRegistro = ref<HTMLDialogElement | null>(null)
const dialogoEstado = ref<HTMLDialogElement | null>(null)
const botonAbrirRegistro = ref<HTMLButtonElement | null>(null)
const empleadoPendiente = ref<Empleado | null>(null)
const estadoSolicitado = ref<boolean | null>(null)
const registrando = ref(false)
const actualizandoEstado = ref(false)
const erroresFormulario = ref<ErroresFormularioEmpleado>({})
const mensajeErrorRegistro = ref('')
const mensajeErrorEstado = ref('')
const claveIdempotencia = ref<string | null>(null)
const huellaClaveIdempotencia = ref<string | null>(null)
const paginaSolicitada = computed(() =>
  obtenerPaginaSolicitadaEmpleados(route.query.pagina),
)
const capacidades = computed<CapacidadesEmpleados>(() =>
  construirCapacidadesEmpleados(usuario.value?.rol),
)

const formulario = ref<DatosFormularioEmpleado>({
  nombres: '',
  apellido_paterno: '',
  apellido_materno: '',
  turno_empleado_id: '',
})

function listaVacia(): RespuestaListaEmpleados {
  return {
    empleados: [],
    pagina: 1,
    tamano_pagina: 10,
    total: 0,
    total_paginas: 0,
    turnos_disponibles: [],
  }
}

const carga = await useAsyncData<ResultadoCarga>(
  CLAVE_LISTA_EMPLEADOS,
  async (_nuxtApp, { signal }): Promise<ResultadoCarga> => {
    try {
      return {
        tipo: 'exito',
        lista: await listarEmpleados(paginaSolicitada.value, signal),
      }
    } catch (error: unknown) {
      const codigo = obtenerEstadoErrorEmpleado(error)
      return {
        tipo: 'error',
        codigo,
        mensaje: mapearErrorEmpleados(codigo, 'leer'),
      }
    }
  },
  {
    default: (): ResultadoCarga => ({ tipo: 'exito', lista: listaVacia() }),
    dedupe: 'cancel',
    watch: [paginaSolicitada],
  },
)

const lista = computed(() =>
  carga.data.value?.tipo === 'exito' ? carga.data.value.lista : listaVacia(),
)
const mensajeErrorCarga = computed(() =>
  carga.data.value?.tipo === 'error' ? carga.data.value.mensaje : '',
)
const paginaActual = computed(() => lista.value.pagina)
const paginasVisibles = computed(() => Math.max(1, lista.value.total_paginas))
const nombreEmpleadoPendiente = computed(() =>
  empleadoPendiente.value === null
    ? ''
    : construirNombreCompletoEmpleado(empleadoPendiente.value),
)
const etiquetaConfirmacionEstado = computed(() =>
  estadoSolicitado.value ? 'Activar empleado' : 'Desactivar empleado',
)
const textoConfirmacionEstado = computed(() => {
  if (actualizandoEstado.value) {
    return estadoSolicitado.value ? 'Activando…' : 'Desactivando…'
  }
  return 'Confirmar'
})

function actualizarLista(listaActualizada: RespuestaListaEmpleados) {
  carga.data.value = { tipo: 'exito', lista: listaActualizada }
}

async function redirigirSesionInvalida(error: unknown): Promise<boolean> {
  if (obtenerEstadoErrorEmpleado(error) !== 401) {
    return false
  }

  limpiarSesion()
  clearNuxtData()
  await navigateTo('/login', { replace: true })
  return true
}

async function actualizarListaAutoritativa(): Promise<boolean> {
  await carga.refresh()
  return carga.data.value?.tipo === 'exito'
}

function crearClaveParaSolicitud(solicitud: ReturnType<typeof construirSolicitudRegistrarEmpleado>) {
  const huella = JSON.stringify(solicitud)
  if (claveIdempotencia.value === null || huellaClaveIdempotencia.value !== huella) {
    claveIdempotencia.value = crypto.randomUUID()
    huellaClaveIdempotencia.value = huella
  }
  return claveIdempotencia.value
}

function limpiarClaveIdempotencia() {
  claveIdempotencia.value = null
  huellaClaveIdempotencia.value = null
}

function limpiarFormulario() {
  formulario.value = {
    nombres: '',
    apellido_paterno: '',
    apellido_materno: '',
    turno_empleado_id: lista.value.turnos_disponibles[0]?.id ?? '',
  }
  erroresFormulario.value = {}
  mensajeErrorRegistro.value = ''
}

function abrirDialogoRegistro() {
  if (!capacidades.value.registrar || registrando.value || carga.pending.value) {
    return
  }

  limpiarFormulario()
  dialogoRegistro.value?.showModal()
}

function cerrarDialogoRegistro() {
  if (registrando.value) {
    return
  }

  dialogoRegistro.value?.close()
}

function evitarCierreDuranteRegistro(event: Event) {
  if (registrando.value) {
    event.preventDefault()
  }
}

function alCerrarDialogoRegistro() {
  if (!registrando.value) {
    limpiarFormulario()
  }
  botonAbrirRegistro.value?.focus()
}

async function registrar() {
  if (!capacidades.value.registrar || registrando.value) {
    return
  }

  const errores = validarDatosEmpleado(formulario.value)
  erroresFormulario.value = errores
  if (Object.keys(errores).length > 0) {
    mensajeErrorRegistro.value = 'Revisa los campos marcados antes de continuar.'
    return
  }

  const solicitud = construirSolicitudRegistrarEmpleado(formulario.value)
  const clave = crearClaveParaSolicitud(solicitud)
  registrando.value = true
  mensajeErrorRegistro.value = ''

  try {
    const resultado = await registrarEmpleado(solicitud, clave)
    limpiarClaveIdempotencia()
    limpiarFormulario()
    dialogoRegistro.value?.close()

    if (resultado.status === 201) {
      mostrarToast(`Empleado ${resultado.empleado.codigo_empleado} registrado como Activo.`)
    } else {
      mostrarToast(`El registro ya existía. Código de empleado: ${resultado.empleado.codigo_empleado}.`)
    }

    await actualizarListaAutoritativa()
    const listaActualizada = carga.data.value
    if (
      resultado.status === 201
      && listaActualizada?.tipo === 'exito'
      && listaActualizada.lista.total_paginas > listaActualizada.lista.pagina
    ) {
      const ultimaPagina = listaActualizada.lista.total_paginas
      await router.push({
        path: '/admin/empleados',
        query: { pagina: String(ultimaPagina) },
      })
    }
  } catch (error: unknown) {
    if (await redirigirSesionInvalida(error)) {
      return
    }

    if (obtenerEstadoErrorEmpleado(error) === 409) {
      const actualizada = await actualizarListaAutoritativa()
      if (actualizada) {
        limpiarClaveIdempotencia()
        mensajeErrorRegistro.value =
          'La clave de registro ya se usó con otros datos. Verifica el formulario e inténtalo de nuevo.'
      }
    } else {
      mensajeErrorRegistro.value = mapearErrorEmpleados(
        obtenerEstadoErrorEmpleado(error),
        'registrar',
      )
    }
  } finally {
    registrando.value = false
  }
}

function cambiarPagina(pagina: number) {
  const limite = Math.max(1, lista.value.total_paginas)
  const paginaSegura = Math.min(Math.max(1, pagina), limite)
  return router.push({
    path: '/admin/empleados',
    query: paginaSegura > 1 ? { pagina: String(paginaSegura) } : {},
  })
}

function solicitarCambioEstado(empleado: Empleado) {
  if (!capacidades.value.cambiar_estado || actualizandoEstado.value) {
    return
  }

  empleadoPendiente.value = empleado
  estadoSolicitado.value = !empleado.esta_activo
  mensajeErrorEstado.value = ''
  dialogoEstado.value?.showModal()
}

function cerrarDialogoEstado() {
  if (actualizandoEstado.value) {
    return
  }
  empleadoPendiente.value = null
  estadoSolicitado.value = null
  mensajeErrorEstado.value = ''
}

function cerrarDialogoEstadoDesdeFondo() {
  if (actualizandoEstado.value) {
    return
  }
  dialogoEstado.value?.close()
}

function guardarEmpleadoActualizado(empleadoActualizado: Empleado) {
  if (carga.data.value?.tipo !== 'exito') {
    return
  }

  const empleados = carga.data.value.lista.empleados.map((empleado) =>
    empleado.id === empleadoActualizado.id ? empleadoActualizado : empleado,
  )
  actualizarLista({ ...carga.data.value.lista, empleados })
}

async function confirmarCambioEstado() {
  const empleado = empleadoPendiente.value
  const activo = estadoSolicitado.value
  if (
    empleado === null
    || activo === null
    || !capacidades.value.cambiar_estado
    || actualizandoEstado.value
  ) {
    return
  }

  actualizandoEstado.value = true
  mensajeErrorEstado.value = ''
  let cerrarTrasRespuesta = false
  try {
    const actualizado = await cambiarEstadoEmpleado(empleado.id, {
      esta_activo: activo,
      revision_esperada: empleado.revision_estado,
    })
    guardarEmpleadoActualizado(actualizado)
    mostrarToast(`Empleado ${actualizado.codigo_empleado}: ${actualizado.esta_activo ? 'Activo' : 'Inactivo'}.`)
    cerrarTrasRespuesta = true
  } catch (error: unknown) {
    if (await redirigirSesionInvalida(error)) {
      return
    }

    if (obtenerEstadoErrorEmpleado(error) === 409) {
      const actualizada = await actualizarListaAutoritativa()
      mensajeErrorEstado.value = actualizada
        ? 'El estado cambió en otra sesión. La lista se actualizó; revisa el estado actual.'
        : carga.data.value?.tipo === 'error'
          ? carga.data.value.mensaje
          : mapearErrorEmpleados(409, 'cambiar_estado')
    } else {
      mensajeErrorEstado.value = mapearErrorEmpleados(
        obtenerEstadoErrorEmpleado(error),
        'cambiar_estado',
      )
    }
  } finally {
    actualizandoEstado.value = false
    if (cerrarTrasRespuesta) {
      dialogoEstado.value?.close()
    }
  }
}

if (carga.data.value?.tipo === 'error' && carga.data.value.codigo === 401) {
  limpiarSesion()
  clearNuxtData()
  await navigateTo('/login', { replace: true })
}
</script>

<template>
  <div class="employees-page">
    <header class="page-heading">
      <div>
        <p class="page-eyebrow">Smart Parking · Administración</p>
        <h1>Administrar empleados</h1>
        <p class="page-description">
          Gestiona el personal, sus turnos y estados.
        </p>
      </div>
      <button
        v-if="capacidades.registrar"
        ref="botonAbrirRegistro"
        class="button-primary create-button"
        type="button"
        :disabled="carga.pending.value"
        @click="abrirDialogoRegistro"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
          <path d="M12 5v14M5 12h14" />
        </svg>
        Registrar empleado
      </button>
    </header>

    <p v-if="carga.pending.value" class="loading-message" role="status" aria-live="polite">
      Cargando empleados…
    </p>

    <section
      v-if="mensajeErrorCarga"
      class="notice notice-error"
      role="alert"
    >
      <span>{{ mensajeErrorCarga }}</span>
      <button class="button-secondary" type="button" @click="carga.refresh()">
        Intentar de nuevo
      </button>
    </section>

    <div v-if="capacidades.leer && !mensajeErrorCarga">
      <section class="panel directory-panel" aria-labelledby="employee-list-title" :aria-busy="carga.pending.value">
        <div class="panel-heading directory-heading">
          <div>
            <h2 id="employee-list-title">Empleados registrados</h2>
          </div>
        </div>
        <p class="panel-copy">
          {{ lista.total }} {{ lista.total === 1 ? 'empleado' : 'empleados' }} ·
          Página {{ paginaActual }} de {{ paginasVisibles }}
        </p>

        <p v-if="mensajeErrorEstado" class="notice notice-error" role="alert">
          {{ mensajeErrorEstado }}
        </p>

        <p v-if="carga.pending.value && lista.empleados.length === 0" class="inline-status" role="status">
          Cargando directorio…
        </p>

        <div v-else-if="lista.empleados.length === 0" class="empty-state">
          <span class="empty-icon" aria-hidden="true">E</span>
          <h3>Aún no hay empleados</h3>
        </div>

        <div v-else class="table-scroll" tabindex="0" aria-label="Tabla desplazable de empleados">
          <table class="employees-table">
            <thead>
              <tr>
                <th scope="col">Código</th>
                <th scope="col">Nombre completo</th>
                <th scope="col">Turno</th>
                <th scope="col">Estado</th>
                <th v-if="capacidades.cambiar_estado" class="action-header" scope="col">Acciones</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="empleado in lista.empleados" :key="empleado.id">
                <td class="employee-id">{{ empleado.codigo_empleado }}</td>
                <td class="employee-name">{{ construirNombreCompletoEmpleado(empleado) }}</td>
                <td>{{ empleado.turno.nombre }}</td>
                <td>
                  <span
                    class="status-badge"
                    :class="empleado.esta_activo ? 'status-active' : 'status-inactive'"
                  >
                    {{ empleado.esta_activo ? 'Activo' : 'Inactivo' }}
                  </span>
                </td>
                <td v-if="capacidades.cambiar_estado" class="action-cell">
                  <button
                    class="button-secondary button-row-action"
                    type="button"
                    :disabled="actualizandoEstado || carga.pending.value"
                    :aria-label="`${empleado.esta_activo ? 'Desactivar' : 'Activar'} a ${construirNombreCompletoEmpleado(empleado)}`"
                    @click="solicitarCambioEstado(empleado)"
                  >
                    {{ empleado.esta_activo ? 'Desactivar' : 'Activar' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <nav
          v-if="lista.total_paginas > 1"
          class="pagination-footer"
          aria-label="Paginación de empleados"
        >
          <div class="pagination-actions">
            <button
              class="button-secondary"
              type="button"
              :disabled="carga.pending.value || paginaActual <= 1"
              @click="cambiarPagina(paginaActual - 1)"
            >
              Anterior
            </button>
            <button
              class="button-secondary"
              type="button"
              :disabled="carga.pending.value || paginaActual >= lista.total_paginas"
              @click="cambiarPagina(paginaActual + 1)"
            >
              Siguiente
            </button>
          </div>
        </nav>
      </section>
    </div>

    <dialog
      v-if="capacidades.registrar"
      ref="dialogoRegistro"
      class="employee-dialog"
      aria-labelledby="employee-create-title"
      @close="alCerrarDialogoRegistro"
      @cancel="evitarCierreDuranteRegistro"
      @click.self="cerrarDialogoRegistro"
    >
      <header class="dialog-header">
        <div>
          <h2 id="employee-create-title">Registrar empleado</h2>
        </div>
        <button
          class="dialog-close"
          type="button"
          aria-label="Cerrar registro de empleado"
          :disabled="registrando"
          @click="cerrarDialogoRegistro"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
            <path d="m6 6 12 12M18 6 6 18" />
          </svg>
        </button>
      </header>

      <form class="employee-form" novalidate @submit.prevent="registrar">
        <div class="field-group">
          <label for="empleado-nombres">Nombres</label>
          <input
            id="empleado-nombres"
            v-model="formulario.nombres"
            type="text"
            maxlength="100"
            autocomplete="given-name"
            required
            autofocus
            :aria-invalid="Boolean(erroresFormulario.nombres)"
            :aria-describedby="erroresFormulario.nombres ? 'empleado-nombres-error' : undefined"
            :disabled="registrando"
          >
          <p v-if="erroresFormulario.nombres" id="empleado-nombres-error" class="field-error">
            {{ erroresFormulario.nombres }}
          </p>
        </div>

        <div class="field-group">
          <label for="empleado-apellido-paterno">Apellido paterno</label>
          <input
            id="empleado-apellido-paterno"
            v-model="formulario.apellido_paterno"
            type="text"
            maxlength="100"
            autocomplete="family-name"
            required
            :aria-invalid="Boolean(erroresFormulario.apellido_paterno)"
            :aria-describedby="erroresFormulario.apellido_paterno ? 'empleado-apellido-paterno-error' : undefined"
            :disabled="registrando"
          >
          <p v-if="erroresFormulario.apellido_paterno" id="empleado-apellido-paterno-error" class="field-error">
            {{ erroresFormulario.apellido_paterno }}
          </p>
        </div>

        <div class="field-group">
          <label for="empleado-apellido-materno">
            Apellido materno <span class="optional-label">Opcional</span>
          </label>
          <input
            id="empleado-apellido-materno"
            v-model="formulario.apellido_materno"
            type="text"
            maxlength="100"
            :aria-invalid="Boolean(erroresFormulario.apellido_materno)"
            :aria-describedby="erroresFormulario.apellido_materno ? 'empleado-apellido-materno-error' : undefined"
            :disabled="registrando"
          >
          <p v-if="erroresFormulario.apellido_materno" id="empleado-apellido-materno-error" class="field-error">
            {{ erroresFormulario.apellido_materno }}
          </p>
        </div>

        <div class="field-group">
          <label for="empleado-turno">Turno asignado</label>
          <select
            id="empleado-turno"
            v-model="formulario.turno_empleado_id"
            required
            :aria-invalid="Boolean(erroresFormulario.turno_empleado_id)"
            :aria-describedby="erroresFormulario.turno_empleado_id ? 'empleado-turno-error' : undefined"
            :disabled="registrando || carga.pending.value || lista.turnos_disponibles.length === 0"
          >
            <option value="" disabled>Selecciona un turno</option>
            <option
              v-for="turno in lista.turnos_disponibles"
              :key="turno.id"
              :value="turno.id"
            >
              {{ turno.nombre }}
            </option>
          </select>
          <p v-if="erroresFormulario.turno_empleado_id" id="empleado-turno-error" class="field-error">
            {{ erroresFormulario.turno_empleado_id }}
          </p>
        </div>

        <p v-if="mensajeErrorRegistro" class="notice notice-error form-notice" role="alert">
          {{ mensajeErrorRegistro }}
        </p>

        <footer class="form-footer">
          <div class="form-actions">
            <button
              class="button-secondary"
              type="button"
              :disabled="registrando"
              @click="cerrarDialogoRegistro"
            >
              Cancelar
            </button>
            <button
              class="button-primary"
              type="submit"
              :disabled="registrando || carga.pending.value || lista.turnos_disponibles.length === 0"
            >
              {{ registrando ? 'Registrando…' : 'Registrar empleado' }}
            </button>
          </div>
        </footer>
      </form>
    </dialog>

    <dialog
      ref="dialogoEstado"
      class="confirm-dialog"
      aria-labelledby="employee-state-title"
      @close="cerrarDialogoEstado"
      @click.self="cerrarDialogoEstadoDesdeFondo"
    >
      <form method="dialog" class="dialog-close-form">
        <button class="dialog-close" type="submit" aria-label="Cerrar confirmación" :disabled="actualizandoEstado">
          ×
        </button>
      </form>
      <div class="dialog-content">
        <h2 id="employee-state-title">{{ etiquetaConfirmacionEstado }}</h2>
        <p>
          {{ estadoSolicitado
            ? `El empleado ${nombreEmpleadoPendiente} volverá a estar disponible en el directorio.`
            : `El empleado ${nombreEmpleadoPendiente} permanecerá en el directorio como Inactivo.` }}
        </p>
        <p v-if="mensajeErrorEstado" class="notice notice-error" role="alert">
          {{ mensajeErrorEstado }}
        </p>
        <div class="dialog-actions">
          <button
            class="button-secondary"
            type="button"
            :disabled="actualizandoEstado"
            @click="dialogoEstado?.close()"
          >
            Cancelar
          </button>
          <button
            class="button-primary"
            type="button"
            :disabled="actualizandoEstado"
            @click="confirmarCambioEstado"
          >
            {{ textoConfirmacionEstado }}
          </button>
        </div>
      </div>
    </dialog>
  </div>
</template>

<style scoped>
.employees-page {
  display: grid;
  min-width: 0;
  gap: 1.25rem;
  color: #29252f;
}

.page-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.4rem;
}

.page-eyebrow,
.panel-kicker {
  margin: 0 0 0.45rem;
  color: #776e80;
  font-size: 0.68rem;
  font-weight: 750;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.page-heading h1 {
  margin: 0;
  color: #29252f;
  font-size: clamp(1.65rem, 3vw, 2.15rem);
  font-weight: 700;
  letter-spacing: -0.035em;
  line-height: 1.2;
}

.page-description {
  margin: 0.55rem 0 0;
  color: #746f7b;
  font-size: 0.92rem;
  line-height: 1.55;
}

.create-button {
  gap: 0.55rem;
  font-size: 0.84rem;
}

.create-button svg {
  width: 1.05rem;
  height: 1.05rem;
}

.panel {
  min-width: 0;
  padding: clamp(1rem, 2.5vw, 1.5rem);
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 1rem;
  box-shadow: 0 0.75rem 2rem rgb(37 28 47 / 4%);
}

.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.panel-heading h2 {
  margin: 0;
  color: #29252f;
  font-size: 1rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.panel-copy {
  margin: 0 0 0.85rem;
  color: #827c89;
  font-size: 0.78rem;
  text-align: center;
}

.field-group {
  display: grid;
  min-width: 0;
  align-content: start;
  gap: 0.45rem;
}

.field-group label {
  color: #433c4b;
  font-size: 0.82rem;
  font-weight: 650;
}

.field-group input,
.field-group select {
  width: 100%;
  min-height: 2.8rem;
  padding: 0.65rem 0.75rem;
  color: #29252f;
  background: #fdfcfe;
  border: 1px solid #ded9e3;
  border-radius: 0.6rem;
  font: inherit;
  font-size: 0.9rem;
}

.field-group input:focus-visible,
.field-group select:focus-visible {
  border-color: #76579a;
  outline: 3px solid rgb(92 58 134 / 17%);
  outline-offset: 1px;
}

.field-group input[aria-invalid='true'],
.field-group select[aria-invalid='true'] {
  border-color: #b44e56;
}

.field-group input:disabled,
.field-group select:disabled {
  color: #77717e;
  background: #f5f3f6;
}

.optional-label {
  color: #817b88;
  font-size: 0.74rem;
  font-weight: 450;
}

.field-error {
  margin: 0;
  color: #9f353e;
  font-size: 0.76rem;
  line-height: 1.4;
}

.form-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  grid-column: 1 / -1;
  margin-top: 0.25rem;
  padding-top: 1rem;
  border-top: 1px solid #eeeaf1;
}

.form-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.65rem;
}

.button-primary,
.button-secondary {
  display: inline-flex;
  min-height: 2.65rem;
  align-items: center;
  justify-content: center;
  gap: 0.55rem;
  padding: 0.6rem 0.9rem;
  border: 1px solid transparent;
  border-radius: 0.65rem;
  font: inherit;
  font-size: 0.82rem;
  font-weight: 650;
  cursor: pointer;
  transition: background-color 140ms ease, border-color 140ms ease, color 140ms ease;
}

.button-primary {
  color: #ffffff;
  background: #5c3a86;
  border-color: #5c3a86;
}

.button-primary:hover:not(:disabled) {
  background: #6c4a97;
  border-color: #6c4a97;
}

.button-secondary {
  color: #4a4252;
  background: #ffffff;
  border-color: #dcd7e1;
}

.button-secondary:hover:not(:disabled) {
  color: #3b2b4b;
  background: #f8f6fa;
  border-color: #c8bdd4;
}

.button-primary:focus-visible,
.button-secondary:focus-visible,
.dialog-close:focus-visible {
  outline: 3px solid rgb(92 58 134 / 24%);
  outline-offset: 2px;
}

.button-primary:disabled,
.button-secondary:disabled {
  cursor: not-allowed;
  opacity: 0.56;
}

.directory-panel {
  min-width: 0;
}

.directory-heading {
  align-items: flex-start;
  margin-bottom: 1.1rem;
}

.table-scroll {
  width: 100%;
  overflow-x: auto;
  border: 1px solid #ece9ef;
  border-radius: 0.7rem;
}

.table-scroll:focus-visible {
  outline: 3px solid rgb(92 58 134 / 20%);
  outline-offset: 2px;
}

.employees-table {
  width: 100%;
  min-width: 46rem;
  table-layout: fixed;
  border-collapse: collapse;
  text-align: left;
}

.employees-table th {
  padding: 0.85rem 1rem;
  color: #746f7b;
  background: #faf9fb;
  border-bottom: 1px solid #e8e5eb;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  white-space: nowrap;
}

.employees-table td {
  padding: 0.9rem 1rem;
  border-bottom: 1px solid #f0edf2;
  color: #403a46;
  font-size: 0.86rem;
  vertical-align: middle;
}

.employees-table tbody tr:last-child td {
  border-bottom: 0;
}

.employees-table tbody tr:hover {
  background: #fbfafc;
}

.employee-id {
  color: #736782 !important;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.76rem !important;
}

.employee-name {
  min-width: 12rem;
  color: #302a37 !important;
  font-weight: 650;
  overflow-wrap: anywhere;
}

.employees-table td:nth-child(3) {
  color: #746f7b;
  overflow-wrap: anywhere;
}

.status-badge {
  display: inline-flex;
  min-height: 1.55rem;
  align-items: center;
  padding: 0.22rem 0.52rem;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 0.69rem;
  font-weight: 700;
  white-space: nowrap;
}

.status-active {
  color: #246447;
  background: #eaf6ef;
  border-color: #d4eadc;
}

.status-inactive {
  color: #6c6572;
  background: #f2f0f3;
  border-color: #e5e1e8;
}

.action-cell {
  text-align: center;
  white-space: nowrap;
}

.action-header {
  text-align: center;
  white-space: nowrap;
}

.button-row-action {
  min-height: 2.25rem;
  padding: 0.45rem 0.65rem;
  font-size: 0.73rem;
  white-space: nowrap;
}

.pagination-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 1rem;
  margin-top: 1.1rem;
  color: #756e7c;
  font-size: 0.76rem;
}

.pagination-actions {
  display: flex;
  gap: 0.5rem;
}

.pagination-actions .button-secondary {
  min-height: 2.4rem;
  padding: 0.5rem 0.65rem;
  font-size: 0.76rem;
}

.empty-state {
  display: grid;
  justify-items: center;
  padding: 2.5rem 1rem;
  color: #746f7b;
  text-align: center;
}

.empty-icon {
  display: grid;
  width: 2.7rem;
  height: 2.7rem;
  place-items: center;
  color: #654787;
  background: #f3eff7;
  border: 1px solid #e5ddec;
  border-radius: 0.8rem;
  font-weight: 750;
}

.empty-state h3 {
  margin: 0.85rem 0 0.3rem;
  color: #393342;
  font-size: 0.95rem;
}

.notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.8rem 0.9rem;
  border: 1px solid transparent;
  border-radius: 0.7rem;
  font-size: 0.8rem;
  line-height: 1.45;
}

.notice-error {
  color: #67456e;
  background: #f8f5f9;
  border-color: #e6dce9;
}

.loading-message {
  margin: 0;
  color: #6f6877;
  font-size: 0.84rem;
}

.inline-status {
  margin: 0;
  padding: 0.8rem 0;
  color: #746f7b;
  font-size: 0.88rem;
}

.employee-dialog {
  width: min(calc(100% - 2rem), 42rem);
  max-width: 42rem;
  max-height: min(92vh, 54rem);
  overflow-y: auto;
  margin: auto;
  padding: clamp(1.25rem, 3vw, 2rem);
  color: #29252f;
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 1rem;
  box-shadow: 0 1.5rem 4.5rem rgb(15 10 21 / 24%);
}

.employee-dialog::backdrop {
  background: rgb(24 18 31 / 62%);
}

.dialog-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.dialog-header h2 {
  margin: 0;
  color: #29252f;
  font-size: clamp(1.35rem, 3vw, 1.65rem);
  letter-spacing: -0.035em;
}

.employee-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem 1.1rem;
}

.form-notice {
  grid-column: 1 / -1;
}

.employee-dialog .dialog-close {
  width: 2.5rem;
  height: 2.5rem;
  flex: 0 0 auto;
  color: #746f7b;
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 0.7rem;
  cursor: pointer;
}

.employee-dialog .dialog-close:hover:not(:disabled) {
  color: #5c3a86;
  background: #f8f6fa;
  border-color: #d9cde3;
}

.employee-dialog .dialog-close svg {
  width: 1.2rem;
  height: 1.2rem;
}

.employee-dialog .dialog-close:disabled {
  cursor: not-allowed;
  opacity: 0.56;
}

.confirm-dialog {
  width: min(100% - 2rem, 32rem);
  max-width: 32rem;
  padding: 0;
  color: #29252f;
  background: #ffffff;
  border: 1px solid #e1dce5;
  border-radius: 1rem;
  box-shadow: 0 20px 60px rgb(24 17 32 / 22%);
}

.confirm-dialog::backdrop {
  background: rgb(23 17 29 / 46%);
}

.dialog-close-form {
  display: flex;
  justify-content: flex-end;
  padding: 0.6rem 0.65rem 0;
}

.dialog-close {
  display: grid;
  width: 2.2rem;
  height: 2.2rem;
  place-items: center;
  color: #746d7b;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 0.6rem;
  font-size: 1.4rem;
  cursor: pointer;
}

.dialog-content {
  padding: 0 1.5rem 1.5rem;
}

.dialog-content h2 {
  margin: 0;
  font-size: 1.2rem;
}

.dialog-content > p:not(.panel-kicker):not(.notice) {
  margin: 0.75rem 0 0;
  color: #716a79;
  font-size: 0.86rem;
  line-height: 1.55;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.6rem;
  margin-top: 1.5rem;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  clip-path: inset(50%);
}

@media (max-width: 48rem) {
  .page-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .create-button {
    align-self: stretch;
  }

  .panel-heading {
    align-items: flex-start;
  }

}

@media (max-width: 38rem) {
  .employee-dialog {
    width: min(calc(100% - 1rem), 42rem);
    max-height: calc(100vh - 1rem);
    padding: 1.25rem 1rem;
  }

  .employee-form {
    grid-template-columns: minmax(0, 1fr);
    gap: 0.9rem;
  }

  .form-footer {
    align-items: stretch;
    flex-direction: column;
    grid-column: auto;
  }

  .form-actions {
    justify-content: stretch;
  }

  .form-actions .button-primary,
  .form-actions .button-secondary {
    flex: 1 1 auto;
  }

  .form-notice {
    grid-column: auto;
  }

  .pagination-footer {
    align-items: flex-start;
    flex-direction: column;
    gap: 0.6rem;
  }

  .notice {
    align-items: flex-start;
    flex-direction: column;
  }

  .dialog-actions {
    flex-direction: column-reverse;
  }
}

@media (prefers-reduced-motion: reduce) {
  .button-primary,
  .button-secondary {
    transition: none;
  }
}
</style>
