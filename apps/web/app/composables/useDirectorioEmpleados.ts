import { computed } from 'vue'
import type { PaginaEmpleados } from '~/types/empleado'
import { ErrorEmpleadoApi, useClienteEmpleados } from '~/utils/empleados-api'

type ResultadoDirectorio =
  | { estado: 'listo'; datos: PaginaEmpleados }
  | { estado: 'fallo'; mensaje: string; status: number }

/** Carga los empleados por página y actualiza la lista cuando llegan avisos;
 * consulta el correo solo al abrir los datos de una persona.
 */
export async function useDirectorioEmpleados() {
  const route = useRoute()
  const router = useRouter()
  const cliente = useClienteEmpleados()
  const { limpiar } = useSesion()
  const eventos = useNuxtApp().$eventosAdministracion
  const paginaSolicitada = computed(() => {
    const valor = route.query.pagina
    if (valor === undefined || valor === null) return '1'
    return Array.isArray(valor) ? valor.map((elemento) => elemento ?? '') : valor
  })

  const { data, pending, refresh, clear } = await useAsyncData<ResultadoDirectorio>(
    'directorio-empleados',
    async (_nuxtApp, { signal }) => {
      try {
        const datos = await cliente.listar(paginaSolicitada.value, signal)
        // La lista muestra los datos básicos; el correo se consulta al abrir la ficha del empleado.
        const datosSinCorreos = {
          ...datos,
          items: datos.items.map((empleado) => ({ ...empleado, correo: null })),
        }
        return { estado: 'listo', datos: datosSinCorreos }
      } catch (fallo) {
        if (signal.aborted) throw fallo
        if (fallo instanceof ErrorEmpleadoApi && fallo.estado === 401) {
          await limpiar()
          if (import.meta.client) await navigateTo('/panel')
        }
        const mensaje =
          fallo instanceof ErrorEmpleadoApi
            ? fallo.message
            : 'No pudimos cargar la lista. Revisa tu conexión e inténtalo de nuevo.'
        const status = fallo instanceof ErrorEmpleadoApi ? fallo.estado : 503
        return { estado: 'fallo', mensaje, status }
      }
    },
    {
      watch: [paginaSolicitada],
      dedupe: 'cancel',
      default: () =>
        ({ estado: 'fallo', mensaje: 'Cargando la lista…', status: 0 }) as ResultadoDirectorio,
    },
  )

  const resultado = computed(() => data.value as ResultadoDirectorio)
  const directorio = computed(() =>
    resultado.value.estado === 'listo' ? resultado.value.datos : null,
  )
  const empleados = computed(() => directorio.value?.items ?? [])
  const paginaActual = computed(() => directorio.value?.pagina ?? 1)
  const totalRegistros = computed(() => directorio.value?.totalRegistros ?? 0)
  const totalPaginas = computed(() => directorio.value?.totalPaginas ?? 0)
  const mensajeError = computed(() =>
    resultado.value.estado === 'fallo' && !pending.value ? resultado.value.mensaje : '',
  )

  let temporizador: ReturnType<typeof setTimeout> | undefined
  let cancelarSuscripcion = () => {}

  function programarRefresco() {
    if (temporizador) clearTimeout(temporizador)
    temporizador = setTimeout(() => {
      temporizador = undefined
      void refresh()
    }, 100)
  }

  async function cambiarPagina(pagina: number) {
    const destino = pagina <= 1 ? undefined : String(Math.trunc(pagina))
    await router.push({ query: { ...route.query, pagina: destino } })
  }

  function iniciarEventos() {
    const cursor = directorio.value?.cursorEventos
    cancelarSuscripcion = eventos.suscribir(programarRefresco, cursor)
  }

  function detenerEventos() {
    cancelarSuscripcion()
    cancelarSuscripcion = () => {}
    if (temporizador) clearTimeout(temporizador)
    temporizador = undefined
  }

  function limpiarSesion() {
    detenerEventos()
    clear()
  }

  function sincronizarUrl(pagina: PaginaEmpleados | null) {
    if (!import.meta.client || !pagina) return
    const urlPagina = route.query.pagina
    const canonica = pagina.pagina === 1 ? undefined : String(pagina.pagina)
    if ((urlPagina ?? undefined) === canonica) return
    void router.replace({ query: { ...route.query, pagina: canonica } })
  }

  return {
    empleados,
    directorio,
    pending,
    mensajeError,
    paginaActual,
    totalRegistros,
    totalPaginas,
    recargar: () => refresh(),
    programarRefresco,
    cambiarPagina,
    iniciarEventos,
    detenerEventos,
    limpiarSesion,
    sincronizarUrl,
  }
}
