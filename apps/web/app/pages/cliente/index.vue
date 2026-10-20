<script setup lang="ts">
import { computed } from 'vue'

import { useSesionCliente } from '~/composables/useSesionCliente'

definePageMeta({
  layout: 'cliente',
  middleware: 'sesion-cliente',
})

const { cliente } = useSesionCliente()
const nombre = computed(() => cliente.value?.nombre ?? 'cliente')

useHead({
  title: 'Inicio | Cuenta de cliente',
  meta: [{ name: 'robots', content: 'noindex, nofollow, noarchive' }],
})
</script>

<template>
  <section class="dashboard" aria-labelledby="dashboard-title">
    <header class="dashboard-heading">
      <p class="eyebrow">CUENTA DE CLIENTE</p>
      <h1 id="dashboard-title">Hola, {{ nombre }}</h1>
      <p>Consulta tu membresía o administra los datos de acceso de tu cuenta.</p>
    </header>

    <div class="dashboard-links">
      <NuxtLink class="dashboard-card" to="/cliente/membresias">
        <span class="card-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="5" width="18" height="14" rx="2" />
            <path d="M3 10h18M7 15h3" />
          </svg>
        </span>
        <span class="card-copy">
          <strong>Membresías</strong>
          <span>Consulta el estado de tu plan mensual.</span>
        </span>
        <span class="card-arrow" aria-hidden="true">›</span>
      </NuxtLink>
      <NuxtLink class="dashboard-card" to="/cliente/configuracion">
        <span class="card-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="8" r="3.5" />
            <path d="M4 20v-1.5A4.5 4.5 0 0 1 8.5 14h7a4.5 4.5 0 0 1 4.5 4.5V20" />
          </svg>
        </span>
        <span class="card-copy">
          <strong>Mi cuenta</strong>
          <span>Revisa tu información y cambia tu contraseña.</span>
        </span>
        <span class="card-arrow" aria-hidden="true">›</span>
      </NuxtLink>
    </div>
  </section>
</template>

<style scoped>
.dashboard { display: grid; gap: 1.6rem; max-width: 72rem; margin: 0 auto; color: #29252f; }
.dashboard-heading { max-width: 46rem; }
.eyebrow { margin: 0 0 .5rem; color: #765b92; font-size: .68rem; font-weight: 800; letter-spacing: .12em; }
h1 { margin: 0; font-size: clamp(1.8rem, 4vw, 2.5rem); letter-spacing: -.05em; }
.dashboard-heading > p:last-child { margin: .65rem 0 0; color: #746f7b; font-size: .9rem; line-height: 1.6; }
.dashboard-links { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
.dashboard-card { display: flex; min-width: 0; min-height: 8rem; align-items: center; gap: 1rem; padding: 1.3rem; color: inherit; background: #fff; border: 1px solid #e8e5eb; border-radius: 1rem; text-decoration: none; transition: border-color 150ms ease, box-shadow 150ms ease, transform 150ms ease; }
.dashboard-card:hover, .dashboard-card:focus-visible { border-color: #c9b8d7; box-shadow: 0 10px 28px rgb(31 20 42 / 6%); transform: translateY(-1px); }
.card-icon { display: grid; width: 2.8rem; height: 2.8rem; flex: 0 0 auto; place-items: center; color: #674187; background: #f4eef8; border: 1px solid #e7dcec; border-radius: .85rem; }
.card-icon svg { width: 1.35rem; height: 1.35rem; }
.card-copy { display: grid; min-width: 0; gap: .3rem; }
.card-copy strong { font-size: .95rem; }
.card-copy > span { color: #746f7b; font-size: .78rem; line-height: 1.5; }
.card-arrow { margin-left: auto; color: #80629a; font-size: 1.7rem; }
.dashboard-card:focus-visible { outline: 3px solid rgb(92 58 134 / 24%); outline-offset: 3px; }
@media (max-width: 42rem) { .dashboard-links { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .dashboard-card { transition: none; } }
</style>
