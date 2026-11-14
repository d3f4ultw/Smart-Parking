<script setup lang="ts">
import { nextTick, onScopeDispose, watch } from 'vue'
import type { DetalleOperador } from '~/types/operador'
import type { Empleado, PaginaEmpleados } from '~/types/empleado'
import { ErrorEmpleadoApi, useClienteEmpleados } from '~/utils/empleados-api'
import { ErrorOperadoresApi, useClienteOperadores } from '~/utils/operadores-api'
import { generarUuidV4 } from '~/utils/uuid'

const abierta = defineModel<boolean>('open', { required: true })
const props = defineProps<{ operadorId: string | null; indiceFoco: number | null }>()
const emit = defineEmits<{ vinculado: [] }>()
const empleadosApi = useClienteEmpleados()
const operadoresApi = useClienteOperadores()
const csrf = useCsrf()
const sesion = useSesion()
const operador = ref<DetalleOperador | null>(null)
const revisionOperador = ref<string | null>(null)
const pagina = ref<PaginaEmpleados | null>(null)
const empleadoIdSeleccionado = ref<string>()
const empleado = ref<Empleado | null>(null)
const etagEmpleado = ref<string | null>(null)
const confirmarPar = ref(false)
const copiarCorreoConsentido = ref(false)
const cargando = ref(false)
const cargandoEmpleado = ref(false)
const ocupado = ref(false)
const error = ref('')
const claveIdempotencia = ref('')
const huellaEnviada = ref('')
let controlador: AbortController | null = null
let controladorEmpleado: AbortController | null = null

const empleadosSinCuenta = computed(() =>
  (pagina.value?.items ?? []).filter((elemento) => elemento.operador === null),
)

const correosCoinciden = computed(() =>
  Boolean(
    operador.value &&
    empleado.value?.correo &&
    operador.value.correo.trim().toLowerCase() === empleado.value.correo.trim().toLowerCase(),
  ),
)

const faltaCorreoEmpleado = computed(() => Boolean(operador.value && !empleado.value?.correo))

const correoIncompatible = computed(() =>
  Boolean(
    operador.value &&
    empleado.value?.correo &&
    operador.value.correo.trim().toLowerCase() !== empleado.value.correo.trim().toLowerCase(),
  ),
)

const puedeVincular = computed(() =>
  Boolean(
    operador.value?.estadoConciliacion === 'LEGADO_SIN_VINCULO' &&
    empleado.value &&
    empleado.value.operador === null &&
    etagEmpleado.value &&
    revisionOperador.value &&
    confirmarPar.value &&
    !correoIncompatible.value &&
    (!faltaCorreoEmpleado.value || copiarCorreoConsentido.value) &&
    !ocupado.value,
  ),
)

function nombreEmpleado(valor: Empleado) {
  return [valor.nombres, valor.primerApellido, valor.segundoApellido]
    .filter((parte): parte is string => Boolean(parte))
    .join(' ')
}

function nombreOperador(valor: DetalleOperador) {
  return [valor.nombres, valor.primerApellido, valor.segundoApellido]
    .filter((parte): parte is string => Boolean(parte))
    .join(' ')
}

function mensajeFallo(fallo: unknown) {
  if (fallo instanceof ErrorEmpleadoApi || fallo instanceof ErrorOperadoresApi) {
    return fallo.message
  }
  return 'No pudimos completar la vinculación. Actualiza la información e inténtalo de nuevo.'
}

async function manejarFallo(fallo: unknown) {
  if (
    (fallo instanceof ErrorEmpleadoApi || fallo instanceof ErrorOperadoresApi) &&
    fallo.estado === 401
  ) {
    await sesion.limpiar()
    await navigateTo('/panel')
  } else if (
    fallo instanceof ErrorEmpleadoApi &&
    fallo.estado === 403 &&
    fallo.codigo === 'CSRF_RECHAZADO'
  ) {
    csrf.limpiar()
  }
}

function limpiar() {
  controlador?.abort()
  controladorEmpleado?.abort()
  controlador = null
  controladorEmpleado = null
  operador.value = null
  revisionOperador.value = null
  pagina.value = null
  empleadoIdSeleccionado.value = undefined
  empleado.value = null
  etagEmpleado.value = null
  confirmarPar.value = false
  copiarCorreoConsentido.value = false
  error.value = ''
  claveIdempotencia.value = ''
  huellaEnviada.value = ''
  cargando.value = false
  cargandoEmpleado.value = false
}

