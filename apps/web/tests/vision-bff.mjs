import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createServer } from 'node:http'
import { setTimeout as pause } from 'node:timers/promises'

const solicitudes = []
const cajones = [
  {
    cajonId: 'a0000000-0000-4000-8000-000000000001',
    etiqueta: 'C1',
    estado: 'LIBRE',
    ultimoEstadoConfirmado: 'LIBRE',
    observadoEn: '2026-11-02T00:00:00Z',
  },
  {
    cajonId: 'a0000000-0000-4000-8000-000000000002',
    etiqueta: 'C2',
    estado: 'NO_VERIFICABLE',
    ultimoEstadoConfirmado: 'OCUPADO',
    observadoEn: '2026-11-01T00:00:00Z',
  },
]

function responder(respuesta, estado, datos, encabezados = {}) {
  respuesta.writeHead(estado, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store, private',
    vary: 'Cookie',
    ...encabezados,
  })
  respuesta.end(JSON.stringify(datos))
}

const api = createServer((solicitud, respuesta) => {
  const url = new URL(solicitud.url ?? '/', 'http://127.0.0.1')
  const cookie = solicitud.headers.cookie ?? ''
  const registrada = {
    metodo: solicitud.method,
    ruta: url.pathname,
    consulta: url.search,
    cookie,
    authorization: solicitud.headers.authorization,
    csrf: solicitud.headers['x-csrf-token'],
    contentType: solicitud.headers['content-type'],
    cuerpo: '',
  }
  solicitudes.push(registrada)
  if (cookie === 'JSESSIONID=fallo') {
    respuesta.destroy()
  } else if (cookie === 'JSESSIONID=dueno' && solicitud.method === 'PUT') {
    solicitud.setEncoding('utf8')
    solicitud.on('data', (parte) => { registrada.cuerpo += parte })
    solicitud.on('end', () => {
      respuesta.writeHead(204, { 'cache-control': 'no-store, private' })
      respuesta.end()
    })
  } else if (cookie === 'JSESSIONID=dueno') {
    responder(respuesta, 200, cajones, {
      'x-eventos-cursor': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa:12',
      'x-vision-vigencia-restante-ms': '12500',
      'set-cookie': [
        'JSESSIONID=renovada; Path=/; HttpOnly; SameSite=Strict',
        'preferencia=prueba; Path=/; SameSite=Strict',
      ],
    })
  } else if (cookie === 'JSESSIONID=operador') {
    responder(respuesta, 403, { codigo: 'ACCESO_DENEGADO' })
  } else {
    responder(respuesta, 401, { codigo: 'SESION_NO_VIGENTE' })
  }
})

async function reservarPuerto() {
  const servidor = createServer()
  await new Promise((resolve) => servidor.listen(0, '127.0.0.1', resolve))
  const puerto = servidor.address().port
  await new Promise((resolve) => servidor.close(resolve))
  return puerto
}

