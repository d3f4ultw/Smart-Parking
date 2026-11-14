import assert from 'node:assert/strict'
import { iniciarEmpleadosBff } from './soporte-empleados-bff.mjs'
import { verificarRutasEmpleados } from './empleados-bff-rutas.mjs'
import {
  verificarEventosEmpleados,
  verificarRutasEventosEmpleados,
} from './empleados-bff-eventos.mjs'
import { verificarPluginHeartbeat } from './empleados-bff-plugin-heartbeat.mjs'

async function ejecutarSuite(verificar) {
  const servidor = await iniciarEmpleadosBff()
  try {
    assert.ok(servidor.listo, `El servidor Web no inició: ${servidor.salida.join('').slice(-2500)}`)
    return await verificar(servidor)
  } finally {
    await servidor.cerrar()
  }
}

await ejecutarSuite(verificarRutasEmpleados)
const verificacionesPlugin = await ejecutarSuite(async (servidor) => {
  const cantidadAntes = await verificarEventosEmpleados(servidor)
  const gruposPlugin = await verificarPluginHeartbeat(servidor)
  await verificarRutasEventosEmpleados(servidor, cantidadAntes)
  return gruposPlugin
})
console.log(
  JSON.stringify({
    resultado: 'PASS',
    verificaciones: [
      'allowlist',
      'cookie/CSRF/idempotencia/If-Match',
      'heartbeat 204/cookie/CSRF/body',
      ...verificacionesPlugin,
      'cursor SSE',
      'streaming',
      'cancelación upstream',
    ],
  }),
)