async function cargarPagina(numero: number, signal?: AbortSignal) {
  const respuesta = await empleadosApi.listar(String(numero), signal)
  pagina.value = {
    ...respuesta,
    items: respuesta.items.map((persona) => ({ ...persona, correo: null })),
  }
}

async function cargar() {
  const operadorId = props.operadorId
  if (!operadorId || !abierta.value) return
  controlador?.abort()
  const nuevoControlador = new AbortController()
  controlador = nuevoControlador
  cargando.value = true
  error.value = ''
  try {
    const [respuestaOperador] = await Promise.all([
      operadoresApi.detalle(operadorId, nuevoControlador.signal),
      cargarPagina(1, nuevoControlador.signal),
    ])
    if (nuevoControlador.signal.aborted || operadorId !== props.operadorId) return
    const revision = /^"(0|[1-9]\d{0,18})"$/.exec(respuestaOperador.etag)?.[1]
    if (!revision || BigInt(revision) > 9223372036854775807n) {
      throw new Error('La revisión de la cuenta no es válida.')
    }
    operador.value = respuestaOperador.datos
    revisionOperador.value = revision
  } catch (fallo) {
    if (nuevoControlador.signal.aborted) return
    await manejarFallo(fallo)
    error.value = mensajeFallo(fallo)
  } finally {
    if (controlador === nuevoControlador) {
      controlador = null
      cargando.value = false
    }
  }
}

watch(abierta, (valor) => {
  if (valor) void cargar()
  else limpiar()
})

watch(
  () => props.operadorId,
  () => {
    if (abierta.value) void cargar()
  },
)

watch(empleadoIdSeleccionado, async (idTexto) => {
  controladorEmpleado?.abort()
  controladorEmpleado = null
  empleado.value = null
  etagEmpleado.value = null
  confirmarPar.value = false
  copiarCorreoConsentido.value = false
  claveIdempotencia.value = ''
  huellaEnviada.value = ''
  error.value = ''
  if (!idTexto) return
  const nuevoControlador = new AbortController()
  controladorEmpleado = nuevoControlador
  cargandoEmpleado.value = true
  try {
    const respuesta = await empleadosApi.detalle(idTexto, nuevoControlador.signal)
    if (nuevoControlador.signal.aborted || empleadoIdSeleccionado.value !== idTexto) return
    empleado.value = respuesta.datos
    etagEmpleado.value = respuesta.etag
  } catch (fallo) {
    if (nuevoControlador.signal.aborted || empleadoIdSeleccionado.value !== idTexto) return
    await manejarFallo(fallo)
    error.value = mensajeFallo(fallo)
  } finally {
    if (controladorEmpleado === nuevoControlador) {
      controladorEmpleado = null
      cargandoEmpleado.value = false
    }
  }
})

watch([confirmarPar, copiarCorreoConsentido], () => {
  claveIdempotencia.value = ''
  huellaEnviada.value = ''
})

onScopeDispose(() => {
  controlador?.abort()
  controladorEmpleado?.abort()
})

async function cambiarPagina(destino: number) {
  if (destino < 1 || destino > (pagina.value?.totalPaginas ?? 0) || ocupado.value) return
  empleadoIdSeleccionado.value = undefined
  empleado.value = null
  etagEmpleado.value = null
  cargando.value = true
  error.value = ''
  try {
    await cargarPagina(destino)
  } catch (fallo) {
    await manejarFallo(fallo)
    error.value = mensajeFallo(fallo)
  } finally {
    cargando.value = false
  }
}

async function vincular() {
  const cuenta = operador.value
  const persona = empleado.value
  const revisionCuenta = revisionOperador.value
  const revisionPersona = etagEmpleado.value
  if (!cuenta || !persona || !revisionCuenta || !revisionPersona || !puedeVincular.value) return
  error.value = ''
  const copiar = faltaCorreoEmpleado.value && copiarCorreoConsentido.value
  const huella = JSON.stringify({
    empleadoId: persona.idTexto,
    operadorId: cuenta.id,
    revisionOperador: revisionCuenta,
    copiarCorreoOperador: copiar,
  })
  ocupado.value = true
  try {
    if (!claveIdempotencia.value || huellaEnviada.value !== huella) {
      claveIdempotencia.value = generarUuidV4()
      huellaEnviada.value = huella
    }
    const token = await csrf.obtener()
    await empleadosApi.vincular(
      persona.idTexto,
      cuenta.id,
      revisionCuenta,
      copiar,
      revisionPersona,
      claveIdempotencia.value,
      token,
    )
    claveIdempotencia.value = ''
    huellaEnviada.value = ''
    emit('vinculado')
    abierta.value = false
  } catch (fallo) {
    await manejarFallo(fallo)
    const mensaje = mensajeFallo(fallo)
    error.value = mensaje
    if (fallo instanceof ErrorEmpleadoApi && fallo.estado === 412) {
      empleadoIdSeleccionado.value = undefined
      empleado.value = null
      etagEmpleado.value = null
      confirmarPar.value = false
      copiarCorreoConsentido.value = false
      claveIdempotencia.value = ''
      huellaEnviada.value = ''
      await cargar()
      error.value = mensaje
    }
  } finally {
    ocupado.value = false
  }
}

