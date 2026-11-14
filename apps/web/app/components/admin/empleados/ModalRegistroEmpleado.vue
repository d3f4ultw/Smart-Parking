<script setup lang="ts">
import { nextTick } from 'vue'
import type { RegistroEmpleado, ReciboRegistroEmpleado } from '~/types/empleado'
import { ErrorEmpleadoApi, useClienteEmpleados } from '~/utils/empleados-api'
import { generarUuidV4 } from '~/utils/uuid'

const abierta = defineModel<boolean>('open', { required: true })
const emit = defineEmits<{ registrado: [recibo: ReciboRegistroEmpleado] }>()
const cliente = useClienteEmpleados()
const csrf = useCsrf()
const formulario = reactive({ nombres: '', primerApellido: '', segundoApellido: '', correo: '' })
const errores = reactive<{
  nombres?: string
  primerApellido?: string
  segundoApellido?: string
  correo?: string
}>({})
const mensajeError = ref('')
const enviando = ref(false)
let claveIdempotencia = ''

function enfocarNombresAlFinal(evento: Event) {
  if (!import.meta.client) return
  evento.preventDefault()
  void nextTick(() => {
    const campo = document.getElementById('empleado-nombres')
    if (!(campo instanceof HTMLInputElement)) return
    campo.focus({ preventScroll: true })
    campo.setSelectionRange(campo.value.length, campo.value.length)
  })
}

watch(abierta, (valor) => {
  if (!valor) return
  mensajeError.value = ''
  limpiarErrores()
})

watch(
  formulario,
  () => {
    claveIdempotencia = ''
  },
  { deep: true },
)

function limpiarErrores() {
  errores.nombres = undefined
  errores.primerApellido = undefined
  errores.segundoApellido = undefined
  errores.correo = undefined
}

function normalizar(): RegistroEmpleado {
  return {
    nombres: formulario.nombres.trim(),
    primerApellido: formulario.primerApellido.trim(),
    segundoApellido: formulario.segundoApellido.trim() || null,
    ...(formulario.correo.trim() ? { correo: formulario.correo.trim() } : {}),
  }
}

function validar(datos: RegistroEmpleado) {
  limpiarErrores()
  for (const campo of ['nombres', 'primerApellido', 'segundoApellido'] as const) {
    const valor = datos[campo] ?? ''
    if (campo !== 'segundoApellido' && !valor) errores[campo] = 'Este campo es obligatorio.'
    else if (Array.from(valor).length > 100) errores[campo] = 'Escribe un texto más corto.'
  }
  if (
    datos.correo &&
    (Array.from(datos.correo).length > 254 || !/^\S+@\S+\.\S+$/.test(datos.correo))
  ) {
    errores.correo = 'Escribe un correo válido.'
  }
  return !errores.nombres && !errores.primerApellido && !errores.segundoApellido && !errores.correo
}

async function registrar() {
  if (enviando.value) return
  mensajeError.value = ''
  const datos = normalizar()
  if (!validar(datos)) return
  enviando.value = true
  try {
    if (!claveIdempotencia) claveIdempotencia = generarUuidV4()
    const token = await csrf.obtener()
    const recibo = await cliente.registrar(datos, claveIdempotencia, token)
    claveIdempotencia = ''
    abierta.value = false
    formulario.nombres = ''
    formulario.primerApellido = ''
    formulario.segundoApellido = ''
    formulario.correo = ''
    limpiarErrores()
    emit('registrado', recibo)
  } catch (fallo) {
    mensajeError.value =
      fallo instanceof ErrorEmpleadoApi
        ? fallo.message
        : 'No sabemos si se agregó al empleado. Revisa la lista antes de intentarlo de nuevo.'
  } finally {
    enviando.value = false
  }
}
</script>

<template>
  <UModal
    v-model:open="abierta"
    title="Agregar empleado"
    description="Ingresa los datos del empleado."
    :dismissible="!enviando"
    :close="!enviando"
    :ui="{
      overlay: 'bg-black/55',
      content: 'max-w-xl border border-gray-200 bg-white text-gray-900 shadow-xl',
      body: 'p-4 sm:p-5',
    }"
    :content="{ onOpenAutoFocus: enfocarNombresAlFinal }"
  >
    <template #body>
      <form
        class="formulario-empleado"
        :aria-busy="enviando"
        novalidate
        @submit.prevent="registrar"
      >
        <UFormField class="w-full" label="Nombres" name="nombres" :error="errores.nombres">
          <UInput
            id="empleado-nombres"
            class="w-full"
            v-model="formulario.nombres"
            autocomplete="given-name"
            required
            :disabled="enviando"
            :aria-invalid="Boolean(errores.nombres)"
          />
        </UFormField>
        <div class="apellidos-empleado">
          <UFormField
            class="w-full"
            label="Primer apellido"
            name="primerApellido"
            :error="errores.primerApellido"
          >
            <UInput
              id="empleado-primer-apellido"
              class="w-full"
              v-model="formulario.primerApellido"
              autocomplete="family-name"
              required
              :disabled="enviando"
              :aria-invalid="Boolean(errores.primerApellido)"
            />
          </UFormField>
          <UFormField
            class="w-full"
            label="Segundo apellido (opcional)"
            name="segundoApellido"
            :error="errores.segundoApellido"
          >
            <UInput
              id="empleado-segundo-apellido"
              class="w-full"
              v-model="formulario.segundoApellido"
              autocomplete="additional-name"
              :disabled="enviando"
              :aria-invalid="Boolean(errores.segundoApellido)"
            />
          </UFormField>
        </div>
        <UFormField
          class="w-full"
          label="Correo electrónico (opcional)"
          name="correo"
          :error="errores.correo"
        >
          <UInput
            id="empleado-correo"
            class="w-full"
            v-model="formulario.correo"
            type="email"
            autocomplete="email"
            maxlength="254"
            :disabled="enviando"
            :aria-invalid="Boolean(errores.correo)"
          />
        </UFormField>
        <p v-if="mensajeError" class="error-registro" role="alert">{{ mensajeError }}</p>
        <footer class="acciones-modal-empleado">
          <UButton
            type="button"
            color="neutral"
            variant="outline"
            :disabled="enviando"
            @click="abierta = false"
            >Cancelar</UButton
          >
          <UButton
            type="submit"
            icon="i-lucide-user-round-plus"
            :loading="enviando"
            :disabled="enviando"
            >Agregar</UButton
          >
        </footer>
      </form>
    </template>
  </UModal>
</template>

<style scoped>
.formulario-empleado {
  display: grid;
  gap: 14px;
}
.apellidos-empleado {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}
.apellidos-empleado > * {
  min-width: 0;
}
.formulario-empleado :deep(input) {
  min-height: 44px;
}
.error-registro {
  margin: 0;
  color: var(--app-error);
  font-size: 0.9rem;
}
.acciones-modal-empleado {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 4px;
}
@media (max-width: 34rem) {
  .apellidos-empleado {
    grid-template-columns: minmax(0, 1fr);
  }
  .acciones-modal-empleado {
    flex-direction: column-reverse;
  }
  .acciones-modal-empleado :deep(button) {
    width: 100%;
    justify-content: center;
  }
}
</style>
