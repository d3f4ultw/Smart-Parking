<script setup lang="ts">
import { nextTick, onScopeDispose, watch } from 'vue'
import type { Empleado, PaginaEmpleados, RespuestaAccionEmpleadoOperador } from '~/types/empleado'
import { ErrorEmpleadoApi, useClienteEmpleados } from '~/utils/empleados-api'
import { generarUuidV4 } from '~/utils/uuid'

const abierta = defineModel<boolean>('open', { required: true })
const emit = defineEmits<{ creada: [resultado: RespuestaAccionEmpleadoOperador] }>()
const cliente = useClienteEmpleados()
const csrf = useCsrf()
const sesion = useSesion()
const pagina = ref<PaginaEmpleados | null>(null)
const seleccionado = ref<Empleado | null>(null)
const busqueda = ref('')
const busquedaAplicada = ref('')
const correo = ref('')
const cargando = ref(false)
const ocupado = ref(false)
const error = ref('')
const errorCorreo = ref('')
const paginaActual = ref(1)
let controlador: AbortController | null = null
let temporizadorBusqueda: ReturnType<typeof setTimeout> | undefined
let generacion = 0
let claveIdempotencia = ''
let huellaEnviada = ''

function nombreCompleto(empleado: Empleado) {
  return [empleado.nombres, empleado.primerApellido, empleado.segundoApellido]
    .filter((parte): parte is string => Boolean(parte))
    .join(' ')
}

function cancelarBusqueda() {
  controlador?.abort()
  controlador = null
  generacion += 1
  if (temporizadorBusqueda) clearTimeout(temporizadorBusqueda)
  temporizadorBusqueda = undefined
  cargando.value = false
}

function limpiar() {
  cancelarBusqueda()
  pagina.value = null
  seleccionado.value = null
  busqueda.value = ''
  busquedaAplicada.value = ''
  correo.value = ''
  paginaActual.value = 1
  ocupado.value = false
  error.value = ''
  errorCorreo.value = ''
  claveIdempotencia = ''
  huellaEnviada = ''
}

async function cargar(criterio: string, numeroPagina: number) {
  if (!abierta.value || !import.meta.client) return
  controlador?.abort()
  const nuevoControlador = new AbortController()
  controlador = nuevoControlador
  const solicitud = ++generacion
  cargando.value = true
  error.value = ''
  busquedaAplicada.value = criterio
  paginaActual.value = numeroPagina
  try {
    const resultado = await cliente.listarElegiblesOperador(
      String(numeroPagina),
      criterio,
      nuevoControlador.signal,
    )
    if (nuevoControlador.signal.aborted || solicitud !== generacion) return
    pagina.value = resultado
    paginaActual.value = resultado.pagina
  } catch (fallo) {
    if (nuevoControlador.signal.aborted || solicitud !== generacion) return
    if (fallo instanceof ErrorEmpleadoApi && fallo.estado === 401) {
      await sesion.limpiar()
      await navigateTo('/panel')
      return
    }
    error.value =
      fallo instanceof ErrorEmpleadoApi
        ? fallo.message
        : 'No pudimos buscar empleados. Revisa tu conexión e inténtalo de nuevo.'
  } finally {
    if (controlador === nuevoControlador) {
      controlador = null
      cargando.value = false
    }
  }
}

function programarBusqueda() {
  if (!abierta.value) return
  if (temporizadorBusqueda) clearTimeout(temporizadorBusqueda)
  temporizadorBusqueda = setTimeout(() => {
    temporizadorBusqueda = undefined
    void cargar(busqueda.value.trim(), 1)
  }, 250)
}

async function seleccionar(empleado: Empleado) {
  if (empleado.estado !== 'ACTIVO' || empleado.operador !== null) return
  seleccionado.value = empleado
  correo.value = empleado.correo ?? ''
  error.value = ''
  errorCorreo.value = ''
  await enfocarCorreo()
}

async function cambiarEmpleado() {
  seleccionado.value = null
  correo.value = ''
  error.value = ''
  errorCorreo.value = ''
  await nextTick()
  document.getElementById('busqueda-empleado-operador')?.focus()
}

async function enfocarCorreo() {
  if (!import.meta.client) return
  await nextTick()
  const campo = document.getElementById('correo-nuevo-operador')
  if (!(campo instanceof HTMLInputElement) || campo.disabled) return
  // El campo de correo puede recibir el foco, pero el navegador no permite
  // elegir una posición dentro de este tipo de campo.
  campo.focus({ preventScroll: true })
}

