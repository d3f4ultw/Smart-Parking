import { computed, ref, type Ref } from 'vue'
import type { CapturaRfid1, VistaPreviaRfid1 } from '~/types/rfid1'

const INTERVALO_RECONCILIACION_MS = 8_000
const ESTADOS_ACTIVOS = new Set(['PENDIENTE', 'ESCANEANDO', 'VISTA_PREVIA'])

/** Muestra cuánto falta para que venza la lectura o su vista previa y programa
 * consultas periódicas mientras la lectura siga activa y la ventana esté abierta.
 */
export function useVigenciaCapturaRfid1(
  abierta: Ref<boolean>,
  captura: Ref<CapturaRfid1 | null>,
  vistaPrevia: Ref<VistaPreviaRfid1 | null>,
  reconciliar: () => Promise<void>,
) {
  const ahora = ref(0)
  const segundosRestantes = computed(() => {
    const limite =
      captura.value?.estado === 'VISTA_PREVIA'
        ? vistaPrevia.value?.confirmacionVenceEn
        : captura.value?.expiraEn
    const vence = limite ? Date.parse(limite) : NaN
    if (!Number.isFinite(vence) || !ahora.value) return null
    return Math.max(0, Math.ceil((vence - ahora.value) / 1_000))
  })

  let temporizadorReconciliacion: ReturnType<typeof setTimeout> | null = null
  let temporizadorReloj: ReturnType<typeof setInterval> | null = null
  let suscripcion: (() => void) | null = null

  function escuchar() {
    if (!import.meta.client) return
    ahora.value = Date.now()
    if (!temporizadorReloj) {
      temporizadorReloj = setInterval(() => (ahora.value = Date.now()), 1_000)
    }
    if (!suscripcion) {
      suscripcion = useNuxtApp().$eventosAdministracion.suscribir(
        () => void reconciliar(),
        undefined,
        'rfid1.captura.actualizada',
      )
    }
  }

  function programar() {
    if (temporizadorReconciliacion) clearTimeout(temporizadorReconciliacion)
    temporizadorReconciliacion = null
    const actual = captura.value
    if (!abierta.value || !actual || !ESTADOS_ACTIVOS.has(actual.estado)) return
    const espera = Math.max(
      250,
      Math.min(INTERVALO_RECONCILIACION_MS, (segundosRestantes.value ?? 8) * 1_000),
    )
    temporizadorReconciliacion = setTimeout(() => {
      temporizadorReconciliacion = null
      void reconciliar()
    }, espera)
  }

  function detener() {
    if (temporizadorReconciliacion) clearTimeout(temporizadorReconciliacion)
    if (temporizadorReloj) clearInterval(temporizadorReloj)
    temporizadorReconciliacion = null
    temporizadorReloj = null
    suscripcion?.()
    suscripcion = null
    ahora.value = 0
  }

  return { ahora, segundosRestantes, escuchar, programar, detener }
}
