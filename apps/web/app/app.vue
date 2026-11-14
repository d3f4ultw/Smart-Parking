<script setup lang="ts">
import { watch } from 'vue'

const ruta = useRoute()
const toast = useToast()

watch(
  () => ruta.path,
  () => toast.clear(),
)
</script>

<template>
  <UApp>
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
  </UApp>
</template>
