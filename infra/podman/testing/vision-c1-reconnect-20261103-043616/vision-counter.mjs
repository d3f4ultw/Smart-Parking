import http from 'node:http'

const destino = new URL(process.env.QA_API_UPSTREAM || 'http://api:8080')
const puerto = Number(process.env.QA_COUNTER_PORT || 8081)
let lecturasVision = 0
let lecturasVisionDetalle = []
let solicitudesEventos = 0
let solicitudesHeartbeat = 0
let altasEmpleado = 0
let heartbeatsObservados = 0
let heartbeatsSseConId = 0
let heartbeatsSseSinId = 0
let cierresSseTrasHeartbeat = 0
let cerrarSsePendiente = false
let solicitudesEventosConCursor = 0
let solicitudesEventosConLastEventId = 0
let getVisionActivos = 0
let maxGetVisionActivos = 0
let eventSourcesActivos = 0
let maxEventSourcesActivos = 0
let eventosSse = []
const conteoEventosSse = Object.create(null)

function registrarEvento(tipo, id, tieneId) {
  if (!tipo) return
  conteoEventosSse[tipo] = (conteoEventosSse[tipo] || 0) + 1
  const coincidencia = /(?:^|[:.])(\d+)$/.exec(id || '')
  eventosSse.push({ tipo, orden: coincidencia ? Number(coincidencia[1]) : null, tieneId, enMs: Date.now() })
  if (eventosSse.length > 2048) eventosSse = eventosSse.slice(-2048)
}

function leerEventosSse(fragmento, estado) {
  estado.pendiente += fragmento.toString('utf8')
  const marcos = estado.pendiente.split(/\r?\n\r?\n/)
  estado.pendiente = marcos.pop() || ''
  let vioHeartbeat = false
  for (const marco of marcos) {
    let tipo = ''
    let id = ''
    let tieneId = false
    for (const linea of marco.split(/\r?\n/)) {
      if (linea.startsWith('event:')) tipo = linea.slice(6).trim()
      else if (linea.startsWith('id:')) {
        id = linea.slice(3).trim()
        tieneId = true
      }
    }
    if (tipo.startsWith('vision.') || tipo.startsWith('empleado.')) registrarEvento(tipo, id, tieneId)
    if (tipo === 'empleado.heartbeat') {
      heartbeatsObservados += 1
      if (tieneId) heartbeatsSseConId += 1
      else heartbeatsSseSinId += 1
      vioHeartbeat = true
    }
  }
  return vioHeartbeat
}

function responderJson(respuesta, estado, cuerpo) {
  respuesta.writeHead(estado, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  })
  respuesta.end(JSON.stringify(cuerpo))
}

