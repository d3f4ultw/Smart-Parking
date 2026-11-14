import assert from 'node:assert/strict'
import {
  CAPTURA_ID,
  UID_SINTETICA,
  iniciarRfid1Bff,
  privado,
} from './soporte-rfid1-bff.mjs'

export async function verificarCapturasRfid1() {
  const servidor = await iniciarRfid1Bff()
  const { base, solicitudes } = servidor
  try {
    const crear = await fetch(`${base}/api/v1/rfid-1/capturas`, {
      method: 'POST',
      headers: {
        cookie: 'JSESSIONID=dueno-sintetico; CLIENTSESSIONID=cliente-sintetico',
        'content-type': 'application/json',
        'x-csrf-token': 'csrf-sintetico',
        'idempotency-key': 'clave-idempotente-sintetica',
        authorization: 'Bearer token-dispositivo-sintetico',
      },
      body: JSON.stringify({ tipoEntidad: 'CLIENTE', codigoPersona: 'CLI-0001' }),
    })
    assert.equal(crear.status, 201)
    privado(crear)
    assert.deepEqual(await crear.json(), {
      capturaId: CAPTURA_ID,
      estado: 'PENDIENTE',
      expiraEn: '2026-10-27T22:00:00Z',
    })
    const cookiesRenovadas = crear.headers.getSetCookie()
    assert.ok(cookiesRenovadas.some((cookie) => cookie.startsWith('JSESSIONID=sesion-renovada;')))
    const solicitudCrear = solicitudes.at(-1)
    assert.equal(solicitudCrear.method, 'POST')
    assert.equal(solicitudCrear.path, '/api/v1/rfid-1/capturas')
    assert.equal(solicitudCrear.headers.cookie, 'JSESSIONID=dueno-sintetico')
    assert.equal(solicitudCrear.headers['x-csrf-token'], 'csrf-sintetico')
    assert.equal(solicitudCrear.headers['idempotency-key'], 'clave-idempotente-sintetica')
    assert.equal(solicitudCrear.headers.authorization, undefined)
    assert.deepEqual(JSON.parse(solicitudCrear.body), {
      tipoEntidad: 'CLIENTE',
      codigoPersona: 'CLI-0001',
    })

    const activa = await fetch(`${base}/api/v1/rfid-1/capturas/activa`, {
      headers: { cookie: 'JSESSIONID=dueno-sintetico' },
    })
    assert.equal(activa.status, 204)
    assert.equal(await activa.text(), '')
    privado(activa)
    assert.equal(solicitudes.at(-1).path, '/api/v1/rfid-1/capturas/activa')
    assert.equal(solicitudes.at(-1).headers.cookie, 'JSESSIONID=dueno-sintetico')
    assert.equal(solicitudes.at(-1).headers['x-csrf-token'], undefined)
    const conexion = await fetch(`${base}/api/v1/rfid-1/estado-conexion`, {
      headers: {
        cookie: 'JSESSIONID=dueno-sintetico',
        authorization: 'Bearer token-dispositivo-sintetico',
      },
    })
    assert.equal(conexion.status, 200)
    privado(conexion)
    assert.deepEqual(await conexion.json(), {
      estado: 'CONECTADO',
      actualizadoEn: '2026-10-29T12:00:00Z',
    })
    assert.equal(solicitudes.at(-1).path, '/api/v1/rfid-1/estado-conexion')
    assert.equal(solicitudes.at(-1).headers.cookie, 'JSESSIONID=dueno-sintetico')
    assert.equal(solicitudes.at(-1).headers.authorization, undefined)
    const conexionAnonima = await fetch(`${base}/api/v1/rfid-1/estado-conexion`)
    assert.equal(conexionAnonima.status, 401)
    assert.equal(solicitudes.at(-1).headers.cookie, undefined)
    const estado = await fetch(`${base}/api/v1/rfid-1/capturas/${CAPTURA_ID}`, {
      headers: { cookie: 'JSESSIONID=dueno-sintetico' },
    })
    assert.equal(estado.status, 200)
    privado(estado)
    assert.equal((await estado.json()).estado, 'ESCANEANDO')
    assert.equal(solicitudes.at(-1).path, `/api/v1/rfid-1/capturas/${CAPTURA_ID}`)
    const cancelar = await fetch(`${base}/api/v1/rfid-1/capturas/${CAPTURA_ID}`, {
      method: 'DELETE',
      headers: { cookie: 'JSESSIONID=dueno-sintetico', 'x-csrf-token': 'csrf-sintetico' },
    })
    assert.equal(cancelar.status, 204)
    assert.equal(await cancelar.text(), '')
    privado(cancelar)
    assert.equal(solicitudes.at(-1).method, 'DELETE')
    assert.equal(solicitudes.at(-1).headers['x-csrf-token'], 'csrf-sintetico')
    const vistaPrevia = await fetch(`${base}/api/v1/rfid-1/capturas/${CAPTURA_ID}/vista-previa`, {
      headers: { cookie: 'JSESSIONID=dueno-sintetico' },
    })
    assert.equal(vistaPrevia.status, 200)
    privado(vistaPrevia)
    assert.equal((await vistaPrevia.json()).uid, UID_SINTETICA)

    const confirmar = await fetch(`${base}/api/v1/rfid-1/capturas/${CAPTURA_ID}/confirmacion`, {
      method: 'POST',
      headers: {
        cookie: 'JSESSIONID=dueno-sintetico',
        'x-csrf-token': 'csrf-sintetico',
        'idempotency-key': 'clave-confirmacion-sintetica',
        authorization: 'Bearer token-dispositivo-sintetico',
      },
    })
    assert.equal(confirmar.status, 200)
    privado(confirmar)
    assert.equal((await confirmar.json()).estado, 'COMPLETADA')
    assert.equal(solicitudes.at(-1).headers['x-csrf-token'], 'csrf-sintetico')
    assert.equal(solicitudes.at(-1).headers['idempotency-key'], 'clave-confirmacion-sintetica')
    assert.equal(solicitudes.at(-1).headers.authorization, undefined)
    assert.equal(solicitudes.at(-1).body, '', 'La UID nunca se reenvía en el cuerpo de confirmación')
  } finally {
    await servidor.cerrar()
  }
}
