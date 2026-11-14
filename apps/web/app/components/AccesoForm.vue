<script setup lang="ts">
const emit = defineEmits<{
  submit: [correo: string, contrasena: string]
}>()
const props = defineProps<{ cargando: boolean; error?: string }>()

const correo = ref('')
const contrasena = ref('')
const mostrarContrasena = ref(false)
const hidratado = ref(false)

onMounted(() => {
  hidratado.value = true
})

function enviar() {
  if (!hidratado.value || props.cargando) return
  emit('submit', correo.value, contrasena.value)
}

function limpiarContrasena() {
  contrasena.value = ''
}

defineExpose({ limpiarContrasena })
</script>

<template>
  <form class="grid w-full gap-5" method="post" @submit.prevent="enviar">
    <UFormField label="Correo electrónico" name="correo">
      <UInput
        v-model="correo"
        type="email"
        autocomplete="username"
        size="lg"
        required
        :disabled="!hidratado || cargando"
        :aria-invalid="Boolean(props.error)"
        :aria-describedby="props.error ? 'error-acceso' : undefined"
        class="w-full"
      />
    </UFormField>
    <UFormField label="Contraseña" name="contrasena">
      <UInput
        v-model="contrasena"
        :type="mostrarContrasena ? 'text' : 'password'"
        autocomplete="current-password"
        size="lg"
        required
        :disabled="!hidratado || cargando"
        :aria-invalid="Boolean(props.error)"
        :aria-describedby="props.error ? 'error-acceso' : undefined"
        class="w-full"
      >
        <template #trailing>
          <UButton
            type="button"
            color="neutral"
            variant="ghost"
            size="sm"
            class="size-8 shrink-0"
            :disabled="!hidratado || cargando"
            :aria-label="mostrarContrasena ? 'Ocultar contraseña' : 'Mostrar contraseña'"
            :aria-pressed="mostrarContrasena"
            @click="mostrarContrasena = !mostrarContrasena"
          >
            <UIcon :name="mostrarContrasena ? 'i-lucide-eye-off' : 'i-lucide-eye'" />
          </UButton>
        </template>
      </UInput>
    </UFormField>
    <p v-if="props.error" id="error-acceso" class="text-sm text-error" role="alert">
      {{ props.error }}
    </p>
    <UButton type="submit" size="lg" block :loading="cargando" :disabled="!hidratado || cargando">
      Iniciar sesión
    </UButton>
  </form>
</template>
