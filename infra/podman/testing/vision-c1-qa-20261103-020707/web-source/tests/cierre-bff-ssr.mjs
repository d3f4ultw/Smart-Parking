import assert from 'node:assert/strict'
import { once } from 'node:events'
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { setTimeout as pause } from 'node:timers/promises'

const maximoBytes = 1_048_576
let solicitudesPanel = 0
let solicitudesSesion = 0
let solicitudesPost = 0
let bytesPost = []
const solicitudesPorRuta = new Map()
const cookiesSesionUpstream = []

function escribirJson(respuesta, estado, datos, cookies = []) {
  respuesta.writeHead(estado, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    ...(cookies.length ? { 'set-cookie': cookies } : {}),
  })
  respuesta.end(JSON.stringify(datos))
}

const servidorApi = createServer(async (solicitud, respuesta) => {
  const ruta = new URL(solicitud.url ?? '/', 'http://127.0.0.1').pathname
  const cookie = solicitud.headers.cookie ?? ''
  solicitudesPorRuta.set(ruta, (solicitudesPorRuta.get(ruta) ?? 0) + 1)

  if (ruta === '/api/v1/csrf' && solicitud.method === 'GET') {
    escribirJson(respuesta, 200, { csrfToken: 'csrf-sintetico' })
    return
  }

  if (ruta === '/api/v1/sesion' && solicitud.method === 'GET') {
    solicitudesSesion += 1
    cookiesSesionUpstream.push(cookie)
    const cookies = cookie.includes('JSESSIONID=TEST_MULTI')
      ? [
          'JSESSIONID=valor-sintetico; Path=/api/v1; HttpOnly; SameSite=Strict',
          'CSRF-TOKEN=otro-valor; Expires=Wed, 21 Oct 2037 07:28:00 GMT; Path=/api/v1; SameSite=Strict',
        ]
      : []
    if (cookie.includes('JSESSIONID=SESSION_A') || cookie.includes('JSESSIONID=SESSION_B')) {
      const sufijo = cookie.includes('JSESSIONID=SESSION_A') ? 'A' : 'B'
      escribirJson(
        respuesta,
        200,
        {
          autenticada: true,
          correo: `dueno-${sufijo}@example.test`,
          rol: 'DUENO',
          cuentaId: `uuid-interno-${sufijo}`,
          revisionPropietario: 7,
          csrfToken: `csrf-privado-${sufijo}`,
          hashContrasena: `hash-privado-${sufijo}`,
        },
        cookies,
      )
      return
    }
    if (cookie.includes('JSESSIONID=SESSION_REVOKED')) {
      escribirJson(respuesta, 401, { codigo: 'SESION_NO_VIGENTE' }, [
        'JSESSIONID=; Max-Age=0; Path=/api/v1; HttpOnly; SameSite=Strict',
      ])
      return
    }
    if (cookie.includes('JSESSIONID=API_DOWN')) {
      escribirJson(respuesta, 503, { codigo: 'API_NO_DISPONIBLE' })
      return
    }
    escribirJson(respuesta, 200, { autenticada: false }, cookies)
    return
  }

  if (ruta === '/api/v1/panel' && solicitud.method === 'GET') {
    solicitudesPanel += 1
    if (cookie.includes('JSESSIONID=SESSION_REVOKED')) {
      escribirJson(respuesta, 401, { codigo: 'SESION_NO_VIGENTE' }, [
        'JSESSIONID=; Max-Age=0; Path=/api/v1; HttpOnly; SameSite=Strict',
      ])
      return
    }
    if (cookie.includes('JSESSIONID=SESSION_OPERATOR')) {
      escribirJson(respuesta, 403, { codigo: 'PERMISO_INSUFICIENTE' })
      return
    }
    if (cookie.includes('JSESSIONID=API_DOWN')) {
      escribirJson(respuesta, 503, { codigo: 'API_NO_DISPONIBLE' })
      return
    }
    const sufijo = cookie.includes('JSESSIONID=SESSION_A') ? 'A' : 'B'
    escribirJson(respuesta, 200, {
      propietario: {
        nombres: `Nombre-${sufijo}`,
        primerApellido: 'Sintetico',
        segundoApellido: null,
        correo: `dueno-${sufijo}@example.test`,
        cuentaId: `uuid-interno-${sufijo}`,
        hashContrasena: `hash-privado-${sufijo}`,
      },
      estacionamiento: {
        id: `estacionamiento-privado-${sufijo}`,
        nombre: `Estacionamiento-${sufijo}`,
        tipo: 'PUBLICO',
        horario: { modo: 'CONTINUO_24_7', zonaHoraria: 'America/Mexico_City' },
      },
      materialAdministrativo: `secreto-admin-${sufijo}`,
    })
    return
  }

  if (ruta === '/api/v1/vision/cajones' && solicitud.method === 'GET') {
    if (!cookie.includes('JSESSIONID=SESSION_A') && !cookie.includes('JSESSIONID=SESSION_B')) {
      escribirJson(respuesta, 401, { codigo: 'SESION_NO_VIGENTE' })
      return
    }
    const sufijo = cookie.includes('JSESSIONID=SESSION_A') ? 'A' : 'B'
    respuesta.writeHead(200, {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store, private',
      'x-eventos-cursor': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa:0',
    })
    respuesta.end(
      JSON.stringify([
        {
          cajonId: `00000000-0000-4000-8000-00000000000${sufijo === 'A' ? 1 : 2}`,
          etiqueta: `C-VISION-${sufijo}`,
          estado: 'NO_VERIFICABLE',
          ultimoEstadoConfirmado: null,
          observadoEn: null,
        },
      ]),
    )
    return
  }

  if (ruta === '/api/v1/sesion' && solicitud.method === 'POST') {
    const partes = []
    for await (const parte of solicitud) partes.push(parte)
    const cuerpo = Buffer.concat(partes)
    solicitudesPost += 1
    bytesPost.push(cuerpo.byteLength)
    if (solicitud.headers['x-csrf-token'] !== 'csrf-valido-sintetico') {
      escribirJson(respuesta, 403, {
        codigo: 'CSRF_RECHAZADO',
        error: 'La solicitud no es válida.',
      })
      return
    }
    escribirJson(respuesta, 401, {
      codigo: 'CREDENCIALES_NO_VALIDAS',
      error: 'Correo o contraseña no válidos.',
    })
    return
  }

  if (ruta === '/api/v1/sesion' && solicitud.method === 'DELETE') {
    escribirJson(respuesta, 200, { autenticada: false, csrfToken: 'csrf-renovado' }, [
      'JSESSIONID=; Max-Age=0; Path=/api/v1; HttpOnly; SameSite=Strict',
    ])
    return
  }

  respuesta.writeHead(404)
  respuesta.end()
})

