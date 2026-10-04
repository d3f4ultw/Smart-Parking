import { computed } from 'vue'

import type { RespuestaSesion } from '~/utils/sesion'

const CLAVE_SESION_ACTUAL = 'sesion-actual'

export function useSesion() {
  const headers = import.meta.server ? useRequestHeaders(['cookie']) : undefined
  const estadoSesion = useAsyncData<RespuestaSesion | null>(
    CLAVE_SESION_ACTUAL,
    async () => {
      try {
        return await $fetch<RespuestaSesion>('/api/autenticacion/me', {
          credentials: 'same-origin',
          headers,
        })
      } catch {
        // Una respuesta no autenticada o un fallo del backend nunca debe
        // permitir que el cliente se trate como ADMIN.
        return null
      }
    },
    {
      default: () => null,
      dedupe: 'defer',
      immediate: false,
    },
  )

  const usuario = computed(() => estadoSesion.data.value?.usuario ?? null)
  const autenticado = computed(
    () => estadoSesion.data.value?.autenticado === true,
  )
  const cargando = computed(() => estadoSesion.status.value === 'pending')

  async function resolverSesion(opciones: { forzar?: boolean } = {}) {
    if (opciones.forzar) {
      await estadoSesion.refresh()
    } else if (estadoSesion.status.value === 'idle') {
      await estadoSesion.execute()
    }

    return autenticado.value
  }

  async function refrescarSesion() {
    await estadoSesion.refresh()
    return autenticado.value
  }

  function limpiarSesion() {
    estadoSesion.clear()
  }

  return {
    usuario,
    autenticado,
    cargando,
    resolverSesion,
    refrescarSesion,
    limpiarSesion,
  }
}
