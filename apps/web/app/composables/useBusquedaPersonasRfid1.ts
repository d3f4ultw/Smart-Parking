import { computed, onScopeDispose, ref, watch, type Ref } from 'vue'
import type { CandidatoPersonaRfid1, FiltroTipoEntidadRfid1 } from '~/types/rfid1'
import { ErrorRfid1Api, useClienteRfid1 } from '~/utils/rfid1-api'

export function useBusquedaPersonasRfid1(
  habilitada: Ref<boolean>,
  manejarSesionVencida: (fallo: unknown) => Promise<boolean>,
) {
  const api = useClienteRfid1()
  const tipoEntidad = ref<FiltroTipoEntidadRfid1>('CLIENTE')
  const busqueda = ref('')
  const candidatos = ref<CandidatoPersonaRfid1[]>([])
  const pendientes = ref(false)
  const error = ref('')
  const visible = computed(() => candidatos.value.length > 0 && busqueda.value.trim().length >= 2)

  let temporizador: ReturnType<typeof setTimeout> | null = null
  let controlador: AbortController | null = null
  let secuencia = 0
  let descartada = false

  function limpiar() {
    if (temporizador) clearTimeout(temporizador)
    temporizador = null
    controlador?.abort()
    controlador = null
    secuencia += 1
    candidatos.value = []
    pendientes.value = false
  }

  async function buscar() {
    limpiar()
    error.value = ''
    const termino = busqueda.value.trim()
    if (!habilitada.value || Array.from(termino).length < 2 || descartada) return

    const id = secuencia
    pendientes.value = true
    temporizador = setTimeout(async () => {
      temporizador = null
      const actual = new AbortController()
      controlador = actual
      try {
        const respuesta = await api.buscarPersonas(tipoEntidad.value, termino, actual.signal)
        if (
          !descartada &&
          !actual.signal.aborted &&
          id === secuencia &&
          termino === busqueda.value.trim()
        ) {
          candidatos.value = respuesta
        }
      } catch (fallo) {
        if (actual.signal.aborted || id !== secuencia || descartada) return
        if (await manejarSesionVencida(fallo)) return
        error.value =
          fallo instanceof ErrorRfid1Api
            ? fallo.message
            : 'No pudimos buscar personas. Inténtalo de nuevo.'
      } finally {
        if (id === secuencia) {
          pendientes.value = false
          controlador = null
        }
      }
    }, 300)
  }

  watch([busqueda, tipoEntidad, habilitada], () => void buscar())

  function cambiarTipo(valor: FiltroTipoEntidadRfid1) {
    if (tipoEntidad.value === valor) return
    tipoEntidad.value = valor
    busqueda.value = ''
    limpiar()
  }

  function seleccionar(candidato: CandidatoPersonaRfid1) {
    if (
      !candidato.elegible ||
      (tipoEntidad.value !== 'MIXTO' && candidato.tipoEntidad !== tipoEntidad.value)
    ) {
      return null
    }
    busqueda.value = ''
    limpiar()
    return candidato
  }

  function limpiarSeleccion() {
    busqueda.value = ''
    limpiar()
  }

  onScopeDispose(() => {
    descartada = true
    limpiar()
    candidatos.value = []
  })

  return {
    tipoEntidad,
    busqueda,
    candidatos,
    pendientes,
    error,
    visible,
    cambiarTipo,
    seleccionar,
    limpiar,
    limpiarSeleccion,
  }
}
