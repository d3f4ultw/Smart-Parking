import { computed, ref, watch } from 'vue'
import type { Ref } from 'vue'
import type { EntradaActiva, PaginaEntradasActivas, SalidaManual } from '~/types/acceso'
import { ErrorApi } from '~/utils/api'
import { useClienteSalidaManual } from '~/utils/salida-manual-api'

type EstadoLocal = SalidaManual | { operacionId: string; estado: 'SIN_CONFIRMACION' }
const NO_TERMINADAS = ['PENDIENTE', 'EMITIDA', 'INCIERTA', 'SIN_CONFIRMACION', 'CONFIRMADA']
const ORDEN: Record<EstadoLocal['estado'], number> = {
  SIN_CONFIRMACION: 0,
  PENDIENTE: 1,
  EMITIDA: 2,
  INCIERTA: 3,
  NO_EJECUTADA: 4,
  ANULADA: 4,
  CONFIRMADA: 5,
}

/** Conserva la referencia de cada solicitud mientras la página está abierta;
 * si no llega respuesta, consulta ese mismo resultado en vez de enviar otra orden.
 */
export function useSalidasManuales(
  entradas: Ref<PaginaEntradasActivas | null>,
  actualizarDentro: () => Promise<unknown>,
  actualizarHistorial: () => Promise<unknown>,
  disponible: () => boolean,
) {
  const { sesion } = useSesion()
  const csrf = useCsrf()
  const api = useClienteSalidaManual()
  const locales = ref<Record<string, EstadoLocal>>({})
  const seleccionada = ref<EntradaActiva | null>(null)
  const abierta = ref(false)
  const procesando = ref(false)
  const mensaje = ref('')
  let generacion = 0

  const identidad = computed(() => {
    const actual = sesion.value
    if (actual.estado !== 'autenticada') return null
    if (actual.identidad.rol !== 'DUENO' && actual.identidad.rol !== 'OPERADOR') return null
    return JSON.stringify([actual.identidad.rol, actual.identidad.correo])
  })

  watch(
    identidad,
    () => {
      generacion += 1
      locales.value = {}
      seleccionada.value = null
      abierta.value = false
      procesando.value = false
      mensaje.value = ''
    },
    { flush: 'sync' },
  )

  // Si el servidor ya registra una salida iniciada en otra sesión, conserva ese resultado
  // aunque esta página no haya recibido la respuesta de su solicitud.
  watch(entradas, (pagina) => {
    for (const entrada of pagina?.items ?? []) {
      const servidor = entrada.salidaManual
      const local = locales.value[entrada.movimientoId]
      if (
        servidor &&
        local &&
        servidor.operacionId !== local.operacionId &&
        NO_TERMINADAS.includes(servidor.estado)
      ) {
        locales.value = { ...locales.value, [entrada.movimientoId]: servidor }
      }
    }
  })

  function estado(entrada: EntradaActiva): EstadoLocal | null {
    const local = locales.value[entrada.movimientoId]
    const servidor = entrada.salidaManual
    if (!local) return servidor
    if (!servidor) return local
    if (servidor.operacionId !== local.operacionId) {
      return NO_TERMINADAS.includes(servidor.estado) ? servidor : local
    }
    return ORDEN[servidor.estado] >= ORDEN[local.estado] ? servidor : local
  }

  function puedeSolicitar(entrada: EntradaActiva) {
    const actual = estado(entrada)
    return Boolean(
      identidad.value &&
      disponible() &&
      entrada.estadoTarjeta === 'CANCELADA' &&
      (!actual || !NO_TERMINADAS.includes(actual.estado)),
    )
  }

  function seleccionar(entrada: EntradaActiva) {
    if (procesando.value || !puedeSolicitar(entrada)) return
    seleccionada.value = entrada
    mensaje.value = ''
    abierta.value = true
  }

  async function confirmar() {
    const entrada = seleccionada.value
    if (!entrada || !puedeSolicitar(entrada) || procesando.value || !import.meta.client) return
    const turno = generacion
    procesando.value = true
    mensaje.value = ''
    let token: string
    try {
      token = await csrf.obtener()
    } catch {
      if (turno === generacion)
        mensaje.value = 'No se pudo verificar tu sesión. Inténtalo de nuevo.'
      if (turno === generacion) procesando.value = false
      return
    }
    if (turno !== generacion) return
    if (!globalThis.crypto?.randomUUID) {
      mensaje.value = 'Este navegador no permite preparar la solicitud de forma segura.'
      procesando.value = false
      return
    }
    const operacionId = globalThis.crypto.randomUUID()
    locales.value = {
      ...locales.value,
      [entrada.movimientoId]: { operacionId, estado: 'SIN_CONFIRMACION' },
    }
    try {
      const salida = await api.solicitar(entrada.movimientoId, operacionId, token)
      if (turno !== generacion) return
      locales.value = { ...locales.value, [entrada.movimientoId]: salida }
      abierta.value = false
    } catch (fallo) {
      if (turno !== generacion) return
      if (
        fallo instanceof ErrorApi &&
        fallo.estado === 503 &&
        fallo.codigo === 'SALIDA_MANUAL_NO_DISPONIBLE'
      ) {
        // El servidor devuelve este código antes de guardar la solicitud;
        // se quita la referencia local para que pueda intentarse más tarde.
        const restantes = { ...locales.value }
        delete restantes[entrada.movimientoId]
        locales.value = restantes
        mensaje.value =
          'La salida manual no está disponible. La solicitud no se registró; puedes intentarlo más tarde.'
      } else {
        mensaje.value =
          'No se pudo confirmar la solicitud. Conservamos su referencia para consultar el resultado.'
      }
    } finally {
      if (turno === generacion) {
        procesando.value = false
        void actualizarDentro()
      }
    }
  }

  async function consultar(entrada: EntradaActiva) {
    const actual = estado(entrada)
    if (!actual || procesando.value || !identidad.value) return
    const turno = generacion
    procesando.value = true
    mensaje.value = ''
    try {
      const salida = await api.consultar(entrada.movimientoId, actual.operacionId)
      if (turno !== generacion) return
      locales.value = { ...locales.value, [entrada.movimientoId]: salida }
      await actualizarDentro()
      if (salida.estado === 'CONFIRMADA') await actualizarHistorial()
    } catch {
      if (turno === generacion) {
        mensaje.value = 'No se pudo consultar el resultado. La salida sigue sin confirmar.'
      }
    } finally {
      if (turno === generacion) procesando.value = false
    }
  }

  return {
    identidad,
    abierta,
    seleccionada,
    procesando,
    mensaje,
    estado,
    puedeSolicitar,
    seleccionar,
    confirmar,
    consultar,
  }
}
