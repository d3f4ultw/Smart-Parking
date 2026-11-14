import { computed, getCurrentScope, ref, watch } from 'vue'
import type { Ref } from 'vue'
import { useClienteAccesos } from '~/utils/capacidad-rfid-api'

/** Carga la lista paginada de vehículos que aún figuran dentro, permite buscarlos
 * y actualiza la lista cuando cambia un acceso o una tarjeta.
 */
export async function useEntradasActivas(vista: Ref<'HISTORIAL' | 'DENTRO'>) {
  const alcance = getCurrentScope()
  const ruta = useRoute()
  const { sesion } = useSesion()
  const cliente = useClienteAccesos()
  const filtros = ref({ pagina: 1, busqueda: '' })
  alcance?.run(() => {
    watch(
      () => {
        const actual = sesion.value
        return actual.estado === 'autenticada'
          ? JSON.stringify([actual.identidad.rol, actual.identidad.correo])
          : null
      },
      (actual, anterior) => {
        if (actual !== anterior) filtros.value = { pagina: 1, busqueda: '' }
      },
      { flush: 'sync' },
    )
  })
  const criterio = computed(() => {
    const actual = sesion.value
    if (actual.estado !== 'autenticada' || vista.value !== 'DENTRO') return null
    const { rol, correo } = actual.identidad
    const rutaDueno = ruta.path === '/admin/accesos'
    const rutaOperador = ruta.path === '/operador/accesos'
    return (rol === 'DUENO' && rutaDueno) || (rol === 'OPERADOR' && rutaOperador)
      ? JSON.stringify([rol, correo, filtros.value.pagina, filtros.value.busqueda])
      : null
  })
  const consulta = await useConsultaAccesos({
    clave: 'entradas-activas-rfid:' + ruta.path,
    criterio,
    consultar: (signal) => cliente.dentro(filtros.value.pagina, filtros.value.busqueda, signal),
    temas: ['acceso.historial.actualizado', 'rfid1.tarjetas.actualizadas'],
    inmediata: false,
  })

  alcance?.run(() => {
    watch(consulta.datos, (datos) => {
      if (!datos) return
      const ultima = Math.max(1, Math.ceil(datos.totalRegistros / datos.tamano))
      if (filtros.value.pagina > ultima) filtros.value = { ...filtros.value, pagina: ultima }
    })
  })

  function cambiarPagina(numero: number) {
    if (Number.isSafeInteger(numero) && numero >= 1 && numero !== filtros.value.pagina) {
      filtros.value = { ...filtros.value, pagina: numero }
    }
  }

  function buscar(valor: string) {
    const busqueda = [...valor]
      .filter((caracter) => {
        const codigo = caracter.codePointAt(0) ?? 0
        return codigo > 0x1f && (codigo < 0x7f || codigo > 0x9f)
      })
      .join('')
      .trim()
      .slice(0, 100)
    if (busqueda !== filtros.value.busqueda || filtros.value.pagina !== 1) {
      filtros.value = { pagina: 1, busqueda }
    }
  }

  return { ...consulta, busqueda: computed(() => filtros.value.busqueda), cambiarPagina, buscar }
}
