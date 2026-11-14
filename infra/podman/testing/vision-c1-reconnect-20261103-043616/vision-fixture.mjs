import { randomUUID } from 'node:crypto'
import { readFile, rename, unlink, writeFile } from 'node:fs/promises'
import http from 'node:http'
import path from 'node:path'

const baseURL = process.env.QA_API_BASE_URL || 'http://api:8080'
const port = Number(process.env.QA_FIXTURE_PORT || 8082)
const sourceId = process.env.QA_VISION_SOURCE_ID
const token = process.env.QA_VISION_TOKEN
const fixtureDir = process.env.QA_FIXTURE_DIR || '/fixtures'
const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
let sessionId = null
let revision = null
let calibrationHash = null
let zones = []
let states = new Map()
let sequence = 0
let inFlight = false

if (!sourceId || !uuidV4.test(sourceId) || !token) {
  throw new Error('Falta la fuente sintética configurada o el token privado.')
}

async function leerJson(solicitud) {
  const chunks = []
  let bytes = 0
  for await (const chunk of solicitud) {
    bytes += chunk.length
    if (bytes > 64 * 1024) throw new Error('Solicitud de fixture demasiado grande.')
    chunks.push(chunk)
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'))
}

function responder(respuesta, estado, cuerpo) {
  respuesta.writeHead(estado, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  })
  respuesta.end(JSON.stringify(cuerpo))
}

async function postApi(ruta, cuerpo) {
  const respuesta = await fetch(new URL(ruta, baseURL), {
    method: 'POST',
    headers: {
      authorization: 'Bearer ' + token,
      'content-type': 'application/json',
    },
    body: JSON.stringify(cuerpo),
  })
  if (!respuesta.ok) {
    throw new Error('API Vision HTTP ' + respuesta.status + ' en ' + ruta + '.')
  }
  return respuesta.json()
}

async function leerMarcaCommit(observadoEn) {
  const id = randomUUID()
  const temporal = path.join(fixtureDir, 'consulta-' + id + '.tmp')
  const solicitud = path.join(fixtureDir, 'consulta-commit.json')
  const resultado = path.join(fixtureDir, 'marca-commit-' + id + '.json')
  await writeFile(temporal, JSON.stringify({ id, observadoEn }), { mode: 0o600 })
  await rename(temporal, solicitud)
  for (let intento = 0; intento < 100; intento += 1) {
    try {
      const marca = JSON.parse(await readFile(resultado, 'utf8'))
      await unlink(resultado)
      if (!marca.ok || typeof marca.commitAt !== 'string') return null
      return marca.commitAt
    } catch (error) {
      if (error.code !== 'ENOENT') throw error
      await new Promise((resolver) => setTimeout(resolver, 50))
    }
  }
  return null
}

async function cambiarControlRollback(accion) {
  const id = randomUUID()
  const temporal = path.join(fixtureDir, 'solicitud-' + id + '.tmp')
  const solicitud = path.join(fixtureDir, 'solicitud.json')
  const resultado = path.join(fixtureDir, 'respuesta-' + id + '.json')
  await writeFile(temporal, JSON.stringify({ id, accion }), { mode: 0o600 })
  await rename(temporal, solicitud)
  for (let intento = 0; intento < 100; intento += 1) {
    try {
      const respuesta = JSON.parse(await readFile(resultado, 'utf8'))
      await unlink(resultado)
      if (!respuesta.ok) throw new Error('La fixture SQL no pudo actualizar el control de rollback.')
      return { ok: true }
    } catch (error) {
      if (error.code !== 'ENOENT') throw error
      await new Promise((resolver) => setTimeout(resolver, 50))
    }
  }
  throw new Error('La fixture SQL no respondió al control de rollback.')
}

async function enviarObservacion() {
  if (!sessionId || revision === null || !calibrationHash || zones.length === 0) {
    throw new Error('La fuente sintética aún no tiene sesión o calibración.')
  }
  sequence += 1
  const observedAt = new Date().toISOString()
  const cuerpo = {
    fuenteId: sourceId,
    sesionId: sessionId,
    secuencia: sequence,
    solicitudId: randomUUID(),
    revisionCalibracion: revision,
    hashCalibracion: calibrationHash,
    observadoEn: observedAt,
    zonas: zones.map((zone) => ({
      visionZoneId: zone.visionZoneId,
      estado: states.get(zone.visionZoneId),
    })),
  }
  await postApi('/api/v1/dispositivos/vision/observaciones', cuerpo)
  const commitAt = await leerMarcaCommit(observedAt)
  return { ok: true, secuencia: sequence, observadoEn: observedAt, commitAt }
}

