import assert from 'node:assert/strict'
import { once } from 'node:events'
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { setTimeout as pause } from 'node:timers/promises'

export const CAPTURA_ID = 'a'.repeat(32)
export const ASOCIACION_ID = 17
export const UID_SINTETICA = '04A1B2C3'

function responderJson(res, estado, cuerpo, headers = {}) {
  res.writeHead(estado, { 'content-type': 'application/json; charset=utf-8', ...headers })
  res.end(JSON.stringify(cuerpo))
}

async function iniciarServidorWeb(api) {
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

export function privado(respuesta) {
  assert.match(respuesta.headers.get('cache-control') ?? '', /no-store, private/)
  assert.match(respuesta.headers.get('vary') ?? '', /Cookie/i)
}

export async function iniciarRfid1Bff() {
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

  const { base, web } = await iniciarServidorWeb(api)
  return {
    base,
    solicitudes,
    async cerrar() {
      web.kill('SIGTERM')
      await Promise.race([once(web, 'exit'), pause(3_000)])
      await new Promise((resolve) => api.close(resolve))
    },
  }
}
