import assert from 'node:assert/strict'
import { once } from 'node:events'
import { lstat, readdir, rm, symlink } from 'node:fs/promises'
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { setTimeout as pause } from 'node:timers/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const solicitudes = []
let cancelacionesSse = 0
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

class FuenteEventosSimulada {
  listeners = new Map()
  closed = false

  constructor(url) {
    this.url = url
  }

  addEventListener(tipo, listener) {
    const listeners = this.listeners.get(tipo) ?? []
    listeners.push(listener)
    this.listeners.set(tipo, listeners)
  }

  emitir(tipo, evento) {
    for (const listener of this.listeners.get(tipo) ?? []) listener(evento)
  }

  close() {
    this.closed = true
  }
}

async function esperar(condicion, mensaje, limiteMs = 2_000) {
  for (let transcurrido = 0; transcurrido < limiteMs; transcurrido += 25) {
    if (condicion()) return
    await pause(25)
  }
  assert.fail(mensaje)
}

async function probarPluginHeartbeat(base) {
  const directorioPrueba = dirname(fileURLToPath(import.meta.url))
  const rutaVue = resolve(directorioPrueba, '../node_modules/vue')
  const rutaPaquetes = resolve(directorioPrueba, '../node_modules/.pnpm')
  let enlaceVueCreado = false
  try {
    await lstat(rutaVue)
  } catch (fallo) {
    if (fallo.code !== 'ENOENT') throw fallo
    const entradas = await readdir(rutaPaquetes)
    const paqueteVue = entradas.find((entrada) => entrada.startsWith('vue@'))
    assert.ok(paqueteVue, 'Vue debe estar instalado como dependencia transitiva de Nuxt UI')
    await symlink(resolve(rutaPaquetes, paqueteVue, 'node_modules/vue'), rutaVue, 'dir')
    enlaceVueCreado = true
  }

  const { effectScope, ref } = await import('vue')
  const scope = effectScope()
  const sesion = ref({ estado: 'autenticada', identidad: { rol: 'DUENO' } })
  const fuentes = []
  const llamadasActualizar = { total: 0 }
  const propiedadesAnteriores = new Map()
  const nombresGlobales = [
    'defineNuxtPlugin',
    'useSesion',
    'useCsrf',
    'useRoute',
    'navigateTo',
    'EventSource',
    'fetch',
  ]
  for (const nombre of nombresGlobales) propiedadesAnteriores.set(nombre, globalThis[nombre])
  const fetchOriginal = globalThis.fetch
  let dejarDeEscuchar = () => {}
  let estadoRespuestaAck

  globalThis.defineNuxtPlugin = (configurar) => configurar
  globalThis.useSesion = () => ({
    sesion,
    actualizar: async () => {
      llamadasActualizar.total += 1
    },
  })
  globalThis.useCsrf = () => ({ obtener: async () => 'csrf-heartbeat' })
  globalThis.useRoute = () => ({ path: '/admin/empleados' })
  globalThis.navigateTo = async () => {}
  globalThis.EventSource = class extends FuenteEventosSimulada {
    constructor(url) {
      super(url)
      fuentes.push(this)
    }
  }
  globalThis.fetch = async (entrada, opciones = {}) => {
    const url = new URL(String(entrada), base)
    const encabezados = new Headers(opciones.headers)
    encabezados.set('cookie', 'JSESSIONID=SESION_HEARTBEAT')
    const respuesta = await fetchOriginal(url, { ...opciones, headers: encabezados })
    if (url.pathname === '/api/v1/eventos/administracion/heartbeat')
      estadoRespuestaAck = respuesta.status
    return respuesta
  }

  try {
    const plugin = await import(
      `../app/plugins/eventos-administracion.client.ts?prueba=${Date.now()}`
    )
    let cliente
    scope.run(() => {
      cliente = plugin.default().provide.eventosAdministracion
    })
    let actualizaciones = 0
    dejarDeEscuchar = cliente.suscribir(() => {
      actualizaciones += 1
    }, 'epoch-1:7')
    assert.equal(fuentes.length, 1)
    assert.match(fuentes[0].url, /despues=epoch-1%3A7/)
    fuentes[0].emitir('empleado.directorio.actualizado', { lastEventId: 'epoch-1:8', data: '{}' })
    assert.equal(actualizaciones, 1)

    const cantidadGetDirectorio = solicitudes.filter(
      (solicitud) => solicitud.method === 'GET' && solicitud.path === '/api/v1/empleados',
    ).length
    const acksAntesInvalidos = solicitudes.filter((solicitud) =>
      solicitud.path.endsWith('/heartbeat'),
    ).length
    for (const datos of [
      { suscripcionId: '00000000-0000-3000-8000-000000000001', secuencia: 1 },
      { suscripcionId: '00000000-0000-4000-8000-000000000001', secuencia: 0 },
      {
        suscripcionId: '00000000-0000-4000-8000-000000000001',
        secuencia: Number.MAX_SAFE_INTEGER + 1,
      },
    ]) {
      fuentes[0].emitir('empleado.heartbeat', {
        lastEventId: 'cursor-que-no-debe-usarse',
        data: JSON.stringify(datos),
      })
      await pause(15)
    }
    assert.equal(
      solicitudes.filter((solicitud) => solicitud.path.endsWith('/heartbeat')).length,
      acksAntesInvalidos,
      'Debe ignorar UUID y secuencias inválidas',
    )

    const cantidadAcks = solicitudes.filter((solicitud) =>
      solicitud.path.endsWith('/heartbeat'),
    ).length
    fuentes[0].emitir('empleado.heartbeat', {
      lastEventId: 'cursor-que-no-debe-usarse',
      data: JSON.stringify({ suscripcionId: '00000000-0000-4000-8000-000000000001', secuencia: 1 }),
    })
    await esperar(
      () =>
        solicitudes.filter((solicitud) => solicitud.path.endsWith('/heartbeat')).length >
        cantidadAcks,
      'El heartbeat válido no produjo ACK por el BFF',
    )

    const solicitudAck = solicitudes.findLast(
      (solicitud) => solicitud.path === '/api/v1/eventos/administracion/heartbeat',
    )
    assert.equal(solicitudAck.method, 'POST')
    assert.equal(solicitudAck.headers.cookie, 'JSESSIONID=SESION_HEARTBEAT')
    assert.equal(solicitudAck.headers['x-csrf-token'], 'csrf-heartbeat')
    assert.deepEqual(JSON.parse(solicitudAck.body), {
      suscripcionId: '00000000-0000-4000-8000-000000000001',
      secuencia: 1,
    })
    assert.equal(estadoRespuestaAck, 204)
    assert.equal(actualizaciones, 1, 'El ACK no debe invocar la reacción del directorio')
    assert.equal(llamadasActualizar.total, 0, 'El ACK no debe validar ni refrescar la sesión')
    assert.equal(
      solicitudes.filter(
        (solicitud) => solicitud.method === 'GET' && solicitud.path === '/api/v1/empleados',
      ).length,
      cantidadGetDirectorio,
    )

    fuentes[0].onerror()
    await esperar(() => fuentes.length > 1, 'El EventSource simulado no reconectó', 2_500)
    assert.match(
      fuentes[1].url,
      /despues=epoch-1%3A8/,
      'El heartbeat no debe mover el cursor de negocio',
    )
    assert.doesNotMatch(fuentes[1].url, /cursor-que-no-debe-usarse/)
    dejarDeEscuchar()
    assert.equal(fuentes[1].closed, true)
    return [
      'plugin ACK con cookie/CSRF/body',
      'sin refresh del directorio',
      'cursor SSE de negocio sin cambios',
    ]
  } finally {
    dejarDeEscuchar()
    scope.stop()
    for (const nombre of nombresGlobales) {
      const anterior = propiedadesAnteriores.get(nombre)
      if (anterior === undefined) delete globalThis[nombre]
      else globalThis[nombre] = anterior
    }
    if (enlaceVueCreado) await rm(rutaVue)
  }
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

try {
  assert.ok(listo, `El servidor Web no inició: ${salida.join('').slice(-2500)}`)
  const directorio = await fetch(`${base}/api/v1/empleados?pagina=2`, {
    headers: { cookie: 'JSESSIONID=SESION_SINTETICA', accept: 'application/json' },
  })
  assert.equal(directorio.status, 200)
  assert.equal((await directorio.json()).cursorEventos, 'epoch-1:7')
  assert.match(directorio.headers.get('cache-control') ?? '', /no-store, private/)
  assert.match(directorio.headers.get('vary') ?? '', /Cookie/i)
  assert.equal(solicitudes.at(-1).search, '?pagina=2')
  assert.equal(solicitudes.at(-1).headers.cookie, 'JSESSIONID=SESION_SINTETICA')

  const elegibles = await fetch(
    `${base}/api/v1/empleados?pagina=1&busqueda=E-0042&soloElegiblesOperador=true`,
    { headers: { cookie: 'JSESSIONID=SESION_SINTETICA', accept: 'application/json' } },
  )
  assert.equal(elegibles.status, 200)
  assert.equal(solicitudes.at(-1).search, '?pagina=1&busqueda=E-0042&soloElegiblesOperador=true')
  assert.equal(solicitudes.at(-1).headers.cookie, 'JSESSIONID=SESION_SINTETICA')

  const registro = await fetch(`${base}/api/v1/empleados`, {
    method: 'POST',
    headers: {
      cookie: 'JSESSIONID=SESION_SINTETICA',
      'content-type': 'application/json',
      'x-csrf-token': 'csrf-sintetico',
      'idempotency-key': 'uuid-sintetico',
    },
    body: JSON.stringify({ nombres: 'Ana', primerApellido: 'Luz', segundoApellido: null }),
  })
  assert.equal(registro.status, 201)
  assert.deepEqual(await registro.json(), { id: 12, codigo: 'E-0012' })
  const solicitudRegistro = solicitudes.at(-1)
  assert.equal(solicitudRegistro.headers['x-csrf-token'], 'csrf-sintetico')
  assert.equal(solicitudRegistro.headers['idempotency-key'], 'uuid-sintetico')
  assert.deepEqual(JSON.parse(solicitudRegistro.body), {
    nombres: 'Ana',
    primerApellido: 'Luz',
    segundoApellido: null,
  })

  const registroConCorreo = await fetch(`${base}/api/v1/empleados`, {
    method: 'POST',
    headers: {
      cookie: 'JSESSIONID=SESION_SINTETICA',
      'content-type': 'application/json',
      'x-csrf-token': 'csrf-correo-alta',
      'idempotency-key': 'uuid-correo-alta',
    },
    body: JSON.stringify({
      nombres: 'Luz',
      primerApellido: 'Sol',
      segundoApellido: null,
      correo: 'luz@example.test',
    }),
  })
  assert.equal(registroConCorreo.status, 201)
  assert.deepEqual(JSON.parse(solicitudes.at(-1).body), {
    nombres: 'Luz',
    primerApellido: 'Sol',
    segundoApellido: null,
    correo: 'luz@example.test',
  })

  const cambio = await fetch(`${base}/api/v1/empleados/12/estado`, {
    method: 'PATCH',
    headers: {
      cookie: 'JSESSIONID=SESION_SINTETICA',
      'content-type': 'application/json',
      'x-csrf-token': 'csrf-sintetico',
      'if-match': '"1"',
    },
    body: JSON.stringify({ estado: 'INACTIVO' }),
  })
  assert.equal(cambio.status, 200)
  assert.equal(solicitudes.at(-1).headers['if-match'], '"1"')

  const idTexto = '9223372036854775807'
  const detalleExacto = await fetch(`${base}/api/v1/empleados/${idTexto}`, {
    headers: { cookie: 'JSESSIONID=SESION_SINTETICA', accept: 'application/json' },
  })
  assert.equal(detalleExacto.status, 200)
  assert.equal(detalleExacto.headers.get('etag'), '"9007199254740993"')
  assert.match(detalleExacto.headers.get('cache-control') ?? '', /no-store, private/)
  assert.equal((await detalleExacto.json()).idTexto, idTexto)
  assert.equal(solicitudes.at(-1).path, `/api/v1/empleados/${idTexto}`)
  assert.equal(solicitudes.at(-1).headers.cookie, 'JSESSIONID=SESION_SINTETICA')

  const correo = await fetch(`${base}/api/v1/empleados/${idTexto}/correo`, {
    method: 'PATCH',
    headers: {
      cookie: 'JSESSIONID=SESION_SINTETICA',
      'content-type': 'application/json',
      'x-csrf-token': 'csrf-correo',
      'if-match': '"9007199254740993"',
      'idempotency-key': 'clave-correo',
    },
    body: JSON.stringify({ correo: null }),
  })
  assert.equal(correo.status, 200)
  assert.equal(solicitudes.at(-1).headers['x-csrf-token'], 'csrf-correo')
  assert.equal(solicitudes.at(-1).headers['if-match'], '"9007199254740993"')
  assert.equal(solicitudes.at(-1).headers['idempotency-key'], 'clave-correo')
  assert.deepEqual(JSON.parse(solicitudes.at(-1).body), { correo: null })

  for (const sufijo of ['promocion', 'desactivacion']) {
    const respuesta = await fetch(`${base}/api/v1/empleados/${idTexto}/operador/${sufijo}`, {
      method: 'POST',
      headers: {
        cookie: 'JSESSIONID=SESION_SINTETICA',
        'content-type': 'application/json',
        'x-csrf-token': `csrf-${sufijo}`,
        'if-match': '"9007199254740993"',
        'idempotency-key': `clave-${sufijo}`,
      },
      body: '{}',
    })
    assert.equal(respuesta.status, 200)
    assert.equal(solicitudes.at(-1).headers['if-match'], '"9007199254740993"')
    assert.equal(solicitudes.at(-1).headers['idempotency-key'], `clave-${sufijo}`)
    assert.equal(solicitudes.at(-1).headers['x-csrf-token'], `csrf-${sufijo}`)
    assert.equal(solicitudes.at(-1).headers.cookie, 'JSESSIONID=SESION_SINTETICA')
  }

  const promocionConCorreo = await fetch(`${base}/api/v1/empleados/${idTexto}/operador/promocion`, {
    method: 'POST',
    headers: {
      cookie: 'JSESSIONID=SESION_SINTETICA',
      'content-type': 'application/json',
      'x-csrf-token': 'csrf-promocion-correo',
      'if-match': '"9007199254740993"',
      'idempotency-key': 'clave-promocion-correo',
    },
    body: JSON.stringify({ correo: 'nuevo@example.test' }),
  })
  assert.equal(promocionConCorreo.status, 200)
  assert.equal(solicitudes.at(-1).headers['if-match'], '"9007199254740993"')
  assert.equal(solicitudes.at(-1).headers['idempotency-key'], 'clave-promocion-correo')
  assert.equal(solicitudes.at(-1).headers['x-csrf-token'], 'csrf-promocion-correo')
  assert.deepEqual(JSON.parse(solicitudes.at(-1).body), { correo: 'nuevo@example.test' })

  const vinculacion = await fetch(`${base}/api/v1/empleados/${idTexto}/operador/vinculacion`, {
    method: 'POST',
    headers: {
      cookie: 'JSESSIONID=SESION_SINTETICA',
      'content-type': 'application/json',
      'x-csrf-token': 'csrf-vinculo',
      'if-match': '"9007199254740993"',
      'idempotency-key': 'clave-vinculo',
    },
    body: JSON.stringify({
      operadorId: '00000000-0000-4000-8000-000000000009',
      revisionOperador: '9223372036854775806',
      copiarCorreoOperador: true,
    }),
  })
  assert.equal(vinculacion.status, 200)
  assert.equal(solicitudes.at(-1).headers['if-match'], '"9007199254740993"')
  assert.equal(solicitudes.at(-1).headers['idempotency-key'], 'clave-vinculo')
  assert.equal(solicitudes.at(-1).headers['x-csrf-token'], 'csrf-vinculo')
  assert.equal(solicitudes.at(-1).headers.cookie, 'JSESSIONID=SESION_SINTETICA')
  assert.deepEqual(JSON.parse(solicitudes.at(-1).body), {
    operadorId: '00000000-0000-4000-8000-000000000009',
    revisionOperador: '9223372036854775806',
    copiarCorreoOperador: true,
  })

  const vinculacionSinCopia = await fetch(
    `${base}/api/v1/empleados/${idTexto}/operador/vinculacion`,
    {
      method: 'POST',
      headers: {
        cookie: 'JSESSIONID=SESION_SINTETICA',
        'content-type': 'application/json',
        'x-csrf-token': 'csrf-vinculo',
        'if-match': '"9007199254740993"',
        'idempotency-key': 'clave-vinculo-sin-copia',
      },
      body: JSON.stringify({
        operadorId: '00000000-0000-4000-8000-000000000009',
        revisionOperador: '9223372036854775806',
        copiarCorreoOperador: false,
      }),
    },
  )
  assert.equal(vinculacionSinCopia.status, 200)
  assert.equal(JSON.parse(solicitudes.at(-1).body).copiarCorreoOperador, false)

  const abortar = new AbortController()
  const flujo = await fetch(`${base}/api/v1/eventos/administracion?despues=epoch-1%3A7`, {
    headers: {
      cookie: 'JSESSIONID=SESION_SINTETICA',
      accept: 'text/event-stream',
      'last-event-id': 'epoch-1:6',
    },
    signal: abortar.signal,
  })
  assert.equal(flujo.status, 200)
  assert.match(flujo.headers.get('content-type') ?? '', /text\/event-stream/)
  assert.equal(flujo.headers.get('x-accel-buffering'), 'no')
  const lector = flujo.body.getReader()
  const primerEvento = await lector.read()
  assert.match(new TextDecoder().decode(primerEvento.value), /empleado\.directorio\.actualizado/)
  const eventoEsperado = new TextEncoder().encode(
    'id: epoch-1:8\nevent: empleado.directorio.actualizado\ndata: {}\n\n',
  )
  assert.deepEqual(
    primerEvento.value.slice(0, eventoEsperado.length),
    eventoEsperado,
    'El BFF debe conservar los bytes SSE upstream sin alterar',
  )
  const solicitudSse = solicitudes.at(-1)
  assert.equal(solicitudSse.search, '?despues=epoch-1%3A7')
  assert.equal(solicitudSse.headers['last-event-id'], 'epoch-1:6')
  abortar.abort()
  await lector.cancel().catch(() => {})
  for (let intento = 0; intento < 30 && cancelacionesSse === 0; intento += 1) await pause(50)
  assert.ok(cancelacionesSse > 0, 'El cierre del cliente debe cancelar el flujo upstream')

  const flujoInterrumpido = await fetch(`${base}/api/v1/eventos/administracion?despues=fallo`, {
    headers: { cookie: 'JSESSIONID=SESION_SINTETICA', accept: 'text/event-stream' },
  })
  assert.equal(flujoInterrumpido.status, 200)
  const lectorInterrumpido = flujoInterrumpido.body.getReader()
  const eventoInicial = await lectorInterrumpido.read()
  assert.match(new TextDecoder().decode(eventoInicial.value), /empleado\.directorio\.actualizado/)
  const resultadoInterrupcion = await Promise.race([
    lectorInterrumpido.read().then(
      (resultado) => ({ resultado }),
      (fallo) => ({ fallo }),
    ),
    pause(2_000).then(() => ({ vencio: true })),
  ])
  assert.notEqual(
    resultadoInterrupcion.vencio,
    true,
    'El BFF no debe dejar abierto el stream tras el fallo upstream',
  )
  assert.ok(
    resultadoInterrupcion.fallo instanceof Error,
    'El error upstream debe llegar al cliente como error de transporte',
  )

  const cantidadAntes = solicitudes.length
  const heartbeat = await fetch(`${base}/api/v1/eventos/administracion/heartbeat`, {
    method: 'POST',
    headers: {
      cookie: 'JSESSIONID=SESION_DIRECTA',
      'content-type': 'application/json',
      'x-csrf-token': 'csrf-directo',
    },
    body: JSON.stringify({ suscripcionId: '00000000-0000-4000-8000-000000000002', secuencia: 2 }),
  })
  assert.equal(heartbeat.status, 204)
  assert.equal(await heartbeat.text(), '')
  const solicitudHeartbeat = solicitudes.at(-1)
  assert.equal(solicitudHeartbeat.headers.cookie, 'JSESSIONID=SESION_DIRECTA')
  assert.equal(solicitudHeartbeat.headers['x-csrf-token'], 'csrf-directo')
  assert.deepEqual(JSON.parse(solicitudHeartbeat.body), {
    suscripcionId: '00000000-0000-4000-8000-000000000002',
    secuencia: 2,
  })
  const verificacionesPlugin = await probarPluginHeartbeat(base)

  const antesRutaNoPermitida = solicitudes.length
  assert.equal(
    (
      await fetch(`${base}/api/v1/eventos/administracion/heartbeat?extra=1`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: '{}',
      })
    ).status,
    404,
  )
  assert.equal(
    solicitudes.length,
    antesRutaNoPermitida,
    'La allowlist debe rechazar query extra en heartbeat',
  )

  const solicitudesAntes = solicitudes.length
  assert.equal((await fetch(`${base}/api/v1/empleados/9223372036854775808`)).status, 404)
  assert.equal((await fetch(`${base}/api/v1/empleados/12/correo-extra`)).status, 404)
  assert.equal((await fetch(`${base}/api/v1/empleados?pagina=1&admin=true`)).status, 404)
  assert.equal(
    solicitudes.length,
    solicitudesAntes,
    'La allowlist debe rechazar localmente rutas y parámetros extra',
  )
  assert.ok(solicitudes.length > cantidadAntes)
  console.log(
    JSON.stringify({
      resultado: 'PASS',
      verificaciones: [
        'allowlist',
        'cookie/CSRF/idempotencia/If-Match',
        'heartbeat 204/cookie/CSRF/body',
        ...verificacionesPlugin,
        'cursor SSE',
        'streaming',
        'cancelación upstream',
      ],
    }),
  )
} finally {
  web.kill('SIGTERM')
  await Promise.race([once(web, 'exit'), pause(3_000)])
  await new Promise((resolve) => api.close(resolve))
}
