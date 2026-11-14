<script setup lang="ts">
import FormularioAcceso from '~/components/clientes/FormularioAcceso.vue'

/** Muestra el formulario de acceso y avisa si el cliente acaba de registrarse,
 * cambiar su contraseña o cerrar sesión.
 */
definePageMeta({ layout: 'cliente', middleware: 'cliente-sesion' })

const route = useRoute()
const aviso = computed(() => {
  if (route.query.registro === '1') return 'Tu cuenta se creó. Inicia sesión para continuar.'
  if (route.query.contrasena === 'actualizada') {
    return 'La contraseña se actualizó. Inicia sesión con tu contraseña nueva.'
  }
  if (route.query.salida === '1') return 'Tu sesión de cliente se cerró.'
  return ''
})

useHead({
  title: 'Acceso de cliente | Smart Parking',
  meta: [{ name: 'referrer', content: 'no-referrer' }],
})
</script>

<template>
  <main class="pagina-acceso-cliente">
    <section class="tarjeta-acceso-cliente" aria-labelledby="titulo-acceso">
      <div class="marca-seccion-cliente">
        <UIcon name="i-lucide-lock-keyhole" aria-hidden="true" />
        <span>Portal personal</span>
      </div>
      <p class="sobrelinea-cliente">Bienvenido</p>
      <h1 id="titulo-acceso">Inicia sesión</h1>
      <p class="descripcion-formulario-cliente">
        Usa el correo y la contraseña de tu cuenta de cliente.
      </p>
      <p v-if="aviso" class="aviso-acceso-cliente" role="status">{{ aviso }}</p>
      <FormularioAcceso modo="acceso" />
    </section>
  </main>
</template>

<style scoped>
.pagina-acceso-cliente {
  display: grid;
  flex: 1;
  place-items: center;
  padding: 40px 20px 56px;
}
.tarjeta-acceso-cliente {
  width: min(100%, 29rem);
  border: 1px solid var(--app-border);
  border-radius: 16px;
  background: var(--app-surface);
  padding: clamp(24px, 5vw, 38px);
}
.marca-seccion-cliente {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 25px;
  color: var(--app-primary);
  font-size: 0.82rem;
  font-weight: 750;
}
.sobrelinea-cliente {
  margin: 0;
  color: var(--app-muted);
  font-size: 0.76rem;
  font-weight: 750;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
h1 {
  margin: 5px 0 8px;
  font-size: clamp(1.85rem, 5vw, 2.25rem);
  letter-spacing: -0.045em;
}
.descripcion-formulario-cliente {
  margin: 0 0 24px;
  color: var(--app-muted);
  font-size: 0.94rem;
  line-height: 1.55;
}
.aviso-acceso-cliente {
  border: 1px solid color-mix(in srgb, var(--app-success) 25%, transparent);
  border-radius: 10px;
  background: color-mix(in srgb, var(--app-success) 6%, var(--app-surface));
  margin: 0 0 20px;
  padding: 12px 14px;
  color: var(--app-success);
  font-size: 0.88rem;
  line-height: 1.5;
}
</style>
