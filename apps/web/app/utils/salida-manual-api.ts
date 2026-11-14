import type { EstadoSalidaManual, SalidaManual } from '~/types/acceso'
import { solicitarApi } from '~/utils/api'

const UUID = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/
const ESTADOS: EstadoSalidaManual[] = [
  'PENDIENTE',
  'EMITIDA',
  'CONFIRMADA',
  'NO_EJECUTADA',
  'INCIERTA',
  'ANULADA',
]

/** Comprueba que la respuesta incluya un identificador válido y uno de los
 * resultados previstos antes de usarla en la pantalla.
 */
export function leerSalidaManual(valor: unknown): SalidaManual | null {
  if (!valor || typeof valor !== 'object' || Array.isArray(valor)) return null
  const dato = valor as Record<string, unknown>
  if (
    typeof dato.operacionId !== 'string' ||
    !UUID.test(dato.operacionId) ||
    typeof dato.estado !== 'string' ||
    !ESTADOS.includes(dato.estado as EstadoSalidaManual)
  ) {
    return null
  }
  return { operacionId: dato.operacionId, estado: dato.estado as EstadoSalidaManual }
}

function leerOperacion(valor: unknown, movimientoId: string, operacionId: string): SalidaManual {
  const salida = leerSalidaManual(valor)
  if (
    !salida ||
    salida.operacionId !== operacionId ||
    !valor ||
    typeof valor !== 'object' ||
    !('movimientoId' in valor) ||
    valor.movimientoId !== movimientoId
  ) {
    throw new Error('No se pudo verificar el estado de la salida.')
  }
  return salida
}

/** Envía una solicitud de salida para un movimiento concreto. Si no llega respuesta,
 * consulta el resultado de esa misma solicitud y no vuelve a enviarla automáticamente.
 */
export function useClienteSalidaManual() {
  return {
    async solicitar(movimientoId: string, operacionId: string, csrf: string) {
      const valor = await solicitarApi<unknown>(
        `/api/v1/accesos/movimientos/${encodeURIComponent(movimientoId)}/salida-manual`,
        {
          method: 'POST',
          headers: { 'x-csrf-token': csrf, 'idempotency-key': operacionId },
          retry: 0,
          timeout: 10_000,
        },
      )
      return leerOperacion(valor, movimientoId, operacionId)
    },
    async consultar(movimientoId: string, operacionId: string) {
      const valor = await solicitarApi<unknown>(
        `/api/v1/accesos/salidas-manuales/${encodeURIComponent(operacionId)}`,
        { method: 'GET', retry: 0, timeout: 10_000 },
      )
      return leerOperacion(valor, movimientoId, operacionId)
    },
  }
}