async function preparar(cuerpo) {
  const newRevision = Number(cuerpo.revisionCalibracion)
  const newHash = cuerpo.hashCalibracion
  const newZones = cuerpo.zonas
  if (!Number.isSafeInteger(newRevision) || newRevision < 1
      || typeof newHash !== 'string' || !/^[0-9a-f]{64}$/i.test(newHash)
      || !Array.isArray(newZones) || newZones.length < 1 || newZones.length > 32) {
    throw new Error('Calibración sintética inválida.')
  }
  const ids = new Set()
  for (const zone of newZones) {
    if (!zone || typeof zone.visionZoneId !== 'string' || !uuidV4.test(zone.visionZoneId)
        || !['LIBRE', 'OCUPADO'].includes(zone.estado) || ids.has(zone.visionZoneId)) {
      throw new Error('Zona sintética inválida.')
    }
    ids.add(zone.visionZoneId)
  }
  revision = newRevision
  calibrationHash = newHash.toLowerCase()
  zones = newZones.map((zone) => ({ visionZoneId: zone.visionZoneId }))
  states = new Map(newZones.map((zone) => [zone.visionZoneId, zone.estado]))
  sequence = 0
  const sesion = await postApi('/api/v1/dispositivos/vision/sesiones', {
    fuenteId: sourceId,
    solicitudId: randomUUID(),
    iniciadaEn: new Date().toISOString(),
  })
  if (!sesion.sesionId || !uuidV4.test(sesion.sesionId)) {
    throw new Error('La API no devolvió el identificador de sesión esperado.')
  }
  sessionId = sesion.sesionId
  const observacion = await enviarObservacion()
  return { ok: true, secuencia: observacion.secuencia, commitAt: observacion.commitAt }
}

async function cambiar(cuerpo) {
  if (!Array.isArray(cuerpo.cambios) || cuerpo.cambios.length < 1 || cuerpo.cambios.length > 32) {
    throw new Error('Cambios sintéticos inválidos.')
  }
  const estadosAnteriores = new Map(states)
  const secuenciaAnterior = sequence
  for (const cambio of cuerpo.cambios) {
    if (!cambio || !states.has(cambio.visionZoneId)
        || !['LIBRE', 'OCUPADO'].includes(cambio.estado)) {
      throw new Error('Cambio sintético fuera del mapa activo.')
    }
    states.set(cambio.visionZoneId, cambio.estado)
  }
  try {
    return await enviarObservacion()
  } catch (error) {
    states = estadosAnteriores
    sequence = secuenciaAnterior
    throw error
  }
}

async function calibrar(cuerpo) {
  if (!Array.isArray(cuerpo.zonas) || cuerpo.zonas.length < 1 || cuerpo.zonas.length > 32) {
    throw new Error('Mapa sintético inválido.')
  }
  const ruta = `/api/v1/vision/fuentes/${sourceId}/calibracion`
  const headers = { authorization: 'Bearer ' + token, 'content-type': 'application/json' }
  const guardado = await fetch(new URL(ruta, baseURL), {
    method: 'PUT', headers, body: JSON.stringify({ zonas: cuerpo.zonas }),
  })
  if (guardado.status !== 204) throw new Error('No se pudo guardar el mapa sintético.')
  const lectura = await fetch(new URL(ruta, baseURL), { headers })
  if (!lectura.ok) throw new Error('No se pudo consultar el mapa sintético.')
  return lectura.json()
}

const servidor = http.createServer(async (solicitud, respuesta) => {
  const url = new URL(solicitud.url || '/', 'http://vision-fixture')
  if (solicitud.method === 'GET' && url.pathname === '/__health') {
    responder(respuesta, 200, { ok: true })
    return
  }
  if (solicitud.method === 'GET' && url.pathname === '/__estado') {
    responder(respuesta, 200, {
      ok: Boolean(sessionId && revision !== null && calibrationHash && zones.length),
      zonas: zones.map((zone) => ({
        visionZoneId: zone.visionZoneId,
        estado: states.get(zone.visionZoneId),
      })),
    })
    return
  }
  const rutas = [
    '/__calibrar',
    '/__preparar',
    '/__observar',
    '/__armar_rollback',
    '/__desarmar_rollback',
  ]
  if (solicitud.method !== 'POST' || !rutas.includes(url.pathname)) {
    responder(respuesta, 404, { ok: false, error: 'NO_ENCONTRADO' })
    return
  }
  if (inFlight) {
    responder(respuesta, 409, { ok: false, error: 'SOLICITUD_EN_CURSO' })
    return
  }
  inFlight = true
  try {
    const cuerpo = await leerJson(solicitud)
    const resultado =
      url.pathname === '/__calibrar'
        ? await calibrar(cuerpo)
        : url.pathname === '/__preparar'
        ? await preparar(cuerpo)
        : url.pathname === '/__observar'
          ? await cambiar(cuerpo)
          : await cambiarControlRollback(
              url.pathname === '/__armar_rollback' ? 'armar_rollback' : 'desarmar_rollback',
            )
    responder(respuesta, 200, resultado)
  } catch (error) {
    const mensaje = error instanceof Error ? error.message : 'Error de fixture.'
    responder(respuesta, 500, { ok: false, error: mensaje })
  } finally {
    inFlight = false
  }
})

servidor.listen(port, '0.0.0.0')
