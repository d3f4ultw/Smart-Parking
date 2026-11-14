<script setup lang="ts">
import { ErrorApi } from '~/utils/api'

const { sesion, cargando, actualizar } = useSesion()
const autenticacion = useAutenticacion()
const cerrando = ref(false)
const revalidando = ref(false)
const errorCierre = ref('')
const errorSesion = ref('')
let solicitudRevalidacion: Promise<void> | null = null

async function revalidarAcceso(): Promise<void> {
  if (solicitudRevalidacion) return solicitudRevalidacion

  revalidando.value = true
  errorSesion.value = ''
  const solicitud = (async () => {
    await actualizar()

    if (sesion.value.estado === 'anonima') {
      await navigateTo('/panel')
      return
    }
    if (sesion.value.estado === 'error') {
      errorSesion.value = 'No pudimos comprobar tu acceso. Inténtalo de nuevo.'
      return
    }
    if (sesion.value.identidad.rol !== 'OPERADOR') {
      showError(createError({ statusCode: 403, statusMessage: 'Acceso no disponible.' }))
    }
  })()

  solicitudRevalidacion = solicitud
  try {
    await solicitud
  } finally {
    if (solicitudRevalidacion === solicitud) solicitudRevalidacion = null
    revalidando.value = false
  }
}

async function cerrarSesion() {
  if (cerrando.value) return
  cerrando.value = true
  errorCierre.value = ''

  try {
    await autenticacion.cerrar()
  } catch (fallo) {
    if (sesion.value.estado === 'error') {
      errorSesion.value = 'No pudimos comprobar tu acceso. No se confirmó el cierre.'
      return
    }
    if (fallo instanceof ErrorApi && fallo.estado === 403 && fallo.codigo === 'ERROR_API') {
      errorCierre.value = 'Tu sesión sigue activa. No se confirmó el cierre; inténtalo de nuevo.'
      return
    }
    errorCierre.value = 'No pudimos confirmar el cierre. Inténtalo de nuevo.'
  } finally {
    cerrando.value = false
  }
}
</script>

<template>
  <div class="layout-operador">
    <header class="barra-operador">
      <div class="marca-operador" role="img" aria-label="Smart Parking">
        <UIcon name="i-lucide-square-parking" aria-hidden="true" />
        <span>SMART PARKING</span>
      </div>

      <nav class="navegacion-operador" aria-label="Principal">
        <NuxtLink to="/operador" class="enlace-inicio-operador" aria-current="page">
          <UIcon name="i-lucide-house" aria-hidden="true" />
          <span>Inicio</span>
        </NuxtLink>
      </nav>

      <UButton
        color="neutral"
        variant="outline"
        icon="i-lucide-log-out"
        :loading="cerrando"
        :disabled="cerrando || revalidando"
        @click="cerrarSesion"
      >
        Cerrar sesión
      </UButton>
    </header>

    <p v-if="errorCierre" class="error-cierre-operador" role="alert">{{ errorCierre }}</p>

    <div class="contenido-layout-operador" :aria-busy="revalidando">
      <div v-if="revalidando || cargando" class="estado-sesion-operador" aria-live="polite">
        Comprobando tu acceso…
      </div>
      <div v-else-if="errorSesion || sesion.estado === 'error'" class="estado-sesion-operador">
        <p role="alert">
          {{ errorSesion || 'No pudimos comprobar tu acceso. Inténtalo de nuevo.' }}
        </p>
        <UButton color="neutral" variant="outline" @click="() => revalidarAcceso()">
          Reintentar
        </UButton>
      </div>
      <slot v-else-if="sesion.estado === 'autenticada' && sesion.identidad.rol === 'OPERADOR'" />
      <div v-else class="estado-sesion-operador" aria-live="polite">Comprobando tu acceso…</div>
    </div>
  </div>
</template>

<style scoped>
.layout-operador {
  display: flex;
  min-height: 100vh;
  flex-direction: column;
  background: var(--app-surface-hover);
  color: var(--app-foreground);
}

.barra-operador {
  display: flex;
  align-items: center;
  gap: 24px;
  border-bottom: 1px solid var(--app-border);
  padding: 14px clamp(16px, 4vw, 48px);
  background: var(--app-surface);
}

.marca-operador {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 10px;
  color: var(--app-foreground);
  font-size: 0.84rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-decoration: none;
}

.marca-operador :deep(svg) {
  color: var(--app-primary);
  font-size: 1.35rem;
}

.navegacion-operador {
  display: flex;
  flex: 1 1 auto;
  align-items: center;
  gap: 8px;
}

.enlace-inicio-operador {
  display: inline-flex;
  min-height: 42px;
  align-items: center;
  gap: 9px;
  border-radius: 8px;
  padding: 8px 12px;
  color: var(--app-primary);
  font-size: 0.92rem;
  font-weight: 700;
  text-decoration: none;
}

.enlace-inicio-operador:hover {
  background: var(--app-surface-hover);
}

.enlace-inicio-operador:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: 3px;
}

.error-cierre-operador {
  width: min(100% - 32px, 70rem);
  margin: 16px auto 0;
  color: var(--app-error);
}

.contenido-layout-operador {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
}

.estado-sesion-operador {
  display: flex;
  min-height: 40vh;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 24px;
  color: var(--app-muted);
  text-align: center;
}

.estado-sesion-operador p {
  margin: 0;
}

@media (max-width: 38rem) {
  .barra-operador {
    flex-wrap: wrap;
    gap: 10px 14px;
  }

  .navegacion-operador {
    order: 3;
    flex: 1 0 100%;
  }

  .barra-operador > :deep(button) {
    margin-left: auto;
  }
}
</style>
