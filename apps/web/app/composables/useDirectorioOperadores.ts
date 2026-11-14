import { computed, ref } from 'vue'
import type { FiltroEstadoOperador, PaginaOperadores } from '~/types/operador'
import { ErrorOperadoresApi, useClienteOperadores } from '~/utils/operadores-api'

interface SolicitudDirectorio {
  pagina: string
  busqueda: string
  estado: FiltroEstadoOperador
}

type ResultadoDirectorio =
  | { estado: 'listo'; clave: string; datos: PaginaOperadores }
  | { estado: 'fallo'; clave: string; mensaje: string; status: number }

function numeroPagina(valor: unknown) {
  if (typeof valor !== 'string' || !/^[1-9]\d*$/.test(valor)) return 1
  const numero = Number(valor)
  return Number.isSafeInteger(numero) ? numero : 1
}

function claveSolicitud(solicitud: SolicitudDirectorio) {
  return JSON.stringify(solicitud)
}

/** Mantiene la búsqueda, el estado y la página de las cuentas de operador;
 * vuelve a cargar la lista cuando recibe avisos de cambios.
 */
export async function useDirectorioOperadores() {
  const route = useRoute()
  const router = useRouter()
  const cliente = useClienteOperadores()
  const { limpiar } = useSesion()
  const eventos = useNuxtApp().$eventosAdministracion
  const busqueda = ref('')
  const estado = ref<FiltroEstadoOperador>('TODOS')
  const busquedaAplicada = ref('')
  const estadoAplicado = ref<FiltroEstadoOperador>('TODOS')
  const busquedaPendiente = ref(false)
  const errorBusqueda = ref('')
  const paginaSolicitada = computed(() => String(numeroPagina(route.query.pagina)))
  const solicitudActual = computed<SolicitudDirectorio>(() => ({
    pagina: paginaSolicitada.value,
    busqueda: busquedaAplicada.value,
    estado: estadoAplicado.value,
  }))
  const claveActual = computed(() => claveSolicitud(solicitudActual.value))
  let temporizadorBusqueda: ReturnType<typeof setTimeout> | undefined
  let temporizadorRefresco: ReturnType<typeof setTimeout> | undefined
  let suspenderConsultas = false
  let cancelarSuscripcion = () => {}

  const { data, pending, refresh, clear } = await useAsyncData<ResultadoDirectorio>(
    'directorio-operadores',
    async (_nuxtApp, { signal }) => {
      const solicitud = { ...solicitudActual.value }
      const clave = claveSolicitud(solicitud)
      try {
        const datos = await cliente.listar(
          solicitud.pagina,
          solicitud.busqueda,
          solicitud.estado,
          signal,
        )
        if (signal.aborted) throw new DOMException('Consulta cancelada.', 'AbortError')
        // La lista muestra los datos básicos; el correo se consulta al abrir la ficha de una cuenta.
        const datosSinCorreos = {
          ...datos,
          items: datos.items.map((operador) => ({ ...operador, correo: '' })),
        }
        return { estado: 'listo', clave, datos: datosSinCorreos }
      } catch (fallo) {
        if (signal.aborted) throw fallo
        if (fallo instanceof ErrorOperadoresApi && fallo.estado === 401) {
          await limpiar()
          if (import.meta.client) await navigateTo('/panel')
        }
        const mensaje =
          fallo instanceof ErrorOperadoresApi
            ? fallo.message
            : 'No pudimos cargar la lista. Revisa tu conexión e inténtalo de nuevo.'
        return {
          estado: 'fallo',
          clave,
          mensaje,
          status: fallo instanceof ErrorOperadoresApi ? fallo.estado : 503,
        }
      }
    },
    {
      dedupe: 'cancel',
      default: (): ResultadoDirectorio => ({
        estado: 'fallo',
        clave: '',
        mensaje: 'Cargando la lista…',
        status: 0,
      }),
    },
  )

  const resultado = computed(() => data.value as ResultadoDirectorio)
  const resultadoVigente = computed(() =>
    resultado.value.clave === claveActual.value ? resultado.value : null,
  )
  const directorio = computed(() =>
    resultadoVigente.value?.estado === 'listo' ? resultadoVigente.value.datos : null,
  )
  const operadores = computed(() => directorio.value?.items ?? [])
  const paginaActual = computed(() => directorio.value?.pagina ?? 1)
  const tamanoPagina = computed(() => directorio.value?.tamanoPagina ?? 10)
  const totalRegistros = computed(() => directorio.value?.totalRegistros ?? 0)
  const totalPaginas = computed(() => directorio.value?.totalPaginas ?? 0)
  const pendingFiltro = computed(() => pending.value || busquedaPendiente.value)
  const mensajeError = computed(() => {
    const actual = resultadoVigente.value
    return actual?.estado === 'fallo' && !pendingFiltro.value ? actual.mensaje : ''
  })
  const filtrosActivos = computed(
    () => Boolean(busquedaAplicada.value) || estadoAplicado.value !== 'TODOS',
  )

  async function cambiarPagina(pagina: number) {
    if (!Number.isSafeInteger(pagina) || pagina < 1) return
    const destino = pagina <= 1 ? undefined : String(pagina)
    const actual = route.query.pagina ?? undefined
    if (actual === destino) return
    cancelarRefrescoProgramado()
    await router.push({ query: { ...route.query, pagina: destino } })
  }

  async function reemplazarPaginaCanonica(pagina: number) {
    const destino = pagina <= 1 ? undefined : String(pagina)
    const query = { ...route.query }
    if (destino) query.pagina = destino
    else delete query.pagina
    if ((route.query.pagina ?? undefined) === destino) return
    if (import.meta.server) {
      await navigateTo({ path: route.path, query }, { redirectCode: 302 })
    } else {
      await router.replace({ path: route.path, query })
    }
  }

  async function sincronizarPagina(pagina: PaginaOperadores | null) {
    if (!pagina) return
    await reemplazarPaginaCanonica(pagina.pagina)
  }

  const paginaInicial = directorio.value?.pagina
  if (paginaInicial !== undefined) await sincronizarPagina(directorio.value)

  watch(
    directorio,
    (pagina) => {
      if (pagina) void sincronizarPagina(pagina)
    },
    { flush: 'post' },
  )

  watch(
    [paginaSolicitada, busquedaAplicada, estadoAplicado],
    () => {
      if (!suspenderConsultas) void refresh()
    },
    { flush: 'sync' },
  )

  function cancelarDebounceBusqueda() {
    if (temporizadorBusqueda) clearTimeout(temporizadorBusqueda)
    temporizadorBusqueda = undefined
    busquedaPendiente.value = false
  }

  async function aplicarCriterios() {
    cancelarDebounceBusqueda()
    const nuevaBusqueda = busqueda.value.trim().slice(0, 254)
    const nuevoEstado = estado.value
    if (nuevaBusqueda === busquedaAplicada.value && nuevoEstado === estadoAplicado.value) return
    suspenderConsultas = true
    busquedaAplicada.value = nuevaBusqueda
    estadoAplicado.value = nuevoEstado
    await reemplazarPaginaCanonica(1)
    suspenderConsultas = false
    await refresh()
  }

  function cambiarBusqueda(valor: string) {
    busqueda.value = valor.slice(0, 254)
    cancelarDebounceBusqueda()
    if (valor.includes('@')) {
      errorBusqueda.value = 'Busca por nombre o apellido; no escribas correos.'
      return
    }
    errorBusqueda.value = ''
    busquedaPendiente.value = true
    temporizadorBusqueda = setTimeout(() => void aplicarCriterios(), 300)
  }

  function cambiarEstado(valor: FiltroEstadoOperador) {
    if (estado.value === valor && estadoAplicado.value === valor) return
    estado.value = valor
    void aplicarCriterios()
  }

  function limpiarFiltros() {
    busqueda.value = ''
    errorBusqueda.value = ''
    estado.value = 'TODOS'
    void aplicarCriterios()
  }

  function cancelarRefrescoProgramado() {
    if (temporizadorRefresco) clearTimeout(temporizadorRefresco)
    temporizadorRefresco = undefined
  }

  function programarRefresco() {
    cancelarRefrescoProgramado()
    temporizadorRefresco = setTimeout(() => {
      temporizadorRefresco = undefined
      void refresh()
    }, 100)
  }

  function iniciarEventos(reaccion: () => void = programarRefresco) {
    detenerEventos()
    cancelarSuscripcion = eventos.suscribir(
      reaccion,
      directorio.value?.cursorEventos,
      'operador.directorio.actualizado',
    )
  }

  function detenerEventos() {
    cancelarSuscripcion()
    cancelarSuscripcion = () => {}
    cancelarRefrescoProgramado()
    cancelarDebounceBusqueda()
  }

  function limpiarSesion() {
    detenerEventos()
    clear()
  }

  return {
    operadores,
    directorio,
    pending: pendingFiltro,
    mensajeError,
    paginaActual,
    tamanoPagina,
    totalRegistros,
    totalPaginas,
    busqueda,
    errorBusqueda,
    estado,
    filtrosActivos,
    recargar: () => refresh(),
    programarRefresco,
    iniciarEventos,
    detenerEventos,
    limpiarSesion,
    cambiarPagina,
    cambiarBusqueda,
    cambiarEstado,
    limpiarFiltros,
  }
}
