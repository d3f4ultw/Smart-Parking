import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { setTimeout as pause } from 'node:timers/promises'

const solicitudes = []
const sesiones = new Map()
const eventoPrueba = {
  id: 73,
  ocurridoEn: '2026-10-31T18:00:00Z',
  ocurridoEnLocal: '2026-10-31T12:00:00-06:00',
  lector: 'RFID2',
  resultado: 'AUTORIZADA',
  motivo: null,
  persona: { tipo: 'CLIENTE', nombre: 'Persona Sintetica' },
}

function responder(respuesta, estado, datos, encabezados = {}) {
  respuesta.writeHead(estado, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store, private',
    vary: 'Cookie',
    ...encabezados,
  })
  respuesta.end(JSON.stringify(datos))
}

const api = createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', 'http://127.0.0.1')
  const cookies = req.headers.cookie ?? ''
  const requestId = req.headers['x-request-id']
  solicitudes.push({ method: req.method, path: url.pathname, search: url.search, cookie: cookies, requestId })

  if (req.method === 'POST' && url.pathname === '/api/v1/sesion') {
    for await (const _parte of req) {
      // El cuerpo sintético se consume sin conservarlo ni registrarlo.
    }
    responder(
      res,
      200,
      { autenticada: true, correo: 'persona@example.test', csrfToken: 'csrf-sintetico' },
      { 'set-cookie': 'JSESSIONID=sesion-nueva; Path=/; HttpOnly; SameSite=Strict' },
    )
    return
  }

  if (req.method === 'GET' && url.pathname === '/api/v1/sesion') {
    if (cookies.includes('JSESSIONID=fallo')) {
      responder(res, 503, { codigo: 'API_NO_DISPONIBLE', error: 'Respuesta sintética.' })
      return
    }
    const conteo = sesiones.get(cookies) ?? 0
    sesiones.set(cookies, conteo + 1)
    const dueno =
      cookies.includes('JSESSIONID=dueno') || (cookies.includes('JSESSIONID=vence') && conteo === 0)
    responder(res, 200, {
      autenticada: dueno,
      correo: dueno ? 'dueno@example.test' : null,
      rol: dueno ? 'DUENO' : null,
    })
    return
  }

  if (req.method === 'GET' && url.pathname === '/api/v1/accesos/historial') {
    if (!cookies.includes('JSESSIONID=dueno') && !cookies.includes('JSESSIONID=vence')) {
      responder(res, 401, { codigo: 'SESION_NO_VALIDA', error: 'Inicia sesión.' })
      return
    }
    if (cookies.includes('JSESSIONID=vence')) {
      responder(res, 401, { codigo: 'SESION_NO_VIGENTE', error: 'Tu sesión venció.' })
      return
    }
    responder(res, 200, {
      items: [eventoPrueba],
      pagina: Number(url.searchParams.get('pagina') ?? 1),
      tamano: 50,
      haySiguiente: false,
      zonaHoraria: 'America/Mexico_City',
      cursorEventos: 'epoch-web:2',
    })
    return
  }

  responder(res, 404, { codigo: 'NO_ENCONTRADO' })
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
web.stdout.on('data', (chunk) => salida.push(String(chunk)))
web.stderr.on('data', (chunk) => salida.push(String(chunk)))

const base = `http://127.0.0.1:${puertoWeb}`
let listo = false
for (let intento = 0; intento < 100; intento += 1) {
  if (web.exitCode !== null) break
  try {
    const respuesta = await fetch(
      `${base}/api/v1/accesos/historial?pagina=1&lector=TODOS&resultado=TODOS`,
    )
    if (respuesta.status < 500) {
      listo = true
      break
    }
  } catch {}
  await pause(100)
}

