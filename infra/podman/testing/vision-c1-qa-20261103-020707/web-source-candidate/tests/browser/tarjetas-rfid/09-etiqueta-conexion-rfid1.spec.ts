import { expect, test } from '@playwright/test'
import { etiquetaEstadoConexionRfid1 } from '../../../app/utils/estado-conexion-rfid1'

test('RFID1 diferencia el timeout del lector de los errores de consulta', () => {
  expect(etiquetaEstadoConexionRfid1('DESCONOCIDO', false, false)).toBe('Comprobando')
  expect(etiquetaEstadoConexionRfid1('DESCONOCIDO', true, false)).toBe('Esperando señal')
  expect(etiquetaEstadoConexionRfid1('DESCONECTADO', true, false)).toBe('Sin conexión')
  expect(etiquetaEstadoConexionRfid1('DESCONECTADO', true, true)).toBe('No se pudo verificar')
  expect(etiquetaEstadoConexionRfid1('CONECTADO', true, false)).toBe('Conectado')
})
