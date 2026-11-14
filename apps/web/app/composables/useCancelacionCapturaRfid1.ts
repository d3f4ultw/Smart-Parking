import type { Ref } from 'vue'
import type { CapturaRfid1, VistaPreviaRfid1 } from '~/types/rfid1'
import { useClienteRfid1 } from '~/utils/rfid1-api'

type FaseCancelacion = 'lista' | 'iniciando' | 'escaneando' | 'confirmando' | 'cancelando'

interface OpcionesCancelacion {
  captura: Ref<CapturaRfid1 | null>
  vistaPrevia: Ref<VistaPreviaRfid1 | null>
  fase: Ref<FaseCancelacion>
  mensajeError: Ref<string>
  mensajeCaptura: Ref<string>
  activa: (captura: CapturaRfid1 | null) => boolean
  manejarSesionVencida: (fallo: unknown) => Promise<boolean>
  aplicarEstado: (captura: CapturaRfid1) => Promise<void>
}

/** Cancela la lectura y, si no llega confirmación, consulta si sigue activa
 * antes de mostrarla como cerrada.
 */
export function useCancelacionCapturaRfid1(opciones: OpcionesCancelacion) {
  const api = useClienteRfid1()
  const csrf = useCsrf()

  return async function cancelarCaptura(): Promise<boolean> {
    const actual = opciones.captura.value
    if (!actual || !opciones.activa(actual) || opciones.fase.value === 'cancelando') return true
    opciones.fase.value = 'cancelando'
    opciones.mensajeError.value = ''
    opciones.vistaPrevia.value = null
    try {
      await api.cancelar(actual.capturaId, await csrf.obtener())
      await opciones.aplicarEstado({ ...actual, estado: 'CANCELADA' })
      return true
    } catch (fallo) {
      if (await opciones.manejarSesionVencida(fallo)) return false
      try {
        const estadoActual = await api.consultar(actual.capturaId)
        await opciones.aplicarEstado(estadoActual)
        if (!opciones.activa(estadoActual)) return true
      } catch (reconciliacion) {
        if (await opciones.manejarSesionVencida(reconciliacion)) return false
      }
      opciones.fase.value = 'lista'
      opciones.mensajeError.value =
        'No pudimos confirmar la cancelación. La captura sigue visible para que puedas volver a consultar o cancelar.'
      return false
    }
  }
}