try {
  assert.ok(listo, `El servidor Web no inició: ${salida.join('').slice(-2500)}`)
  const antesAnonimo = solicitudes.filter(
    (solicitud) => solicitud.path === '/api/v1/accesos/historial',
  ).length
  const anonimo = await fetch(`${base}/admin/accesos`, { redirect: 'manual' })
  assert.equal(anonimo.status, 302)
  assert.equal(anonimo.headers.get('location'), '/panel')
  assert.equal(
    solicitudes.filter((solicitud) => solicitud.path === '/api/v1/accesos/historial').length,
    antesAnonimo,
  )

  const ssr = await fetch(`${base}/admin/accesos`, { headers: { cookie: 'JSESSIONID=dueno' } })
  assert.equal(ssr.status, 200)
  assert.match(ssr.headers.get('cache-control') ?? '', /no-store, private/)
  assert.match(ssr.headers.get('vary') ?? '', /Cookie/i)
  const html = await ssr.text()
  assert.ok(/Historial de accesos/.test(html), 'La carga SSR debe presentar la página protegida.')
  assert.ok(
    /Persona Sintetica/.test(html),
    'La carga SSR autorizada debe presentar la persona sintética.',
  )
  assert.ok(
    /2026-10-31 12:00:00-06:00/.test(html),
    'La carga SSR debe conservar la fecha local del servidor.',
  )
  const solicitudSsr = solicitudes.findLast(
    (solicitud) => solicitud.path === '/api/v1/accesos/historial',
  )
  assert.equal(solicitudSsr.cookie, 'JSESSIONID=dueno')
  assert.equal(solicitudSsr.search, '?pagina=1&lector=TODOS&resultado=TODOS')

  const inicioLogin = await fetch(`${base}/api/v1/sesion`, {
    method: 'POST',
    headers: {
      cookie: 'JSESSIONID=sesion-anterior',
      'content-type': 'application/json',
      'x-csrf-token': 'csrf-sintetico-entrada',
    },
    body: JSON.stringify({ correo: 'persona@example.test', contrasena: 'contrasena-sintetica' }),
  })
  assert.equal(inicioLogin.status, 200)
  const idLogin = inicioLogin.headers.get('x-request-id')
  assert.match(idLogin ?? '', /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/)
  assert.equal(solicitudes.at(-1).requestId, idLogin)
  assert.match(inicioLogin.headers.get('set-cookie') ?? '', /JSESSIONID=sesion-nueva/)

  const consultaSesion = await fetch(`${base}/api/v1/sesion`, {
    headers: { cookie: 'JSESSIONID=dueno' },
  })
  assert.equal(consultaSesion.status, 200)
  assert.equal((await consultaSesion.json()).autenticada, true)
  const idConsulta = consultaSesion.headers.get('x-request-id')
  assert.match(idConsulta ?? '', /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/)
  assert.equal(solicitudes.at(-1).requestId, idConsulta)

  const consultaConFalloSintetico = await fetch(`${base}/api/v1/sesion`, {
    headers: { cookie: 'JSESSIONID=fallo' },
  })
  assert.equal(consultaConFalloSintetico.status, 503)
  const idFallo = consultaConFalloSintetico.headers.get('x-request-id')
  assert.match(idFallo ?? '', /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/)
  assert.equal(solicitudes.at(-1).requestId, idFallo)

  for (let intento = 0; intento < 20; intento += 1) {
    const salidaCompleta = salida.join('')
    if ([idLogin, idConsulta, idFallo].every((id) => salidaCompleta.includes(id))) break
    await pause(10)
  }
  const lineasDiagnostico = salida
    .join('')
    .split(/\r?\n/)
    .filter((linea) => linea.includes('session_diagnostic '))
  const diagnosticos = lineasDiagnostico.map((linea) => JSON.parse(linea.slice(linea.indexOf('{'))))
  const diagnosticoLogin = diagnosticos.find((registro) => registro.requestId === idLogin)
  const diagnosticoConsulta = diagnosticos.find((registro) => registro.requestId === idConsulta)
  const diagnosticoFallo = diagnosticos.find((registro) => registro.requestId === idFallo)
  assert.equal(diagnosticoLogin.layer, 'bff')
  assert.equal(diagnosticoLogin.method, 'POST')
  assert.equal(diagnosticoLogin.route, '/api/v1/sesion')
  assert.equal(diagnosticoLogin.status, 200)
  assert.equal(diagnosticoLogin.category, 'autenticacion_aceptada')
  assert.ok(diagnosticoLogin.durationMs >= 0)
  assert.equal('verificationSucceeded' in diagnosticoLogin, false)
  assert.equal(diagnosticoConsulta.method, 'GET')
  assert.equal(diagnosticoConsulta.status, 200)
  assert.equal(diagnosticoConsulta.category, 'sesion_autenticada')
  assert.equal(diagnosticoConsulta.verificationSucceeded, true)
  assert.equal(diagnosticoFallo.status, 503)
  assert.equal(diagnosticoFallo.category, 'api_no_disponible')
  assert.equal(diagnosticoFallo.verificationSucceeded, false)
  assert.doesNotMatch(
    lineasDiagnostico.join('\n'),
    /persona@example\.test|contrasena-sintetica|csrf-sintetico|JSESSIONID=/,
  )

  const filtrado = await fetch(
    `${base}/api/v1/accesos/historial?pagina=2&lector=RFID3&resultado=DENEGADA`,
    { headers: { cookie: 'JSESSIONID=dueno' } },
  )
  assert.equal(filtrado.status, 200)
  assert.equal(solicitudes.at(-1).search, '?pagina=2&lector=RFID3&resultado=DENEGADA')
  assert.equal(solicitudes.at(-1).cookie, 'JSESSIONID=dueno')

  const antesExtra = solicitudes.length
  const queryExtra = await fetch(`${base}/api/v1/accesos/historial?pagina=1&uid=privado`)
  assert.equal(queryExtra.status, 404)
  assert.equal(
    solicitudes.length,
    antesExtra,
    'El BFF debe rechazar parámetros fuera de la allowlist',
  )

  const expirada = await fetch(`${base}/admin/accesos`, {
    headers: { cookie: 'JSESSIONID=vence' },
  })
  assert.equal(expirada.status, 200)
  const htmlExpirado = await expirada.text()
  const terminoEnPanel = new URL(expirada.url).pathname === '/panel'
  assert.ok(
    !/Persona Sintetica/.test(htmlExpirado),
    'La sesión expirada no debe devolver registros privados.',
  )
  assert.ok(
    terminoEnPanel || /acceso venció|historial/i.test(htmlExpirado),
    `La sesión expirada debe volver al panel o mostrar un estado seguro (ruta: ${new URL(expirada.url).pathname}).`,
  )
  console.log(
    'PASS: BFF limitado, cookie de propietario, SSR privado y sesión expirada sin registros privados.',
  )
} finally {
  web.kill('SIGTERM')
  if (web.exitCode === null) {
    await Promise.race([new Promise((resolve) => web.once('exit', resolve)), pause(3_000)])
  }
  await new Promise((resolve) => api.close(resolve))
}
