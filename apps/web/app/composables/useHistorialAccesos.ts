import { computed, getCurrentScope, onScopeDispose, watch } from 'vue'
import type {
  FiltroLectorAccesos,
  FiltroResultadoAccesos,
  PaginaHistorialAccesos,
  PeriodoHistorialAccesos,
} from '~/types/acceso'
import { ErrorHistorialAccesosApi, useClienteHistorialAccesos } from '~/utils/accesos-api'

type ResultadoHistorial =
  | { estado: 'listo'; datos: PaginaHistorialAccesos }
  | { estado: 'fallo'; mensaje: string; status: number }

const lectores: FiltroLectorAccesos[] = ['TODOS', 'RFID2', 'RFID3', 'MANUAL']
const resultados: FiltroResultadoAccesos[] = ['TODOS', 'AUTORIZADA', 'DENEGADA']
const periodos: PeriodoHistorialAccesos[] = [
  'HOY',
  'ULTIMOS_7_DIAS',
  'ULTIMOS_30_DIAS',
  'TODO',
  'PERSONALIZADO',
]
const PERIODO_PREDETERMINADO: PeriodoHistorialAccesos = 'ULTIMOS_7_DIAS'

function paginaValida(valor: unknown) {
  if (typeof valor !== 'string' || !/^[1-9]\d*$/.test(valor)) return '1'
  return Number.isSafeInteger(Number(valor)) ? valor : '1'
}

function filtroLector(valor: unknown): FiltroLectorAccesos {
  return typeof valor === 'string' && lectores.includes(valor as FiltroLectorAccesos)
    ? (valor as FiltroLectorAccesos)
    : 'TODOS'
}

function filtroResultado(valor: unknown): FiltroResultadoAccesos {
  return typeof valor === 'string' && resultados.includes(valor as FiltroResultadoAccesos)
    ? (valor as FiltroResultadoAccesos)
    : 'TODOS'
}

function filtroPeriodo(valor: unknown): PeriodoHistorialAccesos {
  return typeof valor === 'string' && periodos.includes(valor as PeriodoHistorialAccesos)
    ? (valor as PeriodoHistorialAccesos)
    : PERIODO_PREDETERMINADO
}

function fechaValida(valor: unknown): string | null {
  if (typeof valor !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(valor)) return null
  const fecha = new Date(`${valor}T00:00:00.000Z`)
  return Number.isNaN(fecha.getTime()) || fecha.toISOString().slice(0, 10) !== valor ? null : valor
}

/** Guarda en la dirección web los filtros de fecha, lector y resultado; muestra las horas
 * de la zona del estacionamiento y actualiza el historial cuando llegan avisos.
 */
