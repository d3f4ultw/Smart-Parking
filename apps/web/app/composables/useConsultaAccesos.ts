import { computed, getCurrentScope, onMounted, onScopeDispose, ref, watch } from 'vue'
import type { ComputedRef } from 'vue'
import { ErrorAccesosApi } from '~/utils/capacidad-rfid-api'

type TemaAcceso =
  | 'acceso.historial.actualizado'
  | 'vision.ocupacion.actualizada'
  | 'rfid1.tarjetas.actualizadas'

interface ConCursor {
  cursorEventos: string | null
}

interface ResultadoConsulta<T> {
  estado: 'cargando' | 'actual' | 'error' | 'sin-acceso'
  datos: T | null
  mensaje: string
  revision: number
}

interface OpcionesConsulta<T> {
  clave: string
  criterio: ComputedRef<string | null>
  consultar: (signal: AbortSignal) => Promise<T>
  temas: TemaAcceso[]
  inmediata: boolean
}

function resultadoInicial<T>(): ResultadoConsulta<T> {
  return { estado: 'cargando', datos: null, mensaje: '', revision: 0 }
}

/** Reúne las consultas que usan el aforo y la lista de vehículos dentro;
 * las detiene al cambiar de persona o salir de la página y vuelve a consultar
 * cuando llegan avisos o se recupera la conexión. También se pausa si la pestaña
 * está oculta o el equipo no tiene conexión.
 */
