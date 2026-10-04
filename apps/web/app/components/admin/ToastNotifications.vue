<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'

const { toasts, descartarToast, limpiarToasts } = useAdminToasts()
const route = useRoute()
const temporizadores = new Map<number, ReturnType<typeof setTimeout>>()

watch(toasts, (notificaciones) => {
  const idsActivos = new Set(notificaciones.map((toast) => toast.id))

  for (const [id, temporizador] of temporizadores) {
    if (!idsActivos.has(id)) {
      clearTimeout(temporizador)
      temporizadores.delete(id)
    }
  }

  for (const toast of notificaciones) {
    if (temporizadores.has(toast.id)) {
      continue
    }

    const duracion = 2500
    temporizadores.set(
      toast.id,
      setTimeout(() => descartarToast(toast.id), duracion),
    )
  }
}, { deep: true })

watch(
  [() => route.path, () => route.query.pagina],
  () => limpiarToasts(),
)

onBeforeUnmount(() => {
  for (const temporizador of temporizadores.values()) {
    clearTimeout(temporizador)
  }
  temporizadores.clear()
  limpiarToasts()
})
</script>

<template>
  <Teleport to="body">
    <div class="toast-stack">
      <TransitionGroup name="toast">
        <div
          v-for="toast in toasts"
          :key="toast.id"
          class="toast"
          :class="`toast--${toast.tipo}`"
          :role="toast.tipo === 'error' ? 'alert' : 'status'"
          aria-atomic="true"
        >
          <span class="toast-icon" aria-hidden="true">
            <svg v-if="toast.tipo === 'success'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="m5 12 4 4L19 6" />
            </svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 8v5m0 3h.01" />
            </svg>
          </span>
          <p>{{ toast.mensaje }}</p>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-stack {
  position: fixed;
  z-index: 200;
  right: max(1.25rem, env(safe-area-inset-right));
  bottom: max(1.25rem, env(safe-area-inset-bottom));
  display: grid;
  width: min(25rem, calc(100vw - 2.5rem));
  gap: 0.75rem;
  --toast-accent: #5c3a86;
  --toast-error-accent: #67456e;
  --toast-border: #e8e3ed;
  --toast-foreground: #3c3542;
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  min-height: 4.25rem;
  padding: 0.8rem 1rem 0.8rem 0.9rem;
  color: var(--toast-foreground);
  background: #ffffff;
  border: 1px solid var(--toast-border);
  border-inline-start: 3px solid var(--toast-accent);
  border-radius: 0.9rem;
  box-shadow: 0 0.75rem 1.75rem rgb(37 28 47 / 13%), 0 0.15rem 0.4rem rgb(37 28 47 / 6%);
  font-size: 0.875rem;
  line-height: 1.45;
  pointer-events: auto;
}

.toast--error {
  border-inline-start-color: var(--toast-error-accent);
}

.toast-icon {
  display: grid;
  width: 2.15rem;
  height: 2.15rem;
  flex: 0 0 auto;
  place-items: center;
  color: var(--toast-accent);
  background: #f4eff8;
  border: 1px solid #ebe3f2;
  border-radius: 0.7rem;
}

.toast--error .toast-icon {
  color: var(--toast-error-accent);
  background: #f4f0f5;
  border-color: #e9e1ec;
}

.toast-icon svg {
  width: 100%;
  height: 100%;
}

.toast p {
  margin: 0;
}

.toast-enter-active,
.toast-leave-active,
.toast-move {
  transition: opacity 180ms ease, transform 180ms ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(0.45rem);
}

.toast-leave-active {
  position: absolute;
  inset-inline: 0;
}

@media (max-width: 38rem) {
  .toast-stack {
    right: max(0.75rem, env(safe-area-inset-right));
    bottom: max(0.75rem, env(safe-area-inset-bottom));
    left: max(0.75rem, env(safe-area-inset-left));
    width: auto;
  }
}

@media (prefers-reduced-motion: reduce) {
  .toast-enter-active,
  .toast-leave-active,
  .toast-move {
    transition: none;
  }
}
</style>
