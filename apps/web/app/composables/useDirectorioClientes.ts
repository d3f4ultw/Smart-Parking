import { computed, onScopeDispose, ref, watch } from 'vue'
import type { EstadoFiltroClientes, PaginaClientesAdministracion } from '~/types/cliente-admin'
import {
  ErrorClientesAdministracionApi,
  useClienteAdministracionClientes,
} from '~/utils/clientes-admin-api'

type ResultadoDirectorio =
  | { estado: 'listo'; datos: PaginaClientesAdministracion }
  | { estado: 'fallo'; mensaje: string; status: number }

const estadosPermitidos: EstadoFiltroClientes[] = ['todos', 'sin-membresia', 'activa', 'cancelada']
const DEMORA_BUSQUEDA_MS = 300

function esEstadoFiltro(valor: unknown): valor is EstadoFiltroClientes {
  return typeof valor === 'string' && estadosPermitidos.includes(valor as EstadoFiltroClientes)
}

function normalizarBusqueda(valor: string) {
  return valor.trim().replace(/\s+/g, ' ')
}

/** Mantiene la página, el estado de membresía y la búsqueda en la dirección web;
 * espera brevemente al escribir y actualiza la lista cuando llegan avisos de cambios.
 */
export async function useDirectorioClientes() {
  const route = useRoute()
  const router = useRouter()
  const cliente = useClienteAdministracionClientes()
  const sesion = useSesion()
  const eventos = useNuxtApp().$eventosAdministracion
  let temporizadorBusqueda: ReturnType<typeof setTimeout> | undefined
  const paginaSolicitada = computed(() => {
    const valor = route.query.pagina
    return typeof valor === 'string' && /^[1-9][0-9]*$/.test(valor) ? valor : '1'
  })
  const estado = computed<EstadoFiltroClientes>(() =>
    esEstadoFiltro(route.query.estado) ? route.query.estado : 'todos',
  )
  const busquedaSolicitada = computed(() => {
    const valor = route.query.busqueda
    return typeof valor === 'string' ? normalizarBusqueda(valor) : ''
  })
  const busqueda = ref(busquedaSolicitada.value)

  function cancelarBusquedaPendiente() {
    if (temporizadorBusqueda) clearTimeout(temporizadorBusqueda)
    temporizadorBusqueda = undefined
  }

  watch(busquedaSolicitada, (valor) => {
    if (normalizarBusqueda(busqueda.value) === valor) return
    cancelarBusquedaPendiente()
    busqueda.value = valor
  })

  const { data, pending, refresh, clear } = await useAsyncData<ResultadoDirectorio>(
    'directorio-administracion-clientes',
    async (_nuxtApp, { signal }) => {
      const paginaOriginal = paginaSolicitada.value
      const estadoOriginal = estado.value
      const busquedaOriginal = busquedaSolicitada.value
      try {
        let datos = await cliente.listar(paginaOriginal, estadoOriginal, signal, busquedaOriginal)
        if (signal.aborted) throw new DOMException('Solicitud cancelada', 'AbortError')
        if (
          paginaOriginal !== paginaSolicitada.value ||
          estadoOriginal !== estado.value ||
          busquedaOriginal !== busquedaSolicitada.value
        ) {
          throw new DOMException('La consulta cambió', 'AbortError')
        }

        const totalPaginas =
          Number.isInteger(datos.totalPaginas) && datos.totalPaginas > 0 ? datos.totalPaginas : 1
        const paginaRespuesta =
          Number.isInteger(datos.pagina) && datos.pagina > 0 ? datos.pagina : 1
        const paginaCanonica = Math.min(paginaRespuesta, totalPaginas)
        if (paginaCanonica !== Number(paginaOriginal)) {
          datos = await cliente.listar(
            String(paginaCanonica),
            estadoOriginal,
            signal,
            busquedaOriginal,
          )
          if (
            signal.aborted ||
            paginaOriginal !== paginaSolicitada.value ||
            estadoOriginal !== estado.value ||
            busquedaOriginal !== busquedaSolicitada.value
          ) {
            throw new DOMException('La consulta cambió', 'AbortError')
          }
        }
        return { estado: 'listo', datos }
      } catch (fallo) {
        if (signal.aborted || (fallo instanceof DOMException && fallo.name === 'AbortError')) {
          throw fallo
        }
        if (fallo instanceof ErrorClientesAdministracionApi && fallo.estado === 401) {
          await sesion.limpiar()
          if (import.meta.client) await navigateTo('/panel')
        }
        const mensaje =
          fallo instanceof ErrorClientesAdministracionApi
            ? fallo.message
            : 'No pudimos cargar la lista de clientes. Revisa tu conexión e inténtalo de nuevo.'
        const status = fallo instanceof ErrorClientesAdministracionApi ? fallo.estado : 503
        return { estado: 'fallo', mensaje, status }
      }
    },
    {
      watch: [paginaSolicitada, estado, busquedaSolicitada],
      dedupe: 'cancel',
      default: () =>
        ({ estado: 'fallo', mensaje: 'Cargando clientes…', status: 0 }) as ResultadoDirectorio,
    },
  )

  const resultado = computed(() => data.value as ResultadoDirectorio)
  const directorio = computed(() =>
    resultado.value.estado === 'listo' ? resultado.value.datos : null,
  )
  const clientes = computed(() => directorio.value?.items ?? [])
  const paginaActual = computed(() => directorio.value?.pagina ?? Number(paginaSolicitada.value))
  const totalClientes = computed(() => directorio.value?.totalClientes ?? 0)
  const totalRegistros = computed(() => directorio.value?.totalRegistros ?? 0)
  const totalPaginas = computed(() => directorio.value?.totalPaginas ?? 0)
  const mensajeError = computed(() =>
    resultado.value.estado === 'fallo' && !pending.value ? resultado.value.mensaje : '',
  )

  let temporizador: ReturnType<typeof setTimeout> | undefined
  let cancelarSuscripciones: Array<() => void> = []

  function programarRefresco() {
    if (temporizador) clearTimeout(temporizador)
    temporizador = setTimeout(() => {
      temporizador = undefined
      void refresh()
    }, 100)
  }

  function obtenerConsulta(
    pagina: number,
    filtro: EstadoFiltroClientes,
    busquedaActual = busqueda.value,
  ) {
    const query = { ...route.query }
    delete query.pagina
    delete query.estado
    delete query.busqueda
    if (pagina > 1) query.pagina = String(pagina)
    if (filtro !== 'todos') query.estado = filtro
    const consulta = normalizarBusqueda(busquedaActual)
    if (consulta) query.busqueda = consulta
    return query
  }

  async function cambiarPagina(pagina: number) {
    const busquedaPendiente = normalizarBusqueda(busqueda.value) !== busquedaSolicitada.value
    cancelarBusquedaPendiente()
    const destino = busquedaPendiente ? 1 : Math.max(1, Math.trunc(pagina))
    await router.push({ query: obtenerConsulta(destino, estado.value) })
  }

  async function cambiarEstado(filtro: EstadoFiltroClientes) {
    cancelarBusquedaPendiente()
    await router.push({ query: obtenerConsulta(1, filtro) })
  }

  function cambiarBusqueda(valor: string) {
    busqueda.value = valor
    cancelarBusquedaPendiente()
    if (normalizarBusqueda(valor) === busquedaSolicitada.value) return
    temporizadorBusqueda = setTimeout(() => {
      temporizadorBusqueda = undefined
      void router.replace({ query: obtenerConsulta(1, estado.value, valor) })
    }, DEMORA_BUSQUEDA_MS)
  }

  async function limpiarBusqueda() {
    cancelarBusquedaPendiente()
    busqueda.value = ''
    await router.replace({ query: obtenerConsulta(1, estado.value, '') })
  }

  async function sincronizarUrl(pagina: PaginaClientesAdministracion | null) {
    if (!pagina) return
    const numeroPagina = Math.max(1, pagina.pagina)
    const query = obtenerConsulta(numeroPagina, estado.value, busquedaSolicitada.value)
    const paginaUrl = numeroPagina > 1 ? String(numeroPagina) : undefined
    const estadoUrl = estado.value === 'todos' ? undefined : estado.value
    const busquedaUrl = busquedaSolicitada.value || undefined
    if (
      route.query.pagina === paginaUrl &&
      route.query.estado === estadoUrl &&
      route.query.busqueda === busquedaUrl
    )
      return
    if (import.meta.server) {
      await navigateTo({ path: route.path, query }, { redirectCode: 302 })
    } else {
      await router.replace({ query })
    }
  }

  function iniciarEventos(refrescarDetalle?: () => void) {
    detenerEventos()
    const cursor = directorio.value?.cursorEventos ?? undefined
    const invalidar = () => {
      programarRefresco()
      refrescarDetalle?.()
    }
    cancelarSuscripciones = [
      eventos.suscribir(invalidar, cursor, 'cliente.registrado'),
      eventos.suscribir(invalidar, cursor, 'membresia.actualizada'),
    ]
  }

  function detenerEventos() {
    cancelarSuscripciones.forEach((cancelar) => cancelar())
    cancelarSuscripciones = []
    if (temporizador) clearTimeout(temporizador)
    temporizador = undefined
    cancelarBusquedaPendiente()
  }

  function limpiarSesion() {
    detenerEventos()
    clear()
  }

  onScopeDispose(detenerEventos)

  if (import.meta.server) await sincronizarUrl(directorio.value)

  return {
    clientes,
    directorio,
    estado,
    busqueda,
    pending,
    mensajeError,
    paginaActual,
    totalClientes,
    totalRegistros,
    totalPaginas,
    recargar: () => refresh(),
    programarRefresco,
    cambiarPagina,
    cambiarEstado,
    cambiarBusqueda,
    limpiarBusqueda,
    iniciarEventos,
    detenerEventos,
    limpiarSesion,
    sincronizarUrl,
  }
}
