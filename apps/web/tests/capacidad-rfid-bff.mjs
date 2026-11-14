import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { setTimeout as pausa } from 'node:timers/promises'

const solicitudes = []
const datosDentro = {
  items: [{ movimientoId: '19', persona: { tipo: 'EMPLEADO', nombre: 'Persona sintética', codigo: 'E-0001' }, estadoTarjeta: 'CANCELADA', entradaEn: '2026-11-10T12:00:00Z', entradaEnLocal: '2026-11-10T06:00:00-06:00', salidaManual: null }],
  pagina: 2, tamano: 10, totalRegistros: 11, haySiguiente: false,
  zonaHoraria: 'America/Mexico_City', cursorEventos: 'epoch:2',
}
function responder(res, estado, datos, adicionales = {}) {
  res.writeHead(estado, { 'content-type': 'application/json', 'cache-control': 'no-store, private', ...adicionales })
  res.end(JSON.stringify(datos))
}
const api = createServer((req, res) => {
  const url = new URL(req.url ?? '/', 'http://127.0.0.1')
  const cookie = req.headers.cookie ?? ''
  const rol = cookie.includes('JSESSIONID=dueno') ? 'DUENO'
    : cookie.includes('JSESSIONID=operador') ? 'OPERADOR'
    : cookie.includes('JSESSIONID=sinclave') ? 'SIN_CLAVE'
    : cookie.includes('JSESSIONID=denegado') ? 'DENEGADO'
    : cookie.includes('JSESSIONID=expirado') ? 'EXPIRADO'
    : cookie.includes('JSESSIONID=fallo') ? 'FALLO'
    : 'ANONIMO'
  solicitudes.push({ metodo: req.method, ruta: url.pathname, busqueda: url.search, rol, csrf: req.headers['x-csrf-token'], clave: req.headers['idempotency-key'] })
  if (req.method === 'GET' && url.pathname === '/api/v1/sesion') {
    const autenticada = rol === 'DUENO' || rol === 'OPERADOR' || rol === 'EXPIRADO' || rol === 'FALLO'
    responder(res, 200, { autenticada, rol: autenticada ? (rol === 'OPERADOR' ? 'OPERADOR' : 'DUENO') : null, correo: autenticada ? `${rol.toLowerCase()}@ejemplo.test` : null })
    return
  }
  if (req.method === 'GET' && url.pathname === '/api/v1/panel') {
    if (rol !== 'DUENO' && rol !== 'FALLO') return responder(res, 401, {})
    return responder(res, 200, {
      propietario: { nombres: 'Propietario sintético', correo: 'propietario@example.test' },
      estacionamiento: {
        nombre: 'Estacionamiento sintético',
        tipo: 'MIXTO',
        horario: { modo: 'CONTINUO_24_7', zonaHoraria: 'America/Mexico_City', horaApertura: null, horaCierre: null },
      },
    })
  }
  const idOperacion = '01234567-89ab-4cde-8abc-0123456789ab'
  if (req.method === 'GET' && url.pathname === '/api/v1/accesos/salidas-manuales/capacidad') {
    if (rol !== 'DUENO' && rol !== 'OPERADOR') return responder(res, 401, {})
    return responder(res, 200, { disponible: true, vigenciaRestanteMs: 4000 })
  }
  if (req.method === 'POST' && url.pathname === '/api/v1/accesos/movimientos/19/salida-manual') {
    if (rol === 'SIN_CLAVE') return responder(res, 503, { codigo: 'SALIDA_MANUAL_NO_DISPONIBLE', mensaje: 'La salida manual no está disponible.' })
    if (rol !== 'DUENO' && rol !== 'OPERADOR') return responder(res, 401, {})
    if (req.headers['x-csrf-token'] !== 'csrf-sintetico') return responder(res, 403, {})
    if (req.headers['idempotency-key'] !== idOperacion) return responder(res, 400, {})
    return responder(res, 202, { operacionId: idOperacion, movimientoId: '19', estado: 'PENDIENTE' })
  }
  if (req.method === 'GET' && url.pathname === `/api/v1/accesos/salidas-manuales/${idOperacion}`) {
    if (rol !== 'DUENO' && rol !== 'OPERADOR') return responder(res, 401, {})
    return responder(res, 200, { operacionId: idOperacion, movimientoId: '19', estado: 'PENDIENTE' })
  }
  if (req.method !== 'GET') return responder(res, 404, {})
  if (url.pathname === '/api/v1/vision/cajones') return responder(res, 503, { error: 'Vision sin conexión' })
  if (url.pathname === '/api/v1/accesos/historial') {
    if (rol === 'ANONIMO') return responder(res, 401, {})
    return responder(res, 200, { items: [], pagina: 1, tamano: 10, totalRegistros: 0, haySiguiente: false, zonaHoraria: 'America/Mexico_City', cursorEventos: 'epoch:2' })
  }
  if (url.pathname === '/api/v1/accesos/capacidad' || url.pathname === '/api/v1/accesos/dentro') {
    if (rol === 'ANONIMO' || rol === 'EXPIRADO') return responder(res, 401, {})
    if (rol === 'DENEGADO') return responder(res, 403, {})
    if (rol === 'FALLO') return responder(res, 503, {})
    if (url.pathname.endsWith('/dentro')) return responder(res, 200, datosDentro)
    const datos = cookie.includes('JSESSIONID=dueno-cero')
      ? { capacidadTotal: 0, vehiculosDentro: 0, capacidadDisponible: 0 }
      : rol === 'DUENO'
      ? { capacidadTotal: 9, vehiculosDentro: 3, capacidadDisponible: 6 }
      : { capacidadTotal: 7, vehiculosDentro: 1, capacidadDisponible: 6 }
    return responder(res, 200, { ...datos, cursorEventos: 'epoch:2', uid: 'DATO_PRIVADO_SINTETICO' }, { 'set-cookie': 'renovacion=ficticia; Path=/; HttpOnly; SameSite=Strict' })
  }
  return responder(res, 404, {})
})
async function puertoLibre() {
  const servidor = createServer()
  await new Promise((resolve) => servidor.listen(0, '127.0.0.1', resolve))
  const puerto = servidor.address().port
  await new Promise((resolve) => servidor.close(resolve))
  return puerto
}
await new Promise((resolve) => api.listen(0, '127.0.0.1', resolve))
const puertoApi = api.address().port
const puertoWeb = await puertoLibre()
const salida = []
const web = spawn('node', ['.output/server/index.mjs'], {
  cwd: process.cwd(),
  env: { ...process.env, NUXT_API_INTERNAL_BASE: `http://127.0.0.1:${puertoApi}`, NITRO_HOST: '127.0.0.1', NITRO_PORT: String(puertoWeb), HOST: '127.0.0.1', PORT: String(puertoWeb) },
  stdio: ['ignore', 'pipe', 'pipe'],
})
web.stdout.on('data', (dato) => salida.push(String(dato)))
web.stderr.on('data', (dato) => salida.push(String(dato)))
const base = `http://127.0.0.1:${puertoWeb}`
let listo = false
for (let intento = 0; intento < 100; intento += 1) {
  if (web.exitCode !== null) break
  try {
    const respuesta = await fetch(`${base}/api/v1/accesos/capacidad`)
    if (respuesta.status < 500) { listo = true; break }
  } catch {}
  await pausa(100)
}
try {
  assert.ok(listo, `El servidor Web no inició: ${salida.join('').slice(-1500)}`)
  const antesAnonimo = solicitudes.filter((s) => s.ruta === '/api/v1/accesos/capacidad').length
  const anonimo = await fetch(`${base}/admin/vision`, { redirect: 'manual' })
  assert.equal(anonimo.status, 302)
  assert.equal(anonimo.headers.get('location'), '/panel')
  assert.equal(solicitudes.filter((s) => s.ruta === '/api/v1/accesos/capacidad').length, antesAnonimo)

  const [respuestaDueno, respuestaOperador] = await Promise.all([
    fetch(`${base}/admin/vision`, { headers: { cookie: 'JSESSIONID=dueno' } }),
    fetch(`${base}/operador/monitoreo`, { headers: { cookie: 'JSESSIONID=operador' } }),
  ])
  assert.equal(respuestaDueno.status, 200)
  assert.equal(respuestaOperador.status, 200)
  assert.match(respuestaDueno.headers.get('cache-control') ?? '', /no-store, private/)
  assert.match(respuestaDueno.headers.get('vary') ?? '', /cookie/i)
  assert.ok((respuestaDueno.headers.get('set-cookie') ?? '').includes('renovacion='))
  const htmlDueno = await respuestaDueno.text()
  const htmlOperador = await respuestaOperador.text()
  for (const html of [htmlDueno, htmlOperador]) {
    assert.match(html, /Capacidad del estacionamiento/)
    assert.match(html, /Vehículos registrados dentro/)
    assert.doesNotMatch(html, /DATO_PRIVADO_SINTETICO|"uid"/i)
  }
  assert.ok(/Capacidad total<\/dt>\s*<dd[^>]*>9<\/dd>/.test(htmlDueno), 'La página del dueño muestra su capacidad.')
  assert.ok(/Capacidad total<\/dt>\s*<dd[^>]*>7<\/dd>/.test(htmlOperador), 'La página del operador muestra su capacidad.')
  assert.ok(!/Capacidad total<\/dt>\s*<dd[^>]*>7<\/dd>/.test(htmlDueno), 'Las sesiones SSR no comparten datos.')
  assert.ok(!/Capacidad total<\/dt>\s*<dd[^>]*>9<\/dd>/.test(htmlOperador), 'Las sesiones SSR no comparten datos.')
  assert.ok(solicitudes.some((s) => s.ruta === '/api/v1/accesos/capacidad' && s.rol === 'DUENO'))
  assert.ok(solicitudes.some((s) => s.ruta === '/api/v1/accesos/capacidad' && s.rol === 'OPERADOR'))
  const antesInicio = solicitudes.length
  const inicio = await fetch(`${base}/admin`, { headers: { cookie: 'JSESSIONID=dueno' } })
  assert.equal(inicio.status, 200)
  const htmlInicio = await inicio.text()
  const solicitudesInicio = solicitudes.slice(antesInicio)
  assert.equal(solicitudesInicio.filter((s) => s.ruta === '/api/v1/panel').length, 1)
  assert.equal(solicitudesInicio.filter((s) => s.ruta === '/api/v1/accesos/capacidad').length, 1)
  assert.match(htmlInicio, /Estacionamiento:<\/strong>\s*Estacionamiento sintético/)
  assert.match(htmlInicio, /Horario:<\/strong>\s*Abierto las 24 horas/)
  assert.match(htmlInicio, /Modalidad:<\/strong>\s*Clientes y empleados/)
  assert.ok(/Libres estimados<\/dt>\s*<dd[^>]*>6<\/dd>/.test(htmlInicio))
  assert.ok(/Vehículos registrados dentro<\/dt>\s*<dd[^>]*>3<\/dd>/.test(htmlInicio))
  assert.ok(/Capacidad total<\/dt>\s*<dd[^>]*>9<\/dd>/.test(htmlInicio))
  assert.doesNotMatch(htmlInicio, /<dt>Propietario<\/dt>|<dt>Correo<\/dt>/)
  assert.doesNotMatch(htmlInicio, /titulo-ocupacion-vision|<h2[^>]*>Ocupación física<\/h2>/)

  const inicioCero = await fetch(`${base}/admin`, { headers: { cookie: 'JSESSIONID=dueno-cero' } })
  assert.equal(inicioCero.status, 200)
  const htmlCero = await inicioCero.text()
  assert.ok(/Libres estimados<\/dt>\s*<dd[^>]*>0<\/dd>/.test(htmlCero))
  assert.ok(/Vehículos registrados dentro<\/dt>\s*<dd[^>]*>0<\/dd>/.test(htmlCero))
  assert.ok(/Capacidad total<\/dt>\s*<dd[^>]*>0<\/dd>/.test(htmlCero))

  const inicioCaido = await fetch(`${base}/admin`, { headers: { cookie: 'JSESSIONID=fallo' } })
  assert.equal(inicioCaido.status, 200)
  const htmlInicioCaido = await inicioCaido.text()
  assert.ok(/Libres estimados<\/dt>\s*<dd[^>]*>—<\/dd>/.test(htmlInicioCaido))
  assert.ok(htmlInicioCaido.includes('No pudimos actualizar la información'))
  const capacidadCaida = await fetch(`${base}/admin/vision`, { headers: { cookie: 'JSESSIONID=fallo' } })
  const htmlFallo = await capacidadCaida.text()
  assert.equal(capacidadCaida.status, 200)
  assert.ok(/Capacidad total<\/dt>\s*<dd[^>]*>—<\/dd>/.test(htmlFallo), 'Un fallo de lectura no se muestra como capacidad cero.')
  assert.ok(htmlFallo.includes('No pudimos actualizar la información'))

  for (const rol of ['dueno', 'operador']) {
    const paginaAccesos = await fetch(`${base}/${rol === 'dueno' ? 'admin' : 'operador'}/accesos`, { headers: { cookie: `JSESSIONID=${rol}` } })
    assert.equal(paginaAccesos.status, 200)
    const html = await paginaAccesos.text()
    assert.match(html, /Historial/)
    assert.match(html, /Dentro del estacionamiento/)
    assert.doesNotMatch(html, /DATO_PRIVADO_SINTETICO/)
    const consulta = await fetch(`${base}/api/v1/accesos/dentro?pagina=2&busqueda=E-0001`, { headers: { cookie: `JSESSIONID=${rol}` } })
    assert.equal(consulta.status, 200)
    assert.deepEqual(await consulta.json(), datosDentro)
    assert.equal(solicitudes.at(-1).busqueda, '?pagina=2&busqueda=E-0001')
  }
  const denegado = await fetch(`${base}/api/v1/accesos/dentro?pagina=1`, { headers: { cookie: 'JSESSIONID=denegado' } })
  assert.equal(denegado.status, 403)
  const sinSesion = await fetch(`${base}/api/v1/accesos/capacidad`)
  assert.equal(sinSesion.status, 401)
  const antesExtra = solicitudes.length
  assert.equal((await fetch(`${base}/api/v1/accesos/dentro?pagina=1&uid=privado`)).status, 404)
  assert.equal((await fetch(`${base}/api/v1/accesos/dentro`, { method: 'POST' })).status, 404)
  assert.equal((await fetch(`${base}/api/v1/accesos/movimientos/0/salida-manual`, { method: 'POST' })).status, 404)
  assert.equal((await fetch(`${base}/api/v1/accesos/salidas-manuales/no-es-uuid`)).status, 404)
  assert.equal((await fetch(`${base}/api/v1/dispositivo/salidas-manuales/pendientes`)).status, 404)
  assert.equal(solicitudes.length, antesExtra, 'El BFF rechaza rutas y parámetros no autorizados.')
  const idOperacion = '01234567-89ab-4cde-8abc-0123456789ab'
  const noDisponible = await fetch(`${base}/api/v1/accesos/movimientos/19/salida-manual`, {
    method: 'POST', headers: { cookie: 'JSESSIONID=sinclave', 'idempotency-key': idOperacion, 'x-csrf-token': 'csrf-sintetico' },
  })
  assert.equal(noDisponible.status, 503)
  assert.equal((await noDisponible.json()).codigo, 'SALIDA_MANUAL_NO_DISPONIBLE', 'El BFF preserva el rechazo confirmado de la API.')
  for (const rol of ['dueno', 'operador']) {
    const sinCsrf = await fetch(`${base}/api/v1/accesos/movimientos/19/salida-manual`, {
      method: 'POST', headers: { cookie: `JSESSIONID=${rol}`, 'idempotency-key': idOperacion },
    })
    assert.equal(sinCsrf.status, 403)
    const crear = await fetch(`${base}/api/v1/accesos/movimientos/19/salida-manual`, {
      method: 'POST',
      headers: { cookie: `JSESSIONID=${rol}`, 'idempotency-key': idOperacion, 'x-csrf-token': 'csrf-sintetico' },
    })
    assert.equal(crear.status, 202)
    assert.equal(solicitudes.at(-1).clave, idOperacion)
    assert.equal(solicitudes.at(-1).csrf, 'csrf-sintetico')
    const estado = await fetch(`${base}/api/v1/accesos/salidas-manuales/${idOperacion}`, { headers: { cookie: `JSESSIONID=${rol}` } })
    assert.equal(estado.status, 200)
    assert.equal((await estado.json()).estado, 'PENDIENTE')
    const capacidadManual = await fetch(`${base}/api/v1/accesos/salidas-manuales/capacidad`, { headers: { cookie: `JSESSIONID=${rol}` } })
    assert.deepEqual(await capacidadManual.json(), { disponible: true, vigenciaRestanteMs: 4000 })
  }
  assert.equal((await fetch(`${base}/api/v1/accesos/salidas-manuales/${idOperacion}`)).status, 401)
  assert.equal((await fetch(`${base}/api/v1/accesos/salidas-manuales/capacidad`)).status, 401)
  const expirada = await fetch(`${base}/admin/vision`, { headers: { cookie: 'JSESSIONID=expirado' } })
  assert.ok(expirada.status === 200 || expirada.status === 302)
  assert.doesNotMatch(await expirada.text(), /DATO_PRIVADO_SINTETICO/)
  console.log('PASS: SSR privado concurrente, Vision caída, roles, cookies, BFF y rechazo de acceso.')
} finally {
  web.kill('SIGTERM')
  if (web.exitCode === null) await Promise.race([new Promise((resolve) => web.once('exit', resolve)), pausa(3_000)])
  await new Promise((resolve) => api.close(resolve))
}