await new Promise((resolve) => api.listen(0, '127.0.0.1', resolve))
const puertoApi = api.address().port
const puertoWeb = await reservarPuerto()
const salida = []
const web = spawn('node', ['.output/server/index.mjs'], {
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
web.stdout.on('data', (parte) => salida.push(String(parte)))
web.stderr.on('data', (parte) => salida.push(String(parte)))

const base = `http://127.0.0.1:${puertoWeb}`
let listo = false
try {
  for (let intento = 0; intento < 100; intento += 1) {
    if (web.exitCode !== null) break
    try {
      const respuesta = await fetch(`${base}/api/v1/vision/cajones`)
      if (respuesta.status < 500) {
        listo = true
        break
      }
    } catch {}
    await pause(100)
  }
  assert.ok(listo, `El servidor Web no inició: ${salida.join('').slice(-2500)}`)

  const autorizada = await fetch(`${base}/api/v1/vision/cajones`, {
    headers: {
      cookie: 'otra=ignorada; CLIENTSESSIONID=cliente; JSESSIONID=dueno',
      authorization: 'Bearer credencial-sintetica',
    },
  })
  assert.equal(autorizada.status, 200)
  assert.deepEqual(await autorizada.json(), cajones)
  assert.match(autorizada.headers.get('cache-control') ?? '', /no-store, private/i)
  assert.match(autorizada.headers.get('vary') ?? '', /Cookie/i)
  assert.equal(autorizada.headers.getSetCookie().length, 2)
  assert.equal(
    autorizada.headers.get('x-eventos-cursor'),
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa:12',
  )
  assert.equal(autorizada.headers.get('x-vision-vigencia-restante-ms'), '12500')
  assert.equal(solicitudes.at(-1).cookie, 'JSESSIONID=dueno')
  assert.equal(solicitudes.at(-1).authorization, undefined)
  assert.equal(solicitudes.at(-1).consulta, '')

  const cajonId = 'a0000000-0000-4000-8000-000000000001'
  const rutaNombre = `/api/v1/vision/cajones/${cajonId}/display-name`
  const guardada = await fetch(`${base}${rutaNombre}`, {
    method: 'PUT',
    headers: {
      cookie: 'otra=ignorada; JSESSIONID=dueno',
      authorization: 'Bearer credencial-sintetica',
      'content-type': 'application/json',
      'x-csrf-token': 'csrf-sintetico',
    },
    body: JSON.stringify({ displayName: 'Entrada principal' }),
  })
  assert.equal(guardada.status, 204)
  assert.match(guardada.headers.get('cache-control') ?? '', /no-store, private/i)
  assert.equal(solicitudes.at(-1).cookie, 'JSESSIONID=dueno')
  assert.equal(solicitudes.at(-1).authorization, undefined)
  assert.equal(solicitudes.at(-1).csrf, 'csrf-sintetico')
  assert.match(solicitudes.at(-1).contentType, /application\/json/)
  assert.deepEqual(JSON.parse(solicitudes.at(-1).cuerpo), { displayName: 'Entrada principal' })

  for (const [cookie, estado] of [
    ['', 401],
    ['CLIENTSESSIONID=cliente', 401],
    ['JSESSIONID=operador', 403],
  ]) {
    const respuesta = await fetch(`${base}/api/v1/vision/cajones`, { headers: { cookie } })
    assert.equal(respuesta.status, estado)
    assert.match(respuesta.headers.get('cache-control') ?? '', /no-store, private/i)
    assert.match(respuesta.headers.get('vary') ?? '', /Cookie/i)
  }

  const denegadas = [
    ['GET', '/api/v1/vision/cajones?pagina=1'],
    ['GET', '/api/v1/vision/cajones?fuente=1'],
    ['GET', '/api/v1/vision/cajones/1'],
    ['POST', '/api/v1/vision/fuentes'],
    ['GET', '/api/v1/vision/fuentes/1/calibracion'],
    ['POST', '/api/v1/vision/cajones'],
    ['PUT', '/api/v1/vision/cajones'],
    ['PUT', '/api/v1/vision/cajones/no-es-uuid/display-name'],
    ['PUT', `${rutaNombre}?extra=1`],
    ['PUT', `${rutaNombre}/extra`],
    ['GET', rutaNombre],
    ['PATCH', rutaNombre],
    ['PATCH', '/api/v1/vision/cajones'],
    ['DELETE', '/api/v1/vision/cajones'],
    ['POST', '/api/v1/dispositivos/vision/sesiones'],
    ['POST', '/api/v1/dispositivos/vision/observaciones'],
  ]
  for (const [metodo, ruta] of denegadas) {
    const antes = solicitudes.length
    const respuesta = await fetch(`${base}${ruta}`, { method: metodo })
    assert.equal(respuesta.status, 404, `${metodo} ${ruta} debe ser rechazado`)
    assert.equal(solicitudes.length, antes, `${metodo} ${ruta} no debe alcanzar Java`)
  }

  const fallo = await fetch(`${base}/api/v1/vision/cajones`, {
    headers: { cookie: 'JSESSIONID=fallo' },
  })
  assert.equal(fallo.status, 503)
  assert.match(fallo.headers.get('cache-control') ?? '', /no-store, private/i)
  assert.equal((await fallo.json()).codigo, 'API_NO_DISPONIBLE')

  console.log('PASS: Vision BFF permite GET y PUT acotados y conserva sesión, CSRF y privacidad.')
} finally {
  web.kill('SIGTERM')
  api.closeAllConnections()
  await new Promise((resolve) => api.close(resolve))
}
