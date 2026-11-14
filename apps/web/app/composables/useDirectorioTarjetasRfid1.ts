import { computed, onMounted, onScopeDispose, ref, watch, type Ref } from 'vue'
import type { FiltroTipoEntidadRfid1, EstadoTarjetaRfid1, PaginaTarjetasRfid1 } from '~/types/rfid1'
import { ErrorRfid1Api, useClienteRfid1 } from '~/utils/rfid1-api'

export type FiltroTarjetasRfid1 = 'TODAS' | EstadoTarjetaRfid1

/** Carga tarjetas según tipo, estado, página y búsqueda; espera un momento después
 * de escribir y actualiza la lista cuando recibe avisos de cambios RFID1.
 */
export function useDirectorioTarjetasRfid1(
  tipoInicial: Ref<FiltroTipoEntidadRfid1>,
  habilitado: Ref<boolean>,
) {
  const api = useClienteRfid1()
  const sesion = useSesion()
  const tipoEntidad = ref<FiltroTipoEntidadRfid1>(tipoInicial.value)
  const estado = ref<FiltroTarjetasRfid1>('TODAS')
  const pagina = ref(1)
  const busqueda = ref('')
  const busquedaAplicada = ref('')
  const datos = ref<PaginaTarjetasRfid1 | null>(null)
  const cargando = ref(habilitado.value)
  const mensajeError = ref('')

  let controlador: AbortController | null = null
  let suscripcionSse: (() => void) | null = null
  let temporizadorSse: ReturnType<typeof setTimeout> | null = null
  let temporizadorBusqueda: ReturnType<typeof setTimeout> | null = null
  let secuencia = 0
  let recargaPendiente = false
  let descartado = false

  function cancelarSsePendiente() {
    if (temporizadorSse) clearTimeout(temporizadorSse)
    temporizadorSse = null
  }

  async function manejarError(fallo: unknown) {
    if (fallo instanceof ErrorRfid1Api && fallo.estado === 401) {
      datos.value = null
      await sesion.limpiar()
      await navigateTo('/panel')
      return
    }
    if (fallo instanceof ErrorRfid1Api && fallo.estado === 403) {
      mensajeError.value = 'No tienes permiso para consultar las tarjetas.'
    } else if (fallo instanceof ErrorRfid1Api && fallo.estado === 400) {
      mensajeError.value =
        'No pudimos aplicar los filtros. Revisa la búsqueda e inténtalo de nuevo.'
    } else {
      mensajeError.value =
        'No pudimos cargar las tarjetas. Revisa tu conexión e inténtalo de nuevo.'
    }
  }

  async function cargar() {
    if (!import.meta.client || descartado || !habilitado.value) return
    cancelarSsePendiente()
    recargaPendiente = false
    const id = ++secuencia
    controlador?.abort()
    const actual = new AbortController()
    controlador = actual
    cargando.value = true
    mensajeError.value = ''
    try {
      const respuesta = await api.listarTarjetas(
        tipoEntidad.value,
        estado.value,
        pagina.value,
        busquedaAplicada.value,
        actual.signal,
      )
      if (descartado || actual.signal.aborted || id !== secuencia) return
      const ultimaPagina = Math.max(1, respuesta.totalPaginas)
      if (pagina.value > ultimaPagina) {
        pagina.value = ultimaPagina
        datos.value = null
        return
      }
      datos.value = respuesta
    } catch (fallo) {
      if (actual.signal.aborted || descartado || id !== secuencia) return
      await manejarError(fallo)
    } finally {
      if (id === secuencia) {
        cargando.value = false
        controlador = null
        if (recargaPendiente) {
          recargaPendiente = false
          void cargar()
        }
      }
    }
  }

  function actualizar() {
    if (cargando.value) return
    void cargar()
  }

  function cambiarTipo(valor: FiltroTipoEntidadRfid1) {
    if (tipoEntidad.value === valor) return
    tipoEntidad.value = valor
    pagina.value = 1
    datos.value = null
  }

  watch(tipoInicial, cambiarTipo)

  function cambiarEstado(valor: FiltroTarjetasRfid1) {
    if (estado.value === valor) return
    estado.value = valor
    pagina.value = 1
    datos.value = null
  }

  function cambiarPagina(valor: number) {
    const maximo = datos.value?.totalPaginas ?? 1
    const destino = Math.min(maximo, Math.max(1, valor))
    if (destino === pagina.value) return
    pagina.value = destino
    datos.value = null
  }

  function cambiarBusqueda(valor: string) {
    busqueda.value = valor
  }

  watch(busqueda, (valor) => {
    if (temporizadorBusqueda) clearTimeout(temporizadorBusqueda)
    temporizadorBusqueda = setTimeout(() => {
      temporizadorBusqueda = null
      const termino = valor.trim()
      if (termino === busquedaAplicada.value) return
      busquedaAplicada.value = termino
      pagina.value = 1
    }, 300)
  })

  function programarRefrescoSse() {
    cancelarSsePendiente()
    temporizadorSse = setTimeout(() => {
      temporizadorSse = null
      if (cargando.value) recargaPendiente = true
      else void cargar()
    }, 120)
  }

  watch([tipoEntidad, estado, pagina, busquedaAplicada, habilitado], () => {
    if (habilitado.value) void cargar()
  })

  onMounted(() => {
    suscripcionSse = useNuxtApp().$eventosAdministracion.suscribir(
      programarRefrescoSse,
      undefined,
      'rfid1.tarjetas.actualizadas',
    )
    if (habilitado.value) void cargar()
  })

  onScopeDispose(() => {
    descartado = true
    secuencia += 1
    controlador?.abort()
    controlador = null
    cancelarSsePendiente()
    if (temporizadorBusqueda) clearTimeout(temporizadorBusqueda)
    temporizadorBusqueda = null
    suscripcionSse?.()
    suscripcionSse = null
    datos.value = null
  })

  return {
    tipoEntidad,
    estado,
    pagina,
    busqueda,
    busquedaAplicada,
    datos,
    tarjetas: computed(() => datos.value?.items ?? []),
    total: computed(() => datos.value?.total ?? 0),
    totalPaginas: computed(() => datos.value?.totalPaginas ?? 0),
    cargando,
    mensajeError,
    cargar,
    actualizar,
    cambiarTipo,
    cambiarEstado,
    cambiarPagina,
    cambiarBusqueda,
  }
}