const servidor = http.createServer((solicitud, respuesta) => {
  const url = new URL(solicitud.url || '/', 'http://vision-counter')
  if (solicitud.method === 'GET' && url.pathname === '/__conteo') {
    responderJson(respuesta, 200, {
      lecturasVision,
      lecturasVisionDetalle,
      getVisionActivos,
      maxGetVisionActivos,
      solicitudesEventos,
      eventSourcesActivos,
      maxEventSourcesActivos,
      solicitudesHeartbeat,
      altasEmpleado,
      heartbeatsObservados,
      heartbeatsSseConId,
      heartbeatsSseSinId,
      cierresSseTrasHeartbeat,
      cerrarSsePendiente,
      solicitudesEventosConCursor,
      solicitudesEventosConLastEventId,
      eventosSse,
      conteoEventosSse,
    })
    return
  }
  if (solicitud.method === 'POST' && url.pathname === '/__reiniciar-conteo') {
    lecturasVision = 0
    lecturasVisionDetalle = []
    solicitudesEventos = 0
    solicitudesHeartbeat = 0
    altasEmpleado = 0
    heartbeatsObservados = 0
    heartbeatsSseConId = 0
    heartbeatsSseSinId = 0
    cierresSseTrasHeartbeat = 0
    cerrarSsePendiente = false
    solicitudesEventosConCursor = 0
    solicitudesEventosConLastEventId = 0
    eventosSse = []
    for (const tipo of Object.keys(conteoEventosSse)) delete conteoEventosSse[tipo]
    maxGetVisionActivos = getVisionActivos
    maxEventSourcesActivos = eventSourcesActivos
    respuesta.writeHead(204, { 'cache-control': 'no-store' })
    respuesta.end()
    return
  }
  if (solicitud.method === 'POST' && url.pathname === '/__armar-cierre-sse-tras-heartbeat') {
    if (eventSourcesActivos < 1) {
      responderJson(respuesta, 409, { ok: false, error: 'SSE_NO_ACTIVO' })
      return
    }
    cerrarSsePendiente = true
    respuesta.writeHead(204, { 'cache-control': 'no-store' })
    respuesta.end()
    return
  }

  const esLecturaVision = solicitud.method === 'GET' && url.pathname === '/api/v1/vision/cajones'
  const esSse = solicitud.method === 'GET' && url.pathname === '/api/v1/eventos/administracion'
  const esAltaEmpleado = solicitud.method === 'POST' && url.pathname === '/api/v1/empleados'
  const iniciadaEnMs = Date.now()
  if (esLecturaVision) {
    lecturasVision += 1
    getVisionActivos += 1
    maxGetVisionActivos = Math.max(maxGetVisionActivos, getVisionActivos)
  }
  if (esSse) {
    solicitudesEventos += 1
    if (url.searchParams.has('despues')) solicitudesEventosConCursor += 1
    if (solicitud.headers['last-event-id']) solicitudesEventosConLastEventId += 1
    eventSourcesActivos += 1
    maxEventSourcesActivos = Math.max(maxEventSourcesActivos, eventSourcesActivos)
  }
  if (solicitud.method === 'POST' && url.pathname === '/api/v1/eventos/administracion/heartbeat')
    solicitudesHeartbeat += 1
  if (esAltaEmpleado) altasEmpleado += 1

  let liberadaVision = false
  let liberadaSse = false
  const liberarVision = () => {
    if (!esLecturaVision || liberadaVision) return
    liberadaVision = true
    getVisionActivos = Math.max(0, getVisionActivos - 1)
  }
  const liberarSse = () => {
    if (!esSse || liberadaSse) return
    liberadaSse = true
    eventSourcesActivos = Math.max(0, eventSourcesActivos - 1)
  }
  respuesta.once('finish', () => {
    liberarVision()
    liberarSse()
  })
  respuesta.once('close', () => {
    liberarVision()
    liberarSse()
  })

  const encabezados = { ...solicitud.headers, host: destino.host }
  delete encabezados.connection
  delete encabezados['keep-alive']
  const aguasArriba = http.request({
    protocol: destino.protocol,
    hostname: destino.hostname,
    port: destino.port,
    method: solicitud.method,
    path: solicitud.url,
    headers: encabezados,
  }, (respuestaAguasArriba) => {
    if (esSse) {
      const parser = { pendiente: '' }
      respuestaAguasArriba.on('data', (fragmento) => {
        const vioHeartbeat = leerEventosSse(fragmento, parser)
        if (!vioHeartbeat || !cerrarSsePendiente) return
        cerrarSsePendiente = false
        cierresSseTrasHeartbeat += 1
        setImmediate(() => {
          respuestaAguasArriba.unpipe(respuesta)
          respuestaAguasArriba.destroy()
          if (!respuesta.writableEnded && !respuesta.destroyed) respuesta.end()
        })
      })
      respuesta.writeHead(
        respuestaAguasArriba.statusCode || 502,
        respuestaAguasArriba.statusMessage,
        respuestaAguasArriba.headers,
      )
      respuestaAguasArriba.pipe(respuesta)
      return
    }
    if (!esLecturaVision) {
      respuesta.writeHead(
        respuestaAguasArriba.statusCode || 502,
        respuestaAguasArriba.statusMessage,
        respuestaAguasArriba.headers,
      )
      respuestaAguasArriba.pipe(respuesta)
      return
    }
    const fragmentos = []
    respuestaAguasArriba.on('data', (fragmento) => fragmentos.push(fragmento))
    respuestaAguasArriba.on('end', () => {
      const cuerpo = Buffer.concat(fragmentos)
      let estados = []
      try {
        const cajones = JSON.parse(cuerpo.toString('utf8'))
        if (Array.isArray(cajones)) {
          estados = cajones.map((cajon) => ({
            etiqueta: typeof cajon.etiqueta === 'string' ? cajon.etiqueta : '',
            estado: typeof cajon.estado === 'string' ? cajon.estado : '',
            ultimoEstadoConfirmado:
              typeof cajon.ultimoEstadoConfirmado === 'string' ? cajon.ultimoEstadoConfirmado : null,
          }))
        }
      } catch {
        estados = []
      }
      const completadaEnMs = Date.now()
      lecturasVisionDetalle.push({
        iniciadaEnMs,
        completadaEnMs,
        demoraMs: completadaEnMs - iniciadaEnMs,
        estadoHttp: respuestaAguasArriba.statusCode || 502,
        ttlMs: respuestaAguasArriba.headers['x-vision-vigencia-restante-ms'] || null,
        estados,
      })
      if (lecturasVisionDetalle.length > 1024) lecturasVisionDetalle.shift()
      respuesta.writeHead(
        respuestaAguasArriba.statusCode || 502,
        respuestaAguasArriba.statusMessage,
        respuestaAguasArriba.headers,
      )
      respuesta.end(cuerpo)
    })
  })
  aguasArriba.on('error', () => {
    if (!respuesta.headersSent) respuesta.writeHead(502, { 'cache-control': 'no-store' })
    respuesta.end()
  })
  solicitud.pipe(aguasArriba)
})

servidor.listen(puerto, '0.0.0.0')
