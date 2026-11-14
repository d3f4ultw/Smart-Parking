<script setup lang="ts">
definePageMeta({ layout: 'cliente' })
useHead({
  title: 'Smart Parking | Tu acceso personal',
  meta: [{ name: 'description', content: 'Accede a tu cuenta personal de Smart Parking.' }],
})
</script>

<template>
  <main class="pagina-inicio-cliente">
    <section class="hero-cliente" aria-labelledby="titulo-inicio">
      <div class="hero-contenido">
        <p class="sobrelinea-cliente">Tu espacio personal</p>
        <h1 id="titulo-inicio">Tu cuenta de Smart Parking, en un solo lugar.</h1>
        <p class="descripcion-cliente">
          Crea tu cuenta para consultar tu perfil personal y la información de tu membresía.
        </p>
        <div class="acciones-inicio">
          <UButton to="/clientes/registro" icon="i-lucide-user-round-plus"> Crear cuenta </UButton>
          <UButton to="/clientes/acceso" color="neutral" variant="outline">
            Ya tengo una cuenta
          </UButton>
        </div>
      </div>
      <aside class="resumen-inicio" aria-label="Información de acceso">
        <span class="icono-resumen" aria-hidden="true">
          <UIcon name="i-lucide-shield-check" />
        </span>
        <p class="sobrelinea-cliente">Acceso personal</p>
        <h2>Tu información es privada</h2>
        <p>El portal muestra únicamente los datos de la cuenta con la que iniciaste sesión.</p>
      </aside>
    </section>
  </main>
</template>

<style scoped>
.pagina-inicio-cliente {
  display: grid;
  width: min(100%, 76rem);
  flex: 1;
  align-items: center;
  margin: 0 auto;
  padding: clamp(36px, 7vw, 88px) clamp(20px, 5vw, 72px);
}
.hero-cliente {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(15rem, 0.7fr);
  align-items: center;
  gap: clamp(32px, 6vw, 84px);
}
.hero-contenido {
  max-width: 46rem;
}
.sobrelinea-cliente {
  margin: 0;
  color: var(--app-primary);
  font-size: 0.76rem;
  font-weight: 800;
  letter-spacing: 0.11em;
  text-transform: uppercase;
}
.hero-cliente h1 {
  max-width: 13ch;
  margin: 16px 0;
  font-size: clamp(2.5rem, 6vw, 4.5rem);
  font-weight: 750;
  letter-spacing: -0.055em;
  line-height: 1.04;
}
.descripcion-cliente {
  max-width: 50ch;
  margin: 0;
  color: var(--app-muted);
  font-size: clamp(1rem, 1.5vw, 1.18rem);
  line-height: 1.7;
}
.acciones-inicio {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 30px;
}
.acciones-inicio :deep(button),
.acciones-inicio :deep(a) {
  min-height: 46px;
  border-radius: 10px;
  padding-inline: 18px;
}
.resumen-inicio {
  border: 1px solid var(--app-border);
  border-radius: 16px;
  background: var(--app-surface);
  padding: clamp(22px, 3vw, 32px);
}
.icono-resumen {
  display: grid;
  width: 46px;
  height: 46px;
  place-items: center;
  margin-bottom: 26px;
  border-radius: 12px;
  background: color-mix(in srgb, var(--app-primary) 9%, var(--app-surface));
  color: var(--app-primary);
  font-size: 1.35rem;
}
.resumen-inicio h2 {
  margin: 10px 0;
  font-size: 1.2rem;
  letter-spacing: -0.025em;
}
.resumen-inicio p:last-child {
  margin: 0;
  color: var(--app-muted);
  font-size: 0.92rem;
  line-height: 1.6;
}
@media (max-width: 54rem) {
  .hero-cliente {
    grid-template-columns: minmax(0, 1fr);
  }
  .resumen-inicio {
    max-width: 32rem;
  }
}
</style>
