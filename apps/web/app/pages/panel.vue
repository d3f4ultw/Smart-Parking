<script setup lang="ts">
import { ErrorApi } from '~/utils/api'

definePageMeta({ middleware: 'sesion' })

const { sesion, cargando, actualizar } = useSesion()
const acceso = useAutenticacion()
const formulario = useTemplateRef<{ limpiarContrasena: () => void }>('formulario')
const enviando = ref(false)
const reintentando = ref(false)
const error = ref('')

async function iniciar(correo: string, contrasena: string) {
  enviando.value = true
  error.value = ''
  try {
    await acceso.iniciar(correo, contrasena)
    if (sesion.value.estado !== 'autenticada') {
      error.value = 'No pudimos comprobar tu acceso. Revisa tu conexión e inténtalo de nuevo.'
      return
    }
    await navigateTo(sesion.value.identidad.rol === 'OPERADOR' ? '/operador' : '/admin')
  } catch (fallo) {
    acceso.manejarFalloCsrf(fallo)
    if (fallo instanceof ErrorApi && fallo.estado === 401) {
      error.value = 'El correo o la contraseña no son correctos.'
    } else {
      error.value =
        'No pudimos conectar con Smart Parking. Revisa tu conexión e inténtalo de nuevo.'
    }
  } finally {
    formulario.value?.limpiarContrasena()
    enviando.value = false
  }
}

async function reintentar() {
  if (reintentando.value) return
  reintentando.value = true
  try {
    await actualizar()
    if (sesion.value.estado === 'autenticada') {
      error.value = ''
      await navigateTo(sesion.value.identidad.rol === 'OPERADOR' ? '/operador' : '/admin')
      return
    }
    if (sesion.value.estado === 'anonima') {
      error.value = 'No encontramos una sesión activa. Inicia sesión para continuar.'
    }
  } finally {
    reintentando.value = false
  }
}
</script>

<template>
  <main class="grid min-h-screen place-items-center px-4 py-8 sm:px-6">
    <section class="w-full max-w-lg" aria-labelledby="titulo-acceso">
      <UCard
        :ui="{
          root: 'w-full overflow-hidden rounded-2xl border border-default bg-default shadow-xl',
          body: 'p-6 sm:p-10',
        }"
      >
        <div class="mb-8 flex items-center gap-2.5">
          <UIcon name="i-lucide-square-parking" class="size-5 text-primary" aria-hidden="true" />
          <span class="text-xs font-bold tracking-[0.12em] text-highlighted">SMART PARKING</span>
        </div>

        <div class="mb-7 grid gap-2">
          <p class="text-xs font-semibold uppercase tracking-[0.1em] text-muted">
            Panel administrativo
          </p>
          <h1
            id="titulo-acceso"
            class="text-2xl font-semibold tracking-tight text-highlighted sm:text-3xl"
          >
            Iniciar sesión
          </h1>
          <p class="text-sm leading-6 text-muted">Ingresa tu correo y contraseña para acceder.</p>
        </div>

        <div v-if="sesion.estado === 'error'" class="grid w-full gap-3" role="alert">
          <p class="text-sm leading-6 text-muted">
            No pudimos conectar con Smart Parking. Revisa tu conexión e inténtalo de nuevo.
          </p>
          <UButton
            variant="outline"
            :loading="reintentando"
            :disabled="reintentando || cargando"
            @click="reintentar"
          >
            Reintentar
          </UButton>
        </div>
        <div v-else-if="cargando" class="w-full text-sm text-muted" aria-live="polite">
          Comprobando tu acceso…
        </div>
        <AccesoForm v-else ref="formulario" :cargando="enviando" :error="error" @submit="iniciar" />
      </UCard>
    </section>
  </main>
</template>