await new Promise((resolve) => servidorApi.listen(0, '127.0.0.1', resolve))
const puertoApi = servidorApi.address().port
const servidorNitro = createServer()
await new Promise((resolve) => servidorNitro.listen(0, '127.0.0.1', resolve))
const puertoNitro = servidorNitro.address().port
await new Promise((resolve) => servidorNitro.close(resolve))

const salida = []
const proceso = spawn('node', ['.output/server/index.mjs'], {
  cwd: process.cwd(),
  env: {
    ...process.env,
    NUXT_API_INTERNAL_BASE: `http://127.0.0.1:${puertoApi}`,
    NITRO_HOST: '127.0.0.1',
    NITRO_PORT: String(puertoNitro),
    HOST: '127.0.0.1',
    PORT: String(puertoNitro),
  },
  stdio: ['ignore', 'pipe', 'pipe'],
})
proceso.stdout.on('data', (chunk) => salida.push(String(chunk)))
proceso.stderr.on('data', (chunk) => salida.push(String(chunk)))

const base = `http://127.0.0.1:${puertoNitro}`
let listo = false
for (let intento = 0; intento < 100; intento += 1) {
  if (proceso.exitCode !== null) break
  try {
    const respuesta = await fetch(`${base}/panel`)
    if (respuesta.status < 500) {
      listo = true
      break
    }
  } catch {}
  await pause(200)
}

