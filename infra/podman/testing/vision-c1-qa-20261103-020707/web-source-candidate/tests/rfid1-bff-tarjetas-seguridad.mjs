import assert from 'node:assert/strict'
import {
  ASOCIACION_ID,
  CAPTURA_ID,
  UID_SINTETICA,
  iniciarRfid1Bff,
  privado,
} from './soporte-rfid1-bff.mjs'

export async function verificarDirectorioYSeguridadRfid1() {
  const servidor = await iniciarRfid1Bff()
  const { base, solicitudes } = servidor
  try {
    const personas = await fetch(
      `${base}/api/v1/tarjetas-rfid/personas?tipoEntidad=MIXTO&busqueda=Va`,
      { headers: { cookie: 'JSESSIONID=dueno-sintetico' } },
    )
    assert.equal(personas.status, 200)
    privado(personas)
    assert.equal((await personas.json())[0].tipoEntidad, 'CLIENTE')
    assert.equal(
      solicitudes.at(-1).search,
      '?tipoEntidad=MIXTO&busqueda=Va',
      'El BFF conserva únicamente los parámetros de búsqueda admitidos',
    )
    assert.equal(solicitudes.at(-1).headers.cookie, 'JSESSIONID=dueno-sintetico')
    assert.equal(solicitudes.at(-1).headers.authorization, undefined)
    const directorio = await fetch(
      `${base}/api/v1/tarjetas-rfid?tipoEntidad=MIXTO&estado=TODAS&pagina=1`,
      { headers: { cookie: 'JSESSIONID=dueno-sintetico' } },
    )
    assert.equal(directorio.status, 200)
    privado(directorio)
    assert.equal((await directorio.json()).items[0].uid, UID_SINTETICA)
    assert.equal(solicitudes.at(-1).headers.authorization, undefined)
    const detalle = await fetch(`${base}/api/v1/tarjetas-rfid/${ASOCIACION_ID}`, {
      headers: { cookie: 'JSESSIONID=dueno-sintetico' },
    })
    assert.equal(detalle.status, 200)
    privado(detalle)
    assert.equal((await detalle.json()).uid, UID_SINTETICA)

    const cancelacionTarjeta = await fetch(
      `${base}/api/v1/tarjetas-rfid/${ASOCIACION_ID}/cancelacion`,
      {
        method: 'POST',
        headers: { cookie: 'JSESSIONID=dueno-sintetico', 'x-csrf-token': 'csrf-sintetico' },
      },
    )
    assert.equal(cancelacionTarjeta.status, 200)
    privado(cancelacionTarjeta)
    assert.deepEqual(await cancelacionTarjeta.json(), {
      asociacionId: ASOCIACION_ID,
      estado: 'CANCELADA',
    })
    assert.equal(solicitudes.at(-1).headers['x-csrf-token'], 'csrf-sintetico')
    assert.equal(solicitudes.at(-1).body, '')
    const antesInvalidas = solicitudes.length
    for (const [metodo, ruta] of [
      ['GET', '/api/v1/rfid-1/capturas/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'],
      ['POST', `/api/v1/rfid-1/capturas/${CAPTURA_ID}`],
      ['DELETE', '/api/v1/rfid-1/capturas/activa'],
      ['GET', '/api/v1/rfid-1/capturas/activa?extra=1'],
      ['GET', '/api/v1/tarjetas-rfid/01'],
      ['GET', '/api/v1/rfid-1/estado-conexion?extra=1'],
      ['GET', '/api/v1/tarjetas-rfid/personas?tipoEntidad=CLIENTE&busqueda=x'],
      ['GET', '/api/v1/tarjetas-rfid/personas?tipoEntidad=CLIENTE&tipoEntidad=EMPLEADO&busqueda=Va'],
      ['GET', '/api/v1/tarjetas-rfid?tipoEntidad=CLIENTE&estado=OTRO'],
      ['GET', '/api/v1/tarjetas-rfid?tipoEntidad=CLIENTE&pagina=0'],
      ['POST', '/api/v1/dispositivos/rfid-1/lecturas'],
    ]) {
      assert.equal((await fetch(`${base}${ruta}`, { method: metodo })).status, 404)
    }
    assert.equal(
      solicitudes.length,
      antesInvalidas,
      'Las rutas o métodos RFID no permitidos no llegan al API',
    )

    const antesCuerpoInvalido = solicitudes.length
    const solicitudConUid = await fetch(`${base}/api/v1/rfid-1/capturas`, {
      method: 'POST',
      headers: {
        cookie: 'JSESSIONID=dueno-sintetico',
        'content-type': 'application/json',
        'x-csrf-token': 'csrf-sintetico',
        'idempotency-key': 'clave-idempotente-sintetica',
      },
      body: JSON.stringify({
        tipoEntidad: 'CLIENTE',
        codigoPersona: 'CLI-0001',
        uid: UID_SINTETICA,
      }),
    })
    assert.equal(solicitudConUid.status, 400)
    assert.equal(
      solicitudes.length,
      antesCuerpoInvalido,
      'El BFF rechaza propiedades RFID ajenas al contrato',
    )

    const intentoCliente = await fetch(`${base}/api/v1/rfid-1/capturas`, {
      method: 'POST',
      headers: {
        cookie: 'CLIENTSESSIONID=cliente-sintetico',
        'content-type': 'application/json',
        'x-csrf-token': 'csrf-sintetico',
        'idempotency-key': 'clave-sintetica-cliente',
      },
      body: JSON.stringify({ tipoEntidad: 'EMPLEADO', codigoPersona: 'E-0001' }),
    })
    assert.equal(intentoCliente.status, 401)
    privado(intentoCliente)
    assert.equal(
      solicitudes.at(-1).headers.cookie,
      undefined,
      'Una sesión CLIENTE no se reenvía como sesión DUENO',
    )
    assert.equal(solicitudes.at(-1).headers.authorization, undefined)
  } finally {
    await servidor.cerrar()
  }
}