async function restaurarFoco(evento: Event) {
  evento.preventDefault()
  await nextTick()
  if (props.indiceFoco !== null) {
    const disparador =
      document.getElementById(`operador-vincular-${props.indiceFoco}`) ??
      document.getElementById(`operador-administrar-${props.indiceFoco}`)
    disparador?.focus()
  }
}
</script>

<template>
  <UModal
    v-model:open="abierta"
    title="Vincular cuenta con empleado"
    description="Selecciona a la persona y confirma el par antes de conciliar la cuenta heredada."
    :dismissible="!ocupado"
    :close="!ocupado"
    :content="{ onCloseAutoFocus: restaurarFoco }"
  >
    <template #body>
      <div v-if="cargando" class="estado-conciliacion" role="status">
        Cargando cuentas y empleados…
      </div>
      <div v-else-if="error && !operador" class="contenido-conciliacion">
        <p class="error-conciliacion" role="alert">{{ error }}</p>
        <UButton color="neutral" variant="outline" @click="cargar">Reintentar</UButton>
      </div>
      <div v-else-if="operador" class="contenido-conciliacion">
        <section class="resumen-cuenta" aria-labelledby="titulo-cuenta-legada">
          <p class="sobrelinea">Cuenta heredada</p>
          <h3 id="titulo-cuenta-legada">{{ nombreOperador(operador) }}</h3>
          <p>{{ operador.correo }}</p>
          <UBadge
            :color="operador.estadoConciliacion === 'LEGADO_SIN_VINCULO' ? 'warning' : 'success'"
            variant="subtle"
          >
            {{
              operador.estadoConciliacion === 'LEGADO_SIN_VINCULO' ? 'Sin vínculo' : 'Ya vinculada'
            }}
          </UBadge>
        </section>

        <UFormField label="Empleado disponible" name="empleado">
          <USelect
            v-model="empleadoIdSeleccionado"
            :items="
              empleadosSinCuenta.map((persona) => ({
                label: `${persona.codigo} · ${nombreEmpleado(persona)}`,
                value: persona.idTexto,
              }))
            "
            value-key="value"
            placeholder="Selecciona un empleado"
            :disabled="
              cargando ||
              ocupado ||
              cargandoEmpleado ||
              empleadosSinCuenta.length === 0 ||
              operador.estadoConciliacion !== 'LEGADO_SIN_VINCULO'
            "
          />
        </UFormField>

        <p v-if="operador.estadoConciliacion !== 'LEGADO_SIN_VINCULO'" class="ayuda-conciliacion">
          Esta cuenta ya está vinculada a un empleado.
        </p>

        <div v-if="pagina && pagina.totalPaginas > 1" class="paginacion-conciliacion">
          <span>Página {{ pagina.pagina }} de {{ pagina.totalPaginas }}</span>
          <div>
            <UButton
              color="neutral"
              variant="outline"
              size="sm"
              :disabled="ocupado || pagina.pagina <= 1"
              @click="cambiarPagina(pagina.pagina - 1)"
              >Anterior</UButton
            >
            <UButton
              color="neutral"
              variant="outline"
              size="sm"
              :disabled="ocupado || pagina.pagina >= pagina.totalPaginas"
              @click="cambiarPagina(pagina.pagina + 1)"
              >Siguiente</UButton
            >
          </div>
        </div>

        <p
          v-if="pagina && empleadosSinCuenta.length === 0"
          class="ayuda-conciliacion"
          role="status"
        >
          Esta página no tiene empleados disponibles para vincular.
        </p>

        <div v-if="cargandoEmpleado" class="estado-conciliacion" role="status">
          Comprobando el empleado seleccionado…
        </div>
        <section v-else-if="empleado" class="resumen-empleado" aria-labelledby="titulo-par">
          <h3 id="titulo-par">Empleado seleccionado</h3>
          <dl>
            <div>
              <dt>Nombre</dt>
              <dd>{{ nombreEmpleado(empleado) }}</dd>
            </div>
            <div>
              <dt>Número</dt>
              <dd>{{ empleado.codigo }}</dd>
            </div>
            <div>
              <dt>Correo</dt>
              <dd>{{ empleado.correo || 'Sin correo' }}</dd>
            </div>
            <div>
              <dt>Estado</dt>
              <dd>{{ empleado.estado === 'ACTIVO' ? 'Activo' : 'Inactivo' }}</dd>
            </div>
          </dl>
          <p v-if="empleado.operador" class="error-conciliacion" role="alert">
            Este empleado ya tiene una cuenta de operador vinculada.
          </p>
          <p v-else-if="correoIncompatible" class="error-conciliacion" role="alert">
            Los correos son distintos. Actualiza el correo del empleado antes de vincular; no se
            cambiarán correos durante la conciliación.
          </p>
          <p v-else-if="faltaCorreoEmpleado" class="ayuda-conciliacion">
            El empleado no tiene correo. Puedes autorizar explícitamente que se copie el correo de
            esta cuenta.
          </p>
          <p v-else-if="correosCoinciden" class="ayuda-conciliacion">
            El correo del empleado coincide con el de esta cuenta.
          </p>
        </section>

        <UCheckbox
          v-if="empleado && !empleado.operador && !correoIncompatible"
          v-model="confirmarPar"
          :label="`Confirmo vincular ${nombreOperador(operador)} con ${nombreEmpleado(empleado)} (${empleado.codigo}).`"
          :disabled="ocupado"
        />
        <UCheckbox
          v-if="faltaCorreoEmpleado"
          v-model="copiarCorreoConsentido"
          label="Autorizo copiar el correo de la cuenta al empleado, que no tiene uno."
          :disabled="ocupado"
        />

        <p v-if="error && operador" class="error-conciliacion" role="alert">{{ error }}</p>
        <p class="ayuda-conciliacion">
          La conciliación no copia nombres ni reenvía invitaciones. La cuenta y el empleado deben
          corresponder a la misma persona.
        </p>
        <footer class="acciones-conciliacion">
          <UButton color="neutral" variant="outline" :disabled="ocupado" @click="abierta = false"
            >Cancelar</UButton
          >
          <UButton
            icon="i-lucide-link"
            :loading="ocupado"
            :disabled="!puedeVincular"
            @click="vincular"
            >Vincular cuenta</UButton
          >
        </footer>
      </div>
    </template>
  </UModal>
