import { verificarCapturasRfid1 } from './rfid1-bff-capturas.mjs'
import { verificarDirectorioYSeguridadRfid1 } from './rfid1-bff-tarjetas-seguridad.mjs'

await verificarCapturasRfid1()
await verificarDirectorioYSeguridadRfid1()
console.log(
  JSON.stringify({
    resultado: 'PASS',
    verificaciones: [
      'allowlist exacta de directorio, detalle, vista previa, confirmación y cancelaciones',
      'cookie DUENO y CSRF por método',
      '204 sin cuerpo y respuestas privadas',
      'Authorization de dispositivo no se reenvía',
      'parámetros, IDs, tipos y consultas cortas inválidos rechazados',
      'cuerpos de creación estrictos y confirmación sin UID',
      'sesión CLIENTE no se reenvía como DUENO',
    ],
  }),
)
