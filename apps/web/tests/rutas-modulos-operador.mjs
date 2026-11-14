import assert from 'node:assert/strict'
import {
  esRutaModuloOperador,
  RUTAS_MODULOS_OPERADOR,
} from '../app/utils/rutas-modulos-operador.ts'

const rutasPermitidas = [
  '/operador/monitoreo',
  '/operador/accesos',
  '/operador/clientes',
  '/operador/tarjetas',
]

assert.deepEqual(RUTAS_MODULOS_OPERADOR, rutasPermitidas)
for (const ruta of rutasPermitidas) assert.equal(esRutaModuloOperador(ruta), true, ruta)

for (const ruta of [
  '/operador',
  '/operador/operadores',
  '/operador/empleados',
  '/operador/clientes/1234',
  '/admin/empleados',
]) {
  assert.equal(esRutaModuloOperador(ruta), false, ruta)
}