function cambiarPagina(numeroPagina: number) {
  if (!Number.isSafeInteger(numeroPagina) || numeroPagina < 1 || cargando.value) return
  void cargar(busquedaAplicada.value, numeroPagina)
}

function mensajeFallo(fallo: unknown) {
  return fallo instanceof ErrorEmpleadoApi
    ? fallo.message
    : 'No pudimos crear la cuenta. Revisa la lista antes de volver a intentarlo.'
}

async function crearCuenta() {
  const empleado = seleccionado.value
  if (!empleado || ocupado.value) return
  error.value = ''
  errorCorreo.value = ''
  const correoSolicitado = correo.value.trim()
  if (
    !correoSolicitado ||
    Array.from(correoSolicitado).length > 254 ||
    !/^\S+@\S+\.\S+$/.test(correoSolicitado)
  ) {
    errorCorreo.value = 'Escribe un correo válido para enviar la invitación.'
    return
  }

  const huella = JSON.stringify([empleado.idTexto, correoSolicitado.toLowerCase()])
  if (huella !== huellaEnviada) {
    claveIdempotencia = generarUuidV4()
    huellaEnviada = huella
  }

  ocupado.value = true
  try {
    const token = await csrf.obtener()
    const resultado = await cliente.promocionar(
      empleado.idTexto,
      `"${empleado.revisionTexto}"`,
      claveIdempotencia,
      token,
      correoSolicitado,
    )
    emit('creada', resultado)
    abierta.value = false
  } catch (fallo) {
    if (fallo instanceof ErrorEmpleadoApi && fallo.estado === 401) {
      await sesion.limpiar()
      await navigateTo('/panel')
      return
    }
    if (
      fallo instanceof ErrorEmpleadoApi &&
      fallo.estado === 403 &&
      fallo.codigo === 'CSRF_RECHAZADO'
    ) {
      csrf.limpiar()
    }
    if (fallo instanceof ErrorEmpleadoApi && fallo.codigo === 'OPERADOR_YA_VINCULADO') {
      seleccionado.value = null
      correo.value = ''
      await cargar(busquedaAplicada.value, paginaActual.value)
      error.value = mensajeFallo(fallo)
    } else if (fallo instanceof ErrorEmpleadoApi && fallo.estado === 412) {
      const correoAnterior = empleado.correo ?? ''
      const correoEditado = correo.value.trim() !== correoAnterior
      await cargar(busquedaAplicada.value, paginaActual.value)
      const actualizado = pagina.value?.items.find(
        (elemento) => elemento.idTexto === empleado.idTexto,
      )
      if (actualizado) {
        seleccionado.value = actualizado
        if (!correoEditado) correo.value = actualizado.correo ?? ''
        error.value = 'La información cambió. Revisa el correo actualizado antes de continuar.'
      } else {
        seleccionado.value = null
        correo.value = ''
        error.value = 'El empleado ya no está disponible para crear una cuenta.'
      }
    } else {
      error.value = mensajeFallo(fallo)
    }
  } finally {
    ocupado.value = false
  }
}

async function restaurarFoco(evento: Event) {
  evento.preventDefault()
  await nextTick()
  document.getElementById('boton-anadir-operador')?.focus()
}

watch(abierta, (valor) => {
  if (valor) {
    limpiar()
    void cargar('', 1)
  } else {
    limpiar()
  }
})

watch(busqueda, () => {
  if (!abierta.value || busqueda.value.trim() === busquedaAplicada.value) return
  seleccionado.value = null
  correo.value = ''
  programarBusqueda()
})
watch(correo, () => {
  errorCorreo.value = ''
})
onScopeDispose(cancelarBusqueda)
</script>

