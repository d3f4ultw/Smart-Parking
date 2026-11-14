import assert from 'node:assert/strict'
import { once } from 'node:events'
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { setTimeout as pause } from 'node:timers/promises'

const CAPTURA_ID = 'a'.repeat(32)
const ASOCIACION_ID = 17
const UID_SINTETICA = '04A1B2C3'
const solicitudes = []
const api = createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', 'http://127.0.0.1')
  const partes = []
  for await (const parte of req) partes.push(parte)
  const solicitud = {
    method: req.method,
    path: url.pathname,
    search: url.search,
    headers: req.headers,
    body: Buffer.concat(partes).toString('utf8'),
  }
  solicitudes.push(solicitud)

  if (!req.headers.cookie?.startsWith('JSESSIONID=')) {
    responderJson(res, 401, { codigo: 'SESION_NO_VIGENTE' })
  } else if (req.method === 'POST' && url.pathname === '/api/v1/rfid-1/capturas') {
    responderJson(
      res,
      201,
      { capturaId: CAPTURA_ID, estado: 'PENDIENTE', expiraEn: '2026-10-27T22:00:00Z' },
      { 'set-cookie': 'JSESSIONID=sesion-renovada; Path=/; HttpOnly; SameSite=Strict' },
    )
  } else if (req.method === 'GET' && url.pathname === '/api/v1/rfid-1/estado-conexion') {
    responderJson(res, 200, { estado: 'CONECTADO', actualizadoEn: '2026-10-29T12:00:00Z' })
  } else if (req.method === 'GET' && url.pathname.endsWith('/capturas/activa')) {
    res.writeHead(204)
    res.end()
  } else if (req.method === 'GET' && url.pathname === '/api/v1/tarjetas-rfid/personas') {
    responderJson(res, 200, [
      {
        tipoEntidad: 'CLIENTE',
        codigoPersona: 'CLI-0001',
        nombreCompleto: 'Cliente Sintético',
        estadoAdministrativo: 'ACTIVO',
        elegible: true,
        motivoNoElegible: null,
      },
    ])
  } else if (req.method === 'GET' && url.pathname === '/api/v1/tarjetas-rfid') {
    responderJson(res, 200, {
      items: [
        {
          asociacionId: ASOCIACION_ID,
          uid: UID_SINTETICA,
          tipoEntidad: 'CLIENTE',
          codigoPersona: 'CLI-0001',
          nombreCompleto: 'Cliente Sintético',
          estado: 'ACTIVA',
          asociadaEn: '2026-10-28T12:00:00Z',
          canceladaEn: null,
        },
      ],
      pagina: 1,
      tamano: 10,
      total: 1,
      totalPaginas: 1,
    })
  } else if (req.method === 'GET' && url.pathname === `/api/v1/tarjetas-rfid/${ASOCIACION_ID}`) {
    responderJson(res, 200, {
      asociacionId: ASOCIACION_ID,
      uid: UID_SINTETICA,
      tipoEntidad: 'CLIENTE',
      codigoPersona: 'CLI-0001',
      nombreCompleto: 'Cliente Sintético',
      estado: 'ACTIVA',
      asociadaEn: '2026-10-28T12:00:00Z',
      canceladaEn: null,
    })
  } else if (
    req.method === 'POST' &&
    url.pathname === `/api/v1/tarjetas-rfid/${ASOCIACION_ID}/cancelacion`
  ) {
    responderJson(res, 200, { asociacionId: ASOCIACION_ID, estado: 'CANCELADA' })
  } else if (
    req.method === 'GET' &&
    url.pathname === `/api/v1/rfid-1/capturas/${CAPTURA_ID}/vista-previa`
  ) {
    responderJson(res, 200, {
      uid: UID_SINTETICA,
      previsualizadaEn: '2026-10-28T12:01:00Z',
      confirmacionVenceEn: '2026-10-28T12:06:00Z',
    })
  } else if (
    req.method === 'POST' &&
    url.pathname === `/api/v1/rfid-1/capturas/${CAPTURA_ID}/confirmacion`
  ) {
    responderJson(res, 200, {
      capturaId: CAPTURA_ID,
      asociacionId: ASOCIACION_ID,
      estado: 'COMPLETADA',
      resultado: 'ASOCIADA',
    })
  } else if (req.method === 'GET' && url.pathname.endsWith(`/capturas/${CAPTURA_ID}`)) {
    responderJson(res, 200, {
      capturaId: CAPTURA_ID,
      tipoEntidad: 'CLIENTE',
      codigoPersona: 'CLI-0001',
      estado: 'ESCANEANDO',
      expiraEn: '2026-10-27T22:00:00Z',
    })
  } else if (req.method === 'DELETE' && url.pathname.endsWith(`/capturas/${CAPTURA_ID}`)) {
    res.writeHead(204)
    res.end()
  } else {
    responderJson(res, 404, { codigo: 'NO_ENCONTRADO' })
  }
})

function responderJson(res, estado, cuerpo, headers = {}) {
  res.writeHead(estado, { 'content-type': 'application/json; charset=utf-8', ...headers })
  res.end(JSON.stringify(cuerpo))
}

async function iniciarServidorWeb() {
  await new Promise((resolve) => api.listen(0, '127.0.0.1', resolve))
  const puertoApi = api.address().port
  const reservado = createServer()
  await new Promise((resolve) => reservado.listen(0, '127.0.0.1', resolve))
  const puertoWeb = reservado.address().port
  await new Promise((resolve) => reservado.close(resolve))
  const salida = []
  const web = spawn(process.execPath, ['.output/server/index.mjs'], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      NUXT_API_INTERNAL_BASE: `http://127.0.0.1:${puertoApi}`,
      NITRO_HOST: '127.0.0.1',
      NITRO_PORT: String(puertoWeb),
      HOST: '127.0.0.1',
      PORT: String(puertoWeb),
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  web.stdout.on('data', (chunk) => salida.push(String(chunk)))
  web.stderr.on('data', (chunk) => salida.push(String(chunk)))
  const base = `http://127.0.0.1:${puertoWeb}`
  let listo = false
  for (let intento = 0; intento < 100; intento += 1) {
    if (web.exitCode !== null) break
    try {
      const respuesta = await fetch(`${base}/api/v1/rfid-1/capturas/activa`)
      if (respuesta.status < 500) {
        listo = true
        break
      }
    } catch {}
    await pause(100)
  }
  if (!listo) {
    web.kill('SIGTERM')
    await Promise.race([once(web, 'exit'), pause(3_000)])
    await new Promise((resolve) => api.close(resolve))
    assert.fail(`El servidor Web no inició: ${salida.join('').slice(-2500)}`)
  }
  return { base, web }
}

function privado(respuesta) {
  assert.match(respuesta.headers.get('cache-control') ?? '', /no-store, private/)
  assert.match(respuesta.headers.get('vary') ?? '', /Cookie/i)
}

const { base, web } = await iniciarServidorWeb()
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
} finally {
  web.kill('SIGTERM')
  await Promise.race([once(web, 'exit'), pause(3_000)])
  await new Promise((resolve) => api.close(resolve))
}
