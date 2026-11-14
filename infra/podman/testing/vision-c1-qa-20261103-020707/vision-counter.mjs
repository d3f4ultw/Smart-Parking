import http from 'node:http'

const destino = new URL(process.env.QA_API_UPSTREAM || 'http://api:8080')
const puerto = Number(process.env.QA_COUNTER_PORT || 8081)
let lecturasVision = 0
const lecturasVisionDetalle = []
let solicitudesEventos = 0
let solicitudesHeartbeat = 0

const servidor = http.createServer((solicitud, respuesta) => {
  const url = new URL(solicitud.url || '/', 'http://vision-counter')
  if (solicitud.method === 'GET' && url.pathname === '/__conteo') {
    respuesta.writeHead(200, {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
    })
    respuesta.end(
      JSON.stringify({
        count: lecturasVision,
        lecturasVision,
        lecturasVisionDetalle,
        solicitudesEventos,
        solicitudesHeartbeat,
      }),
    )
    return
  }
  if (solicitud.method === 'POST' && url.pathname === '/__reiniciar-conteo') {
    lecturasVision = 0
    lecturasVisionDetalle.length = 0
    solicitudesEventos = 0
    solicitudesHeartbeat = 0
    respuesta.writeHead(204, { 'cache-control': 'no-store' })
    respuesta.end()
    return
  }

  const esLecturaVision = solicitud.method === 'GET' && url.pathname === '/api/v1/vision/cajones'
  const iniciadaEnMs = Date.now()
  if (esLecturaVision) lecturasVision += 1
  if (solicitud.method === 'GET' && url.pathname === '/api/v1/eventos/administracion') {
    solicitudesEventos += 1
  }
  if (solicitud.method === 'POST' && url.pathname === '/api/v1/eventos/administracion/heartbeat') {
    solicitudesHeartbeat += 1
  }

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
      if (lecturasVisionDetalle.length > 256) lecturasVisionDetalle.shift()
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
