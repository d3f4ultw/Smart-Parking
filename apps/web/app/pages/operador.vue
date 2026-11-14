<script setup lang="ts">
definePageMeta({ layout: 'admin', middleware: 'operador' })
useSeoMeta({ title: 'Monitoreo | Smart Parking' })

await navigateTo('/operador/monitoreo', { replace: true, redirectCode: 302 })
</script>
