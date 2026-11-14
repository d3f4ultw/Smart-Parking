import type { EstadoConexionRfid1 } from '~/types/rfid1'

/** Convierte la respuesta del lector en un mensaje: conectado, sin conexión,
 * esperando señal o sin posibilidad de comprobarlo.
 */
export function etiquetaEstadoConexionRfid1(
  estado: EstadoConexionRfid1,
  consultada: boolean,
  errorConsulta: boolean,
): string {
  if (errorConsulta) return 'No se pudo verificar'
  if (estado === 'CONECTADO') return 'Conectado'
  if (estado === 'DESCONECTADO') return 'Sin conexión'
  if (consultada) return 'Esperando señal'
  return 'Comprobando'
}
