<script setup lang="ts">
import { computed } from 'vue'

definePageMeta({
  layout: 'admin',
  middleware: 'sesion-admin',
})

const { usuario } = useSesion()

const nombreAdmin = computed(() => {
  if (usuario.value === null) {
    return 'Administrador'
  }

  const nombreCompleto = [
    usuario.value.nombre,
    usuario.value.apellido_paterno,
    usuario.value.apellido_materno,
  ]
    .filter((parte): parte is string => parte !== null && parte.length > 0)
    .join(' ')

  return nombreCompleto || usuario.value.correo
})
</script>

<template>
  <main class="dashboard-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">Smart Parking · Administración</p>
        <h1>Dashboard</h1>
        <p class="heading-copy">Bienvenido, {{ nombreAdmin }}.</p>
      </div>
    </header>

    <section class="welcome-panel" aria-labelledby="welcome-title">
      <span class="welcome-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
          <path d="M4 20V5a1 1 0 0 1 1-1h9l6 6v10a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1Z" />
          <path d="M14 4v6h6M8 15h8M8 18h5" />
        </svg>
      </span>
      <div>
        <p class="panel-kicker">Panel de administración</p>
        <h2 id="welcome-title">Tu espacio de gestión</h2>
        <p>Administra el acceso de operadores desde un solo lugar.</p>
      </div>
      <NuxtLink class="primary-link" to="/admin/operadores">
        Administrar operadores
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 12h14m-6-6 6 6-6 6" />
        </svg>
      </NuxtLink>
    </section>

    <section v-if="usuario" class="account-panel" aria-labelledby="account-title">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Sesión activa</p>
          <h2 id="account-title">Cuenta de administrador</h2>
        </div>
      </div>
      <dl class="account-details">
        <div>
          <dt>Nombre</dt>
          <dd>{{ nombreAdmin }}</dd>
        </div>
        <div>
          <dt>Correo electrónico</dt>
          <dd>{{ usuario.correo }}</dd>
        </div>
        <div>
          <dt>Rol</dt>
          <dd>Administrador</dd>
        </div>
      </dl>
    </section>
  </main>
</template>

<style scoped>
.dashboard-page {
  display: grid;
  gap: 1.5rem;
}

.page-heading,
.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.eyebrow,
.panel-kicker {
  margin: 0 0 0.45rem;
  color: #6b4a89;
  font-size: 0.7rem;
  font-weight: 750;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h1,
h2 {
  margin: 0;
  color: #29252f;
  letter-spacing: -0.035em;
}

h1 {
  font-size: clamp(1.8rem, 3vw, 2.35rem);
  line-height: 1.2;
}

h2 {
  font-size: 1.12rem;
  line-height: 1.35;
}

.heading-copy {
  margin: 0.55rem 0 0;
  color: #746f7b;
  font-size: 0.95rem;
}

.welcome-panel,
.account-panel {
  min-width: 0;
  padding: clamp(1.25rem, 2.5vw, 2rem);
  background: #ffffff;
  border: 1px solid #e8e5eb;
  border-radius: 1rem;
  box-shadow: 0 0.75rem 2rem rgb(37 28 47 / 4%);
}

.welcome-panel {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 1.25rem;
}

.welcome-icon {
  display: grid;
  width: 3.25rem;
  height: 3.25rem;
  place-items: center;
  color: #5c3a86;
  background: #f1edf5;
  border: 1px solid #e5dceb;
  border-radius: 0.9rem;
}

.welcome-icon svg {
  width: 1.65rem;
  height: 1.65rem;
}

.panel-kicker {
  margin-bottom: 0.35rem;
  color: #82768e;
  letter-spacing: 0.08em;
}

.welcome-panel h2 {
  font-size: 1.25rem;
}

.welcome-panel p:last-child {
  margin: 0.4rem 0 0;
  color: #746f7b;
  font-size: 0.9rem;
  line-height: 1.55;
}

.primary-link {
  display: inline-flex;
  min-height: 2.75rem;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
  padding: 0.65rem 0.95rem;
  color: #ffffff;
  background: #5c3a86;
  border: 1px solid #5c3a86;
  border-radius: 0.65rem;
  font-size: 0.86rem;
  font-weight: 700;
  text-decoration: none;
  transition: background-color 150ms ease, border-color 150ms ease;
}

.primary-link:hover {
  background: #6c4a97;
  border-color: #6c4a97;
}

.primary-link svg {
  width: 1rem;
  height: 1rem;
}

.account-details {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1rem;
  margin: 1.25rem 0 0;
}

.account-details div {
  min-width: 0;
  padding: 1rem;
  background: #faf9fb;
  border: 1px solid #ece9ef;
  border-radius: 0.7rem;
}

dt {
  color: #827c89;
  font-size: 0.77rem;
  font-weight: 650;
}

dd {
  margin: 0.4rem 0 0;
  color: #302b35;
  font-size: 0.9rem;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.primary-link:focus-visible {
  outline: 3px solid rgb(92 58 134 / 27%);
  outline-offset: 3px;
}

@media (max-width: 58rem) {
  .welcome-panel {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .primary-link {
    grid-column: 2;
    justify-self: start;
  }

  .account-details {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 34rem) {
  .welcome-panel {
    grid-template-columns: minmax(0, 1fr);
  }

  .primary-link {
    grid-column: auto;
    justify-self: stretch;
  }
}
</style>
