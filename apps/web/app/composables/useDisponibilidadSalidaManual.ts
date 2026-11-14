import { computed, onMounted, onScopeDispose, ref, watch } from 'vue'
import type { Ref } from 'vue'
import { solicitarApi } from '~/utils/api'

/** Comprueba si se puede pedir una salida manual solo en la vista «Dentro», con sesión
 * autorizada, pestaña visible y conexión disponible. Espera dos segundos tras cada respuesta;
 * el dato vence en ocho segundos como máximo y esta consulta no abre el portón.
 */
export function useDisponibilidadSalidaManual(vista: Ref<'HISTORIAL' | 'DENTRO'>) {
  const ruta = useRoute()
  const { sesion } = useSesion()
  const disponible = ref(false)
  const comprobando = ref(false)
  let montado = false
  let generacion = 0
  let limiteVigencia = 0
  let peticion: AbortController | undefined
  let proximaConsulta: ReturnType<typeof setTimeout> | undefined
  let vencimiento: ReturnType<typeof setTimeout> | undefined

  const identidad = computed(() => {
    const actual = sesion.value
    if (vista.value !== 'DENTRO' || actual.estado !== 'autenticada') return null
    const { rol, correo } = actual.identidad
    const autorizada =
      (rol === 'DUENO' && ruta.path === '/admin/accesos') ||
      (rol === 'OPERADOR' && ruta.path === '/operador/accesos')
    return autorizada ? JSON.stringify([rol, correo, ruta.path]) : null
  })

  function detener() {
    generacion += 1
    peticion?.abort()
    peticion = undefined
    if (proximaConsulta) clearTimeout(proximaConsulta)
    if (vencimiento) clearTimeout(vencimiento)
    proximaConsulta = undefined
    vencimiento = undefined
    limiteVigencia = 0
    disponible.value = false
    comprobando.value = false
  }

  function accesible() {
    return (
      montado &&
      identidad.value !== null &&
      document.visibilityState === 'visible' &&
      navigator.onLine
    )
  }

  async function consultar() {
    if (!accesible() || peticion) return
    const turno = generacion
    const controlador = new AbortController()
    const inicio = performance.now()
    peticion = controlador
    comprobando.value = true
    try {
      const respuesta = await solicitarApi<unknown>('/api/v1/accesos/salidas-manuales/capacidad', {
        method: 'GET',
        retry: 0,
        timeout: 5000,
        signal: controlador.signal,
      })
      if (turno !== generacion || !accesible()) return
      const dato =
        respuesta && typeof respuesta === 'object' && !Array.isArray(respuesta)
          ? (respuesta as Record<string, unknown>)
          : null
      const restante =
        dato &&
        typeof dato.vigenciaRestanteMs === 'number' &&
        Number.isFinite(dato.vigenciaRestanteMs)
          ? Math.max(0, Math.min(8000, dato.vigenciaRestanteMs) - (performance.now() - inicio))
          : 0
      if (vencimiento) clearTimeout(vencimiento)
      disponible.value = dato?.disponible === true && restante > 0
      limiteVigencia = disponible.value ? performance.now() + restante : 0
      if (disponible.value)
        vencimiento = setTimeout(() => {
          disponible.value = false
        }, restante)
    } catch {
      if (turno === generacion) disponible.value = false
    } finally {
      if (turno === generacion) {
        peticion = undefined
        comprobando.value = false
        if (accesible()) proximaConsulta = setTimeout(() => void consultar(), 2000)
      }
    }
  }

  function reiniciar() {
    detener()
    if (accesible()) void consultar()
  }

  watch(identidad, reiniciar, { flush: 'sync' })
  onMounted(() => {
    montado = true
    document.addEventListener('visibilitychange', reiniciar)
    window.addEventListener('focus', reiniciar)
    window.addEventListener('online', reiniciar)
    window.addEventListener('offline', reiniciar)
    reiniciar()
  })
  onScopeDispose(() => {
    montado = false
    detener()
    if (import.meta.client) {
      document.removeEventListener('visibilitychange', reiniciar)
      window.removeEventListener('focus', reiniciar)
      window.removeEventListener('online', reiniciar)
      window.removeEventListener('offline', reiniciar)
    }
  })

  function disponibleAhora() {
    return montado && disponible.value && performance.now() < limiteVigencia && accesible()
  }

  return { disponible, comprobando, disponibleAhora }
}
