import { once } from 'node:events'
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { setTimeout as pause } from 'node:timers/promises'

export async function iniciarEmpleadosBff() {
  let cancelacionesSse = 0
  const solicitudes = []
  const api = createServer(async (req, res) => {
    const url = new URL(req.url ?? '/', 'http://127.0.0.1')
    const partes = []
    for await (const parte of req) partes.push(parte)
    const cuerpo = Buffer.concat(partes).toString('utf8')
    solicitudes.push({
      method: req.method,
      path: url.pathname,
      search: url.search,
      headers: req.headers,
      body: cuerpo,
    })

    if (url.pathname === '/api/v1/empleados' && req.method === 'GET') {
      responderJson(res, 200, {
        items: [],
        pagina: 2,
        tamanoPagina: 10,
        totalRegistros: 11,
        totalPaginas: 2,
        cursorEventos: 'epoch-1:7',
      })
      return
    }
    if (url.pathname === '/api/v1/empleados' && req.method === 'POST') {
      responderJson(res, 201, { id: 12, codigo: 'E-0012' })
      return
    }
    if (url.pathname === '/api/v1/empleados/9223372036854775807' && req.method === 'GET') {
      res.writeHead(200, {
        'content-type': 'application/json; charset=utf-8',
        etag: '"9007199254740993"',
      })
      res.end(
        JSON.stringify({
          id: 9007199254740992,
          idTexto: '9223372036854775807',
          codigo: 'E-0012',
          nombres: 'Ana',
          primerApellido: 'Luz',
          segundoApellido: null,
          estado: 'ACTIVO',
          revision: 9007199254740992,
          revisionTexto: '9007199254740993',
          correo: null,
          operador: null,
        }),
      )
      return
    }
    if (url.pathname === '/api/v1/empleados/12/estado' && req.method === 'PATCH') {
      responderJson(res, 200, {
        id: 12,
        codigo: 'E-0012',
        nombres: 'Ana',
        primerApellido: 'Luz',
        segundoApellido: null,
        estado: 'INACTIVO',
        revision: 2,
      })
      return
    }
    if (url.pathname === '/api/v1/empleados/9223372036854775807/correo' && req.method === 'PATCH') {
      responderJson(res, 200, {
        empleadoId: '9223372036854775807',
        correo: null,
        estadoOperador: null,
        revisionEmpleado: '9007199254740994',
        estadoInvitacion: null,
      })
      return
    }
    if (
      url.pathname === '/api/v1/empleados/9223372036854775807/operador/promocion' &&
      req.method === 'POST'
    ) {
      responderJson(res, 200, {
        empleadoId: '9223372036854775807',
        operadorId: '00000000-0000-4000-8000-000000000009',
        estadoOperador: 'PENDIENTE',
        revisionEmpleado: '9007199254740994',
        estadoInvitacion: 'ENVIADO',
      })
      return
    }
    if (
      url.pathname === '/api/v1/empleados/9223372036854775807/operador/desactivacion' &&
      req.method === 'POST'
    ) {
      responderJson(res, 200, {
        empleadoId: '9223372036854775807',
        operadorId: '00000000-0000-4000-8000-000000000009',
        estadoOperador: 'INACTIVA',
        revisionEmpleado: '9007199254740995',
        estadoInvitacion: null,
      })
      return
    }
    if (
      url.pathname === '/api/v1/empleados/9223372036854775807/operador/vinculacion' &&
      req.method === 'POST'
    ) {
      responderJson(res, 200, {
        empleadoId: '9223372036854775807',
        operadorId: '00000000-0000-4000-8000-000000000009',
        estadoOperador: 'ACTIVA',
        revisionEmpleado: '9007199254740996',
        estadoInvitacion: null,
      })
      return
    }
    if (url.pathname === '/api/v1/eventos/administracion' && req.method === 'GET') {
      res.writeHead(200, {
        'content-type': 'text/event-stream; charset=utf-8',
        'cache-control': 'no-store, private',
        vary: 'Cookie',
        'x-accel-buffering': 'no',
      })
      res.write('id: epoch-1:8\nevent: empleado.directorio.actualizado\ndata: {}\n\n')
      let keepAlive
      res.on('close', () => {
        if (keepAlive) clearInterval(keepAlive)
        cancelacionesSse += 1
      })
      if (url.searchParams.get('despues') === 'fallo') {
        setTimeout(() => res.destroy(), 50)
        return
      }
      keepAlive = setInterval(() => res.write(': latido\n\n'), 250)
      return
    }
    if (url.pathname === '/api/v1/eventos/administracion/heartbeat' && req.method === 'POST') {
      res.writeHead(204)
      res.end()
      return
    }
    responderJson(res, 404, { codigo: 'NO_ENCONTRADO' })
  })

  function responderJson(res, status, data) {
    res.writeHead(status, { 'content-type': 'application/json; charset=utf-8' })
    res.end(JSON.stringify(data))
  }

  await new Promise((resolve) => api.listen(0, '127.0.0.1', resolve))
  const puertoApi = api.address().port
  const reservado = createServer()
  await new Promise((resolve) => reservado.listen(0, '127.0.0.1', resolve))
  const puertoWeb = reservado.address().port
  await new Promise((resolve) => reservado.close(resolve))

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
  web.stdout.on('data', (chunk) => salida.push(String(chunk)))
  web.stderr.on('data', (chunk) => salida.push(String(chunk)))

  const base = `http://127.0.0.1:${puertoWeb}`
  let listo = false
  for (let intento = 0; intento < 100; intento += 1) {
    if (web.exitCode !== null) break
    try {
      const respuesta = await fetch(`${base}/api/v1/empleados?pagina=1`)
      if (respuesta.status < 500) {
        listo = true
        break
      }
    } catch {}
    await pause(100)
  }

  return {
    base,
    listo,
    salida,
    solicitudes,
    get cancelacionesSse() {
      return cancelacionesSse
    },
    async cerrar() {
      web.kill('SIGTERM')
      await Promise.race([once(web, 'exit'), pause(3_000)])
      await new Promise((resolve) => api.close(resolve))
    },
  }
}