try {
  assert.ok(listo, `El servidor de producción no inició: ${salida.join('').slice(-3000)}`)

  const cookiesDirectas = await fetch(`${base}/api/v1/sesion`, {
    headers: { cookie: 'JSESSIONID=TEST_MULTI; CLIENTSESSIONID=OTRA; TEST_IGNORADA=1' },
  })
  const setCookiesDirectas = cookiesDirectas.headers.getSetCookie()
  assert.equal(
    cookiesSesionUpstream.at(-1),
    'JSESSIONID=TEST_MULTI',
    'Solo se reenvía la sesión administrativa',
  )
  assert.equal(setCookiesDirectas.length, 2, 'El BFF debe conservar los dos Set-Cookie')
  assert.match(setCookiesDirectas[0], /^JSESSIONID=valor-sintetico;/)
  assert.match(setCookiesDirectas[0], /Path=\/;/)
  assert.match(setCookiesDirectas[0], /HttpOnly/)
  assert.match(setCookiesDirectas[1], /^CSRF-TOKEN=otro-valor;/)
  assert.match(setCookiesDirectas[1], /Expires=Wed, 21 Oct 2037 07:28:00 GMT/)
  assert.match(setCookiesDirectas[1], /Path=\/;/)

  const sesionesAntesSsrCookies = solicitudesSesion
  const htmlCookies = await fetch(`${base}/panel`, {
    headers: { cookie: 'JSESSIONID=TEST_MULTI' },
    redirect: 'manual',
  })
  assert.equal(htmlCookies.status, 200)
  const setCookiesSsr = htmlCookies.headers.getSetCookie()
  const cookiesSeguros = setCookiesSsr.map(
    (cookie) => `${cookie.slice(0, cookie.indexOf('='))}${cookie.slice(cookie.indexOf(';'))}`,
  )
  assert.equal(
    setCookiesSsr.length,
    2,
    `La respuesta SSR debe conservar exactamente las dos cabeceras; atributos=${JSON.stringify(cookiesSeguros)}, solicitudesSesionSsr=${solicitudesSesion - sesionesAntesSsrCookies}`,
  )
  assert.match(setCookiesSsr[0], /^JSESSIONID=valor-sintetico;/)
  assert.match(setCookiesSsr[1], /Expires=Wed, 21 Oct 2037 07:28:00 GMT/)
  assert.match(htmlCookies.headers.get('cache-control') ?? '', /no-store, private/)
  assert.match(htmlCookies.headers.get('vary') ?? '', /Cookie/i)
  const htmlPanelAnonimo = await htmlCookies.text()
  assert.match(htmlPanelAnonimo, /Iniciar sesión/)
  assert.match(htmlPanelAnonimo, /Acceso de cuenta/)
  assert.doesNotMatch(
    htmlPanelAnonimo,
    /SIN_CONFIGURAR|TRANSFERENCIA_PENDIENTE|configuración inicial|transferencia de propietario|recuperación de acceso/i,
  )

  const loginAnonimo = await fetch(`${base}/api/v1/sesion`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-csrf-token': 'csrf-valido-sintetico' },
    body: '{"correo":"inexistente@example.test","contrasena":"credencial-sintetica"}',
  })
  assert.equal(loginAnonimo.status, 401)
  assert.deepEqual(await loginAnonimo.json(), {
    codigo: 'CREDENCIALES_NO_VALIDAS',
    error: 'Correo o contraseña no válidos.',
  })
  const sesionAnonima = await fetch(`${base}/api/v1/sesion`)
  assert.equal(sesionAnonima.status, 200)
  assert.deepEqual(await sesionAnonima.json(), { autenticada: false })
  assert.equal(solicitudesPorRuta.get('/api/v1/configuracion/estado') ?? 0, 0)

  const csrfRechazado = await fetch(`${base}/api/v1/sesion`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-csrf-token': 'csrf-incorrecto' },
    body: '{}',
  })
  assert.equal(csrfRechazado.status, 403)
  assert.equal((await csrfRechazado.json()).codigo, 'CSRF_RECHAZADO')
  const sesionRevocada = await fetch(`${base}/api/v1/sesion`, {
    headers: { cookie: 'JSESSIONID=SESSION_REVOKED' },
  })
  assert.equal(sesionRevocada.status, 401)
  assert.equal((await sesionRevocada.json()).codigo, 'SESION_NO_VIGENTE')
  assert.match(sesionRevocada.headers.getSetCookie()[0], /Max-Age=0/)
  const permisoDenegado = await fetch(`${base}/api/v1/panel`, {
    headers: { cookie: 'JSESSIONID=SESSION_OPERATOR' },
  })
  assert.equal(permisoDenegado.status, 403)
  assert.equal((await permisoDenegado.json()).codigo, 'PERMISO_INSUFICIENTE')
  const apiNoDisponible = await fetch(`${base}/api/v1/sesion`, {
    headers: { cookie: 'JSESSIONID=API_DOWN' },
  })
  assert.equal(apiNoDisponible.status, 503)
  assert.equal((await apiNoDisponible.json()).codigo, 'API_NO_DISPONIBLE')

  const respuestaLogout = await fetch(`${base}/api/v1/sesion`, {
    method: 'DELETE',
    headers: { cookie: 'JSESSIONID=SESSION_A', 'x-csrf-token': 'csrf-valido-sintetico' },
  })
  assert.equal(respuestaLogout.status, 200)
  assert.deepEqual(await respuestaLogout.json(), {
    autenticada: false,
    csrfToken: 'csrf-renovado',
  })
  assert.match(respuestaLogout.headers.getSetCookie()[0], /Max-Age=0/)

  const [adminA, adminB, anonAdmin] = await Promise.all([
    fetch(`${base}/admin`, { headers: { cookie: 'JSESSIONID=SESSION_A' }, redirect: 'manual' }),
    fetch(`${base}/admin`, { headers: { cookie: 'JSESSIONID=SESSION_B' }, redirect: 'manual' }),
    fetch(`${base}/admin`, { redirect: 'manual' }),
  ])
  assert.equal(adminA.status, 200)
  assert.equal(adminB.status, 200)
  assert.equal(anonAdmin.status, 302)
  assert.equal(anonAdmin.headers.get('location'), '/panel')
  const [htmlA, htmlB, htmlAnon] = await Promise.all([
    adminA.text(),
    adminB.text(),
    anonAdmin.text(),
  ])
  assert.match(htmlA, /Nombre-A/)
  assert.match(htmlA, /dueno-A@example\.test/)
  assert.match(htmlA, /C-VISION-A/)
  assert.doesNotMatch(htmlA, /Nombre-B|dueno-B@example\.test|C-VISION-B/)
  assert.match(htmlB, /Nombre-B/)
  assert.match(htmlB, /dueno-B@example\.test/)
  assert.match(htmlB, /C-VISION-B/)
  assert.doesNotMatch(htmlB, /Nombre-A|dueno-A@example\.test|C-VISION-A/)
  assert.doesNotMatch(htmlAnon, /C-VISION-/)
  assert.doesNotMatch(
    htmlA + htmlB + htmlAnon,
    /uuid-interno|hash-privado|csrf-privado|secreto-admin|estacionamiento-privado/,
  )
  assert.match(htmlA, /Estacionamiento-A/)
  assert.match(htmlB, /Estacionamiento-B/)
  assert.match(adminA.headers.get('cache-control') ?? '', /no-store, private/)
  assert.match(adminA.headers.get('vary') ?? '', /Cookie/i)

  const authenticatedPanel = await fetch(`${base}/panel`, {
    headers: { cookie: 'JSESSIONID=SESSION_A' },
    redirect: 'manual',
  })
  assert.equal(authenticatedPanel.status, 302)
  assert.equal(authenticatedPanel.headers.get('location'), '/admin')

  const rutasPermitidas = [
    ['GET', '/api/v1/csrf'],
    ['GET', '/api/v1/sesion'],
    ['POST', '/api/v1/sesion'],
    ['DELETE', '/api/v1/sesion'],
    ['GET', '/api/v1/panel'],
  ]
  for (const [method, path] of rutasPermitidas) {
    const headers =
      method === 'POST'
        ? { 'content-type': 'application/json', 'x-csrf-token': 'csrf-valido-sintetico' }
        : {}
    const body = method === 'POST' ? '{}' : undefined
    const respuesta = await fetch(`${base}${path}`, { method, headers, body })
    assert.notEqual(respuesta.status, 404, `${method} ${path} debe estar permitido`)
  }

  const antesBloqueos = { sesiones: solicitudesSesion, paneles: solicitudesPanel }
  const bloqueada = await fetch(`${base}/api/v1/configuracion/estado`)
  const metodoBloqueado = await fetch(`${base}/api/v1/panel`, { method: 'POST' })
  assert.equal(bloqueada.status, 404)
  assert.equal(metodoBloqueado.status, 404)
  assert.deepEqual(
    { sesiones: solicitudesSesion, paneles: solicitudesPanel },
    antesBloqueos,
    'Las operaciones bloqueadas no deben alcanzar el upstream',
  )

  const enviarJsonExacto = async (texto) =>
    fetch(`${base}/api/v1/sesion`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-csrf-token': 'csrf-valido-sintetico' },
      body: texto,
    })
  const prefijo = '{"dato":"'
  const sufijo = '"}'
  const rellenoBytes = maximoBytes - Buffer.byteLength(prefijo + sufijo)
  const rellenoMultibyte = `${'é'.repeat(Math.floor(rellenoBytes / 2))}${rellenoBytes % 2 ? 'x' : ''}`
  const validoExacto = `${prefijo}${rellenoMultibyte}${sufijo}`
  assert.equal(Buffer.byteLength(validoExacto), maximoBytes)
  const antesPostExacto = solicitudesPost
  const respuestaExacta = await enviarJsonExacto(validoExacto)
  assert.equal(respuestaExacta.status, 401, 'El límite exacto llega a manejo normal del upstream')
  assert.equal(solicitudesPost, antesPostExacto + 1)
  assert.equal(bytesPost.at(-1), maximoBytes)

  const sobreLimiteDeclarado = `${prefijo}${'x'.repeat(maximoBytes - Buffer.byteLength(prefijo + sufijo) + 1)}${sufijo}`
  assert.equal(Buffer.byteLength(sobreLimiteDeclarado), maximoBytes + 1)
  const antesSobreLimite = solicitudesPost
  const respuestaSobreLimite = await enviarJsonExacto(sobreLimiteDeclarado)
  assert.equal(respuestaSobreLimite.status, 413)
  assert.equal(solicitudesPost, antesSobreLimite)

  const bytesSobreLimite = maximoBytes + 1
  const rellenoSobreLimite = bytesSobreLimite - Buffer.byteLength(prefijo + sufijo)
  const partesFlujo = [
    Buffer.from(prefijo),
    Buffer.alloc(rellenoSobreLimite, 0x78),
    Buffer.from(sufijo),
  ]
  let indiceParte = 0
  let posicionParte = 0
  const flujo = new ReadableStream({
    pull(controlador) {
      if (indiceParte === partesFlujo.length) {
        controlador.close()
        return
      }
      const parte = partesFlujo[indiceParte]
      const final = Math.min(posicionParte + 8192, parte.byteLength)
      controlador.enqueue(parte.subarray(posicionParte, final))
      posicionParte = final
      if (posicionParte === parte.byteLength) {
        indiceParte += 1
        posicionParte = 0
      }
    },
  })
  const respuestaFlujo = await fetch(`${base}/api/v1/sesion`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-csrf-token': 'csrf-valido-sintetico' },
    body: flujo,
    duplex: 'half',
  })
  assert.equal(respuestaFlujo.status, 413, 'El stream sin Content-Length se limita por bytes')
  assert.equal(solicitudesPost, antesSobreLimite)

  console.log(
    JSON.stringify({
      resultado: 'PASS',
      artifact: '.output/server/index.mjs',
      runtime: `node .output/server/index.mjs (${base})`,
      upstream: `http://127.0.0.1:${puertoApi}`,
      assertions: [
        'BFF y SSR conservaron dos Set-Cookie separados, incluidos Expires con coma y Path=/.',
        'SSR autenticado/anonimo aisló solicitudes concurrentes y no incluyó marcadores privados.',
        'Redirecciones SSR de /panel y /admin verificadas.',
        'Allowlist de cinco pares método/ruta y rechazo local sin llamada upstream.',
        'JSON multibyte exacto 1048576 B aceptado; JSON 1048577 B declarado y streamed rechazados con 413.',
        'Cuerpo multibyte medido en bytes UTF-8.',
      ],
    }),
  )
} finally {
  proceso.kill('SIGTERM')
  await Promise.race([once(proceso, 'exit'), pause(3000)])
  servidorApi.close()
}