</template>

<style scoped>
.contenido-conciliacion {
  display: grid;
  gap: 18px;
}
.resumen-cuenta,
.resumen-empleado {
  display: grid;
  gap: 8px;
  padding: 14px;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  background: var(--app-surface);
}
.resumen-cuenta h3,
.resumen-empleado h3 {
  margin: 0;
  color: var(--app-foreground);
  font-size: 1rem;
}
.resumen-cuenta p,
.sobrelinea {
  margin: 0;
  color: var(--app-muted);
}
.sobrelinea {
  font-size: 0.76rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.resumen-empleado dl {
  display: grid;
  gap: 8px;
  margin: 0;
}
.resumen-empleado dl > div {
  display: grid;
  grid-template-columns: 6rem minmax(0, 1fr);
  gap: 10px;
}
.resumen-empleado dt {
  color: var(--app-muted);
}
.resumen-empleado dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--app-foreground);
}
.paginacion-conciliacion,
.paginacion-conciliacion > div,
.acciones-conciliacion {
  display: flex;
  align-items: center;
  gap: 8px;
}
.paginacion-conciliacion,
.acciones-conciliacion {
  justify-content: space-between;
}
.paginacion-conciliacion > span,
.ayuda-conciliacion,
.estado-conciliacion {
  color: var(--app-muted);
  line-height: 1.5;
}
.ayuda-conciliacion,
.error-conciliacion {
  margin: 0;
}
.error-conciliacion {
  color: var(--app-error);
  line-height: 1.5;
}
@media (max-width: 34rem) {
  .paginacion-conciliacion,
  .acciones-conciliacion {
    align-items: stretch;
    flex-direction: column;
  }
  .paginacion-conciliacion > div {
    justify-content: space-between;
  }
  .acciones-conciliacion :deep(button) {
    width: 100%;
    justify-content: center;
  }
}
</style>