export async function useConsultaAccesos<T extends ConCursor>(opciones: OpcionesConsulta<T>) {
  const alcance = getCurrentScope()
  const eventos = useNuxtApp().$eventosAdministracion
  const { limpiar: limpiarSesion } = useSesion()
  let revision = 0
  let montar = () => {}
  let desmontar = () => {}
  onMounted(() => montar())
  onScopeDispose(() => desmontar())

  const consulta = await useAsyncData<ResultadoConsulta<T>>(
    opciones.clave,
    async (_nuxtApp, { signal }) => {
      const criterio = opciones.criterio.value
      const revisionConsulta = revision
      if (!criterio)
        return { estado: 'sin-acceso', datos: null, mensaje: '', revision: revisionConsulta }
      try {
        const datos = await opciones.consultar(signal)
        if (signal.aborted || opciones.criterio.value !== criterio) {
          throw new DOMException('La consulta cambió', 'AbortError')
        }
        return { estado: 'actual', datos, mensaje: '', revision: revisionConsulta }
      } catch (fallo) {
        if (signal.aborted || opciones.criterio.value !== criterio) throw fallo
        if (fallo instanceof ErrorAccesosApi && fallo.estado === 401) {
          await limpiarSesion()
          if (import.meta.client) await navigateTo('/panel')
          return {
            estado: 'sin-acceso',
            datos: null,
            mensaje: fallo.message,
            revision: revisionConsulta,
          }
        }
        if (fallo instanceof ErrorAccesosApi && fallo.estado === 403) {
          return {
            estado: 'sin-acceso',
            datos: null,
            mensaje: fallo.message,
            revision: revisionConsulta,
          }
        }
        return {
          estado: 'error',
          datos: null,
          mensaje:
            fallo instanceof ErrorAccesosApi
              ? fallo.message
              : 'No pudimos actualizar la información. Revisa tu conexión e inténtalo de nuevo.',
          revision: revisionConsulta,
        }
      }
    },
    {
      default: resultadoInicial<T>,
      dedupe: 'defer',
      immediate: opciones.inmediata,
    },
  )

  const datos = computed(() => (consulta.data.value as ResultadoConsulta<T>).datos)
  const estado = computed(() => (consulta.data.value as ResultadoConsulta<T>).estado)
  const mensajeError = computed(() => (consulta.data.value as ResultadoConsulta<T>).mensaje)
  const desactualizado = ref(false)
  let montado = false
  let conexionInterrumpida = false
  let esperandoRetorno = false
  let generacion = 0
  let cancelaEventos: Array<() => void> = []
  let temporizador: ReturnType<typeof setTimeout> | undefined
  let reconciliacion: ReturnType<typeof setInterval> | undefined
  let refrescoPendiente = false

  function marcarDesactualizado() {
    revision += 1
    desactualizado.value = true
  }

  function disponible() {
    return document.visibilityState === 'visible' && navigator.onLine
  }

  function accesoDenegado() {
    return estado.value === 'sin-acceso'
  }

  function cancelarEventos() {
    cancelaEventos.forEach((cancelar) => cancelar())
    cancelaEventos = []
    if (temporizador) clearTimeout(temporizador)
    temporizador = undefined
    refrescoPendiente = false
  }

  function puedeConsultar() {
    return (
      montado && opciones.criterio.value !== null && estado.value !== 'sin-acceso' && disponible()
    )
  }

  function solicitarRefresco() {
    if (!puedeConsultar()) return
    if (consulta.pending.value) {
      refrescoPendiente = true
      return
    }
    if (temporizador) return
    temporizador = setTimeout(() => {
      temporizador = undefined
      if (puedeConsultar()) void consulta.refresh()
    }, 100)
  }

  async function iniciar() {
    const turno = ++generacion
    if (!montado || opciones.criterio.value === null) return
    if (!disponible()) {
      esperandoRetorno = true
      marcarDesactualizado()
      return
    }
    if (accesoDenegado()) return
    if (estado.value !== 'actual') await consulta.refresh()
    if (turno !== generacion || !montado || opciones.criterio.value === null) return
    if (accesoDenegado() || !disponible()) return
    const cursorInicial = datos.value?.cursorEventos ?? undefined
    for (const tema of opciones.temas) {
      let requiereReconciliacion = false
      cancelaEventos.push(
        eventos.suscribir(
          () => {
            marcarDesactualizado()
            solicitarRefresco()
          },
          cursorInicial,
          tema,
          (requerida) => {
            requiereReconciliacion = requerida
          },
          {
            interrumpida: () => {
              conexionInterrumpida = true
              marcarDesactualizado()
            },
            recuperada: () => {
              conexionInterrumpida = false
              marcarDesactualizado()
              solicitarRefresco()
            },
          },
        ),
      )
      if (requiereReconciliacion) {
        marcarDesactualizado()
        solicitarRefresco()
      }
    }
  }

  function alCambiarDisponibilidad() {
    if (!disponible()) {
      if (!esperandoRetorno && opciones.criterio.value !== null) marcarDesactualizado()
      esperandoRetorno = true
      return
    }
    if (esperandoRetorno) {
      esperandoRetorno = false
      if (!cancelaEventos.length) void iniciar()
    }
    solicitarRefresco()
  }

  montar = () => {
    montado = true
    document.addEventListener('visibilitychange', alCambiarDisponibilidad)
    window.addEventListener('focus', alCambiarDisponibilidad)
    window.addEventListener('online', alCambiarDisponibilidad)
    window.addEventListener('offline', alCambiarDisponibilidad)
    reconciliacion = setInterval(solicitarRefresco, 30_000)
    void iniciar()
  }

  desmontar = () => {
    montado = false
    generacion += 1
    cancelarEventos()
    if (reconciliacion) clearInterval(reconciliacion)
    document.removeEventListener('visibilitychange', alCambiarDisponibilidad)
    window.removeEventListener('focus', alCambiarDisponibilidad)
    window.removeEventListener('online', alCambiarDisponibilidad)
    window.removeEventListener('offline', alCambiarDisponibilidad)
    consulta.clear()
  }

  alcance?.run(() => {
    watch(
      opciones.criterio,
      (actual, anterior) => {
        if (actual === anterior) return
        generacion += 1
        cancelarEventos()
        consulta.clear()
        conexionInterrumpida = false
        esperandoRetorno = false
        revision += 1
        desactualizado.value = false
        if (montado && actual !== null) void iniciar()
      },
      { flush: 'sync' },
    )
    watch(consulta.pending, (pendiente) => {
      if (!pendiente && refrescoPendiente) {
        refrescoPendiente = false
        solicitarRefresco()
      }
    })
    watch(consulta.data, () => {
      if (
        estado.value === 'actual' &&
        (consulta.data.value as ResultadoConsulta<T>).revision === revision &&
        !conexionInterrumpida &&
        !esperandoRetorno &&
        disponible()
      )
        desactualizado.value = false
      if (estado.value === 'sin-acceso') cancelarEventos()
    })
  })

  return {
    datos,
    estado,
    mensajeError,
    desactualizado,
    pendiente: consulta.pending,
    actualizar: () => consulta.refresh(),
  }
}