<template>
  <UModal
    v-model:open="abierta"
    title="Añadir operador"
    description="Selecciona un empleado activo para enviarle una invitación."
    :dismissible="!ocupado"
    :close="!ocupado"
    :ui="{
      overlay: 'bg-black/55',
      content:
        'w-[calc(100%-2rem)] max-w-xl border border-gray-200 bg-white text-gray-900 shadow-xl',
      body: 'p-4 sm:p-5',
    }"
    :content="{ onCloseAutoFocus: restaurarFoco }"
  >
    <template #body>
      <form class="grid gap-4" :aria-busy="ocupado" novalidate @submit.prevent="crearCuenta">
        <section v-if="!seleccionado" class="grid gap-3" aria-label="Elegir empleado">
          <UFormField label="Buscar empleado" name="busqueda">
            <UInput
              id="busqueda-empleado-operador"
              v-model="busqueda"
              class="w-full"
              type="search"
              autocomplete="off"
              placeholder="Nombre o E-0001"
              :disabled="ocupado"
            />
          </UFormField>
          <div
            v-if="cargando"
            class="rounded-xl border border-dashed border-[var(--app-border)] p-4 text-center text-sm leading-6 text-[var(--app-muted)]"
            role="status"
          >
            Buscando empleados…
          </div>
          <p v-else-if="error" class="m-0 text-sm leading-6 text-[var(--app-error)]" role="alert">
            {{ error }}
          </p>
          <div
            v-else-if="(pagina?.items.length ?? 0) === 0"
            class="rounded-xl border border-dashed border-[var(--app-border)] p-4 text-center text-sm leading-6 text-[var(--app-muted)]"
          >
            No hay empleados disponibles con esos datos.
          </div>
          <ul
            v-else
            class="m-0 grid max-h-[min(17rem,38vh)] list-none gap-1.5 overflow-auto p-0"
            aria-label="Empleados disponibles"
          >
            <li v-for="empleado in pagina?.items ?? []" :key="empleado.idTexto">
              <button
                type="button"
                class="flex min-h-[52px] w-full items-center justify-between gap-3 rounded-xl border border-[var(--app-border)] bg-[var(--app-surface)] px-3 py-2.5 text-left text-[var(--app-foreground)] hover:border-[var(--app-primary)] hover:bg-[var(--app-surface-muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-primary)]"
                @click="seleccionar(empleado)"
              >
                <span class="grid gap-1">
                  <strong>{{ nombreCompleto(empleado) }}</strong>
                  <small class="text-[0.82rem] text-[var(--app-muted)]">{{
                    empleado.codigo
                  }}</small>
                </span>
                <UIcon class="shrink-0" name="i-lucide-chevron-right" aria-hidden="true" />
              </button>
            </li>
          </ul>

          <UPagination
            v-if="(pagina?.totalPaginas ?? 0) > 1"
            :page="paginaActual"
            :items-per-page="pagina?.tamanoPagina ?? 10"
            :total="pagina?.totalRegistros ?? 0"
            :disabled="cargando || ocupado"
            aria-label="Páginas de empleados disponibles"
            @update:page="cambiarPagina"
          />
        </section>

        <section
          v-else
          class="grid gap-4 rounded-xl border border-[var(--app-border)] bg-[var(--app-surface-muted)] p-4"
          aria-label="Empleado seleccionado"
        >
          <div class="flex items-start justify-between gap-3 max-sm:flex-col">
            <div class="grid min-w-0 gap-1">
              <span class="text-sm font-semibold text-[var(--app-muted)]"
                >Empleado seleccionado</span
              >
              <strong>{{ nombreCompleto(seleccionado) }}</strong>
              <small class="text-[0.82rem] text-[var(--app-muted)]">{{
                seleccionado.codigo
              }}</small>
            </div>
            <UButton
              type="button"
              color="neutral"
              variant="ghost"
              icon="i-lucide-pencil"
              class="max-sm:w-fit"
              :disabled="ocupado"
              @click="cambiarEmpleado"
            >
              Cambiar empleado
            </UButton>
          </div>
          <UFormField
            label="Correo para la cuenta y la invitación"
            name="correo"
            :error="errorCorreo"
          >
            <UInput
              id="correo-nuevo-operador"
              v-model="correo"
              class="w-full"
              type="email"
              autocomplete="email"
              maxlength="254"
              required
              :disabled="ocupado"
              :aria-invalid="Boolean(errorCorreo)"
            />
          </UFormField>
        </section>

        <p
          v-if="error && seleccionado"
          class="m-0 text-sm leading-6 text-[var(--app-error)]"
          role="alert"
        >
          {{ error }}
        </p>
        <footer class="flex justify-end gap-2 pt-1 max-sm:flex-col">
          <UButton
            type="button"
            color="neutral"
            variant="outline"
            class="max-sm:w-full max-sm:justify-center"
            :disabled="ocupado"
            @click="abierta = false"
          >
            Cancelar
          </UButton>
          <UButton
            type="submit"
            icon="i-lucide-mail-plus"
            class="max-sm:w-full max-sm:justify-center"
            :loading="ocupado"
            :disabled="!seleccionado || !correo.trim() || ocupado"
          >
            {{ ocupado ? 'Enviando invitación…' : 'Enviar invitación' }}
          </UButton>
        </footer>
      </form>
    </template>
  </UModal>
</template>

<style scoped lang="css">
/* La ventana usa clases de utilidad; este bloque mantiene activados sus estilos
   locales sin añadir reglas visuales. */
</style>