export async function useHistorialAccesos() {
  const alcance = getCurrentScope()
  const route = useRoute()
  const router = useRouter()
  const api = useClienteHistorialAccesos()
  const { sesion, limpiar } = useSesion()
  const eventos = useNuxtApp().$eventosAdministracion
  const paginaSolicitada = computed(() => paginaValida(route.query.pagina))
  const lector = computed(() => filtroLector(route.query.lector))
  const resultado = computed(() => filtroResultado(route.query.resultado))
  const periodoSolicitado = computed(() => filtroPeriodo(route.query.periodo))
  const desdeSolicitado = computed(() => fechaValida(route.query.desde))
  const hastaSolicitado = computed(() => fechaValida(route.query.hasta))
  const periodo = computed(() => {
    if (
      periodoSolicitado.value === 'PERSONALIZADO' &&
      desdeSolicitado.value &&
      hastaSolicitado.value &&
      desdeSolicitado.value <= hastaSolicitado.value
    ) {
      return 'PERSONALIZADO'
    }
    return periodoSolicitado.value === 'PERSONALIZADO'
      ? PERIODO_PREDETERMINADO
      : periodoSolicitado.value
  })
  const desde = computed(() => (periodo.value === 'PERSONALIZADO' ? desdeSolicitado.value : null))
  const hasta = computed(() => (periodo.value === 'PERSONALIZADO' ? hastaSolicitado.value : null))
  const puedeConsultarHistorial = computed(() => {
    if (sesion.value.estado !== 'autenticada') return false
    const { rol } = sesion.value.identidad
    return (
      (rol === 'DUENO' && route.path === '/admin/accesos') ||
      (rol === 'OPERADOR' && route.path === '/operador/accesos')
    )
  })

  const { data, pending, refresh, clear } = await useAsyncData<ResultadoHistorial>(
    'historial-accesos-propietario',
    async (_nuxtApp, { signal }) => {
      const consulta = {
        pagina: paginaSolicitada.value,
        lector: lector.value,
        resultado: resultado.value,
        periodo: periodo.value,
        desde: desde.value,
        hasta: hasta.value,
      }
      try {
        const datos = await api.listar(
          consulta.pagina,
          consulta.lector,
          consulta.resultado,
          consulta.periodo,
          consulta.desde ?? undefined,
          consulta.hasta ?? undefined,
          signal,
        )
        if (
          signal.aborted ||
          !puedeConsultarHistorial.value ||
          consulta.pagina !== paginaSolicitada.value ||
          consulta.lector !== lector.value ||
          consulta.resultado !== resultado.value ||
          consulta.periodo !== periodo.value ||
          consulta.desde !== desde.value ||
          consulta.hasta !== hasta.value
        ) {
          throw new DOMException('La consulta cambió', 'AbortError')
        }
        return { estado: 'listo', datos }
      } catch (fallo) {
        if (signal.aborted || (fallo instanceof DOMException && fallo.name === 'AbortError')) {
          throw fallo
        }
        if (fallo instanceof ErrorHistorialAccesosApi && fallo.estado === 401) {
          await limpiar()
          if (import.meta.client) await navigateTo('/panel')
        }
        return {
          estado: 'fallo',
          mensaje:
            fallo instanceof ErrorHistorialAccesosApi
              ? fallo.message
              : 'No pudimos cargar el historial. Revisa tu conexión e inténtalo de nuevo.',
          status: fallo instanceof ErrorHistorialAccesosApi ? fallo.estado : 503,
        }
      }
    },
    {
      watch: [paginaSolicitada, lector, resultado, periodo, desde, hasta],
      dedupe: 'cancel',
      default: () => ({ estado: 'fallo', mensaje: '', status: 0 }) as ResultadoHistorial,
    },
  )

  const estadoCarga = computed(() => data.value as ResultadoHistorial)
  const pagina = computed(() =>
    estadoCarga.value.estado === 'listo' ? estadoCarga.value.datos : null,
  )
  const eventosAcceso = computed(() => pagina.value?.items ?? [])
  const paginaActual = computed(() => pagina.value?.pagina ?? Number(paginaSolicitada.value))
  const haySiguiente = computed(() => pagina.value?.haySiguiente ?? false)
  const mensajeError = computed(() =>
    estadoCarga.value.estado === 'fallo' && !pending.value ? estadoCarga.value.mensaje : '',
  )

  watch(pagina, (datos) => {
    if (!datos) return
    const ultimaPagina = Math.max(1, Math.ceil(datos.totalRegistros / datos.tamano))
    if (Number(paginaSolicitada.value) > ultimaPagina) void cambiarPagina(ultimaPagina)
  })

  let temporizador: ReturnType<typeof setTimeout> | undefined
  let cancelarSuscripcion: (() => void) | undefined
  let refrescoPendiente = false
  let escuchandoVisibilidad = false

  function programarRefresco() {
    if (temporizador || !puedeConsultarHistorial.value) return
    temporizador = setTimeout(() => {
      temporizador = undefined
      if (!puedeConsultarHistorial.value) return
      if (pending.value) {
        refrescoPendiente = true
        return
      }
      void refresh()
    }, 100)
  }

  watch(pending, (estaCargando) => {
    if (!estaCargando && refrescoPendiente) {
      refrescoPendiente = false
      programarRefresco()
    }
  })

  function construirConsulta(
    paginaDestino: number,
    lectorDestino: FiltroLectorAccesos,
    resultadoDestino: FiltroResultadoAccesos,
    periodoDestino: PeriodoHistorialAccesos,
    desdeDestino: string | null = null,
    hastaDestino: string | null = null,
  ) {
    const query = { ...route.query }
    delete query.pagina
    delete query.lector
    delete query.resultado
    delete query.periodo
    delete query.desde
    delete query.hasta
    if (paginaDestino > 1) query.pagina = String(paginaDestino)
    if (lectorDestino !== 'TODOS') query.lector = lectorDestino
    if (resultadoDestino !== 'TODOS') query.resultado = resultadoDestino
    if (periodoDestino !== PERIODO_PREDETERMINADO) query.periodo = periodoDestino
    if (periodoDestino === 'PERSONALIZADO' && desdeDestino && hastaDestino) {
      query.desde = desdeDestino
      query.hasta = hastaDestino
    }
    return query
  }

  async function cambiarPagina(destino: number) {
    await router.push({
      query: construirConsulta(
        Math.max(1, Math.trunc(destino)),
        lector.value,
        resultado.value,
        periodo.value,
        desde.value,
        hasta.value,
      ),
    })
  }

  async function cambiarLector(destino: FiltroLectorAccesos) {
    await router.push({
      query: construirConsulta(
        1,
        destino,
        resultado.value,
        periodo.value,
        desde.value,
        hasta.value,
      ),
    })
  }

  async function cambiarResultado(destino: FiltroResultadoAccesos) {
    await router.push({
      query: construirConsulta(1, lector.value, destino, periodo.value, desde.value, hasta.value),
    })
  }

  async function cambiarPeriodo(destino: PeriodoHistorialAccesos) {
    if (destino === 'PERSONALIZADO') return
    await router.push({
      query: construirConsulta(1, lector.value, resultado.value, destino),
    })
  }

  async function cambiarRango(desdeDestino: string, hastaDestino: string) {
    if (!fechaValida(desdeDestino) || !fechaValida(hastaDestino) || desdeDestino > hastaDestino)
      return
    await router.push({
      query: construirConsulta(
        1,
        lector.value,
        resultado.value,
        'PERSONALIZADO',
        desdeDestino,
        hastaDestino,
      ),
    })
  }

  async function limpiarFiltros() {
    await router.push({
      query: construirConsulta(1, 'TODOS', 'TODOS', PERIODO_PREDETERMINADO),
    })
  }

  function actualizarAlVolver() {
    if (document.visibilityState === 'visible') programarRefresco()
  }

/** Escucha los cambios posteriores a la última carga y vuelve a pedir el historial
 * si llega un aviso o si pudo perderse alguno durante una interrupción.
 */
  function iniciarEventos() {
    detenerEventos()
    let requiereReconciliacion = false
    cancelarSuscripcion = eventos.suscribir(
      programarRefresco,
      pagina.value?.cursorEventos ?? undefined,
      'acceso.historial.actualizado',
      (requerida) => {
        requiereReconciliacion = requerida
      },
    )
    window.addEventListener('focus', programarRefresco)
    document.addEventListener('visibilitychange', actualizarAlVolver)
    escuchandoVisibilidad = true
    if (requiereReconciliacion) programarRefresco()
  }

  function detenerEventos() {
    cancelarSuscripcion?.()
    cancelarSuscripcion = undefined
    if (temporizador) clearTimeout(temporizador)
    temporizador = undefined
    refrescoPendiente = false
    if (escuchandoVisibilidad && import.meta.client) {
      window.removeEventListener('focus', programarRefresco)
      document.removeEventListener('visibilitychange', actualizarAlVolver)
      escuchandoVisibilidad = false
    }
  }

  function limpiarSesion() {
    detenerEventos()
    clear()
  }

  alcance?.run(() => {
    watch(
      puedeConsultarHistorial,
      (actual) => {
        if (!actual) limpiarSesion()
      },
      { flush: 'sync' },
    )
    onScopeDispose(detenerEventos)
  })

  return {
    eventosAcceso,
    haySiguiente,
    lector,
    mensajeError,
    pagina,
    paginaActual,
    pending,
    resultado,
    periodo,
    desde,
    hasta,
    recargar: () => refresh(),
    iniciarEventos,
    detenerEventos,
    cambiarPagina,
    cambiarLector,
    cambiarResultado,
    cambiarPeriodo,
    cambiarRango,
    limpiarFiltros,
  }
}
