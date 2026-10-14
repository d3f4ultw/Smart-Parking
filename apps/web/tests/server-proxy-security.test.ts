import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { spawn, type ChildProcess } from 'node:child_process'
import { cp, mkdir, mkdtemp, rm, symlink } from 'node:fs/promises'
import { createServer, type IncomingMessage, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'
import { dirname, join, relative, sep } from 'node:path'
import { tmpdir } from 'node:os'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

type UpstreamPlan = {
  status: number
  body?: string
  headers?: Record<string, string | string[]>
  stream?: boolean
  firstChunkDelayMs?: number
  onClose?: () => void
}

type CapturedRequest = {
  method: string
  path: string
  query: string
  cookie?: string
  accept?: string
  lastEventId?: string
  contentType?: string
  role?: string
  roleAlias?: string
  userId?: string
  authorization?: string
  origin?: string
  body: string
}

type Harness = {
  origin: string
  requests: CapturedRequest[]
  logs: () => string
  queueResponse: (plan: UpstreamPlan) => void
  cancelResponse: (plan: UpstreamPlan) => void
  clearRequests: () => void
  close: () => Promise<void>
}

const WEB_ROOT = resolveWebRoot()
const NUXT_CLI = join(WEB_ROOT, 'node_modules', 'nuxt', 'bin', 'nuxt.mjs')
const MAX_CAPTURED_LOG_CHARS = 96_000

function resolveWebRoot() {
  return join(dirname(fileURLToPath(import.meta.url)), '..')
}

function jsonPlan(
  status: number,
  payload: unknown,
  headers: Record<string, string | string[]> = {},
): UpstreamPlan {
  return {
    status,
    body: status === 204 ? '' : JSON.stringify(payload),
    headers: {
      'content-type': 'application/json; charset=utf-8',
      ...headers,
    },
  }
}

function headerValue(value: string | string[] | undefined) {
  return Array.isArray(value) ? value.join(', ') : value
}

function matchesFlatJson(actual: string, expected: Record<string, unknown>) {
  try {
    const parsed: unknown = JSON.parse(actual)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return false
    }

    const actualRecord = parsed as Record<string, unknown>
    const expectedKeys = Object.keys(expected)
    return Object.keys(actualRecord).length === expectedKeys.length
      && expectedKeys.every((key) => actualRecord[key] === expected[key])
  } catch {
    return false
  }
}

function listen(server: Server) {
  return new Promise<number>((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      server.removeListener('error', reject)
      resolve((server.address() as AddressInfo).port)
    })
  })
}

async function freePort() {
  const server = createServer()
  const port = await listen(server)
  await new Promise<void>((resolve, reject) => {
    server.close((error) => error ? reject(error) : resolve())
  })
  return port
}

function captureRequest(request: IncomingMessage, body: string): CapturedRequest {
  const url = new URL(request.url ?? '/', 'http://upstream.invalid')
  return {
    method: request.method ?? 'GET',
    path: url.pathname,
    query: url.search,
    cookie: headerValue(request.headers.cookie),
    accept: headerValue(request.headers.accept),
    lastEventId: headerValue(request.headers['last-event-id']),
    contentType: headerValue(request.headers['content-type']),
    role: headerValue(request.headers['x-user-role']),
    roleAlias: headerValue(request.headers['x-role']),
    userId: headerValue(request.headers['x-user-id']),
    authorization: headerValue(request.headers.authorization),
    origin: headerValue(request.headers.origin),
    body,
  }
}

async function startHarness(): Promise<Harness> {
  const requests: CapturedRequest[] = []
  const plans: UpstreamPlan[] = []
  const tempRoot = await mkdtemp(join(tmpdir(), 'sp031-nitro-'))
  const isolatedWebRoot = join(tempRoot, 'web')
  let upstream: Server | undefined
  let nuxt: ChildProcess | undefined
  let capturedLogs = ''

  async function stopNuxt() {
    if (!nuxt || (nuxt.exitCode !== null && nuxt.signalCode !== null)) {
      return
    }

    if (nuxt.exitCode === null && nuxt.signalCode === null) {
      try {
        if (process.platform !== 'win32' && nuxt.pid) {
          process.kill(-nuxt.pid, 'SIGTERM')
        } else {
          nuxt.kill('SIGTERM')
        }
      } catch {
        // The process may have exited between the state check and signal.
      }
    }

    await new Promise<void>((resolve) => {
      if (!nuxt || nuxt.exitCode !== null || nuxt.signalCode !== null) {
        resolve()
        return
      }

      const timeout = setTimeout(() => {
        if (nuxt && nuxt.exitCode === null && nuxt.signalCode === null) {
          try {
            if (process.platform !== 'win32' && nuxt.pid) {
              process.kill(-nuxt.pid, 'SIGKILL')
            } else {
              nuxt.kill('SIGKILL')
            }
          } catch {
            // Cleanup remains best-effort if the process already exited.
          }
        }
        resolve()
      }, 5000)

      nuxt.once('exit', () => {
        clearTimeout(timeout)
        resolve()
      })
    })
  }

  async function closeUpstream() {
    if (!upstream?.listening) {
      return
    }

    await new Promise<void>((resolve) => {
      upstream?.close(() => resolve())
      upstream?.closeAllConnections()
    })
  }

  try {
    await mkdir(isolatedWebRoot, { recursive: true })
    await cp(WEB_ROOT, isolatedWebRoot, {
      recursive: true,
      filter: (source) => {
        const path = relative(WEB_ROOT, source)
        if (!path) {
          return true
        }

        const parts = path.split(sep)
        return !parts.some((part) => [
          '.git',
          '.nuxt',
          '.output',
          'node_modules',
        ].includes(part))
          && !parts.some((part) => /^\.env(?:\.|$)/i.test(part))
      },
    })
    await symlink(
      join(WEB_ROOT, 'node_modules'),
      join(isolatedWebRoot, 'node_modules'),
      process.platform === 'win32' ? 'junction' : 'dir',
    )

    upstream = createServer((request, response) => {
      const chunks: Buffer[] = []
      request.on('data', (chunk: Buffer | string) => {
        chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk))
      })
      request.on('end', () => {
        const body = Buffer.concat(chunks).toString('utf8')
        requests.push(captureRequest(request, body))
        const plan = plans.shift() ?? jsonPlan(200, { estado: 'fixture' })
        response.writeHead(plan.status, plan.headers ?? {})
        if (plan.stream) {
          response.flushHeaders()
          if (plan.onClose) {
            response.once('close', plan.onClose)
          }
          if ((plan.firstChunkDelayMs ?? 0) > 0) {
            const temporizador = setTimeout(() => {
              if (!response.destroyed) {
                response.write(plan.body ?? '')
              }
            }, plan.firstChunkDelayMs)
            response.once('close', () => clearTimeout(temporizador))
            return
          }
          response.write(plan.body ?? '')
          return
        }
        response.end(plan.status === 204 ? '' : plan.body ?? '')
      })
    })

    const upstreamPort = await listen(upstream)
    const originPort = await freePort()
    const upstreamUrl = `http://127.0.0.1:${upstreamPort}`
    const origin = `http://127.0.0.1:${originPort}`
    let spawnFailed = false

    nuxt = spawn(
      process.execPath,
      [
        NUXT_CLI,
        'dev',
        '--host',
        '127.0.0.1',
        '--port',
        String(originPort),
        '--no-fork',
      ],
      {
        cwd: isolatedWebRoot,
        detached: process.platform !== 'win32',
        env: {
          ...process.env,
          NUXT_API_INTERNAL_BASE_URL: upstreamUrl,
          NUXT_PUBLIC_MANAGEMENT_ORIGIN: origin,
          NUXT_TELEMETRY_DISABLED: '1',
          NO_COLOR: '1',
          NODE_ENV: 'development',
        },
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    )

    const captureLog = (chunk: Buffer | string) => {
      capturedLogs = `${capturedLogs}${chunk.toString()}`.slice(-MAX_CAPTURED_LOG_CHARS)
    }
    nuxt.stdout?.on('data', captureLog)
    nuxt.stderr?.on('data', captureLog)
    nuxt.on('error', () => {
      spawnFailed = true
    })

    let ready = false
    for (let attempt = 0; attempt < 240; attempt += 1) {
      if (spawnFailed || nuxt.exitCode !== null) {
        throw new Error('Nitro test server exited before readiness')
      }

      const readinessPlan = jsonPlan(200, { estado: 'ready' })
      plans.push(readinessPlan)
      try {
        const response = await fetch(`${origin}/api/autenticacion/me`, {
          signal: AbortSignal.timeout(1500),
        })
        await response.text()
        ready = response.status === 200
          && requests.some((item) => item.path === '/api/autenticacion/me')
      } catch {
        ready = false
      }

      plans.length = 0
      requests.length = 0
      if (ready) {
        break
      }
      await delay(250)
    }

    if (!ready) {
      throw new Error('Nitro test server did not become ready')
    }

    return {
      origin,
      requests,
      logs: () => capturedLogs,
      queueResponse: (plan) => plans.push(plan),
      cancelResponse: (plan) => {
        const planIndex = plans.lastIndexOf(plan)
        if (planIndex >= 0) {
          plans.splice(planIndex, 1)
        }
      },
      clearRequests: () => {
        requests.length = 0
        plans.length = 0
      },
      close: async () => {
        await stopNuxt()
        await closeUpstream()
        await rm(tempRoot, { recursive: true, force: true })
        requests.length = 0
        plans.length = 0
      },
    }
  } catch {
    await stopNuxt()
    await closeUpstream()
    await rm(tempRoot, { recursive: true, force: true })
    throw new Error('Unable to initialize isolated Nuxt/Nitro test server')
  }
}

test('Nitro BFF security boundary preserves upstream contracts', {
  timeout: 180_000,
}, async (suite) => {
  const marker = () => `sp031-${randomUUID()}`
  const sensitiveMarkers = [
    marker(), // password
    marker(), // replacement credential
    marker(), // activation token
    marker(), // challenge token
    marker(), // session token
    marker(), // hash
    marker(), // internal diagnostic
  ]
  const password = sensitiveMarkers[0]
  const activationToken = sensitiveMarkers[2]
  const challengeToken = sensitiveMarkers[3]
  const sessionToken = sensitiveMarkers[4]
  const harness = await startHarness()

  async function send(
    path: string,
    options: RequestInit = {},
    plan?: UpstreamPlan,
  ) {
    const requestIndex = harness.requests.length
    if (plan) {
      harness.queueResponse(plan)
    }

    const response = await fetch(`${harness.origin}${path}`, options)
    const body = await response.text()
    const upstreamRequest = harness.requests[requestIndex]
    if (!upstreamRequest && plan) {
      harness.cancelResponse(plan)
    }

    return { response, body, upstreamRequest }
  }

  function assertForwarded(
    result: Awaited<ReturnType<typeof send>>,
    method: string,
    path: string,
  ) {
    assert.ok(result.upstreamRequest, 'Nitro handler reached the fake upstream')
    assert.ok(result.upstreamRequest.method === method, 'HTTP method was preserved')
    assert.ok(
      `${result.upstreamRequest.path}${result.upstreamRequest.query}` === path,
      'Upstream path and query match the route contract',
    )
  }

  function assertNoSensitiveBody(body: string) {
    for (const value of sensitiveMarkers) {
      assert.ok(!body.includes(value), 'Sensitive marker leaked in BFF response body')
    }
  }

  try {
    await suite.test('cookie matrix and OWNER session semantics', async () => {
      const states = [
        { name: 'anonymous', value: undefined, status: 401 },
        { name: 'OWNER', value: marker(), status: 200 },
        { name: 'OPERADOR', value: marker(), status: 401 },
        { name: 'random', value: marker(), status: 401 },
        { name: 'revoked', value: marker(), status: 401 },
        { name: 'expired', value: marker(), status: 401 },
      ]

      for (const state of states) {
        const cookie = state.value
          ? `smart_parking_session=${state.value}`
          : undefined
        const result = await send(
          '/api/admin/operadores',
          {
            headers: cookie ? { cookie } : {},
          },
          jsonPlan(state.status, state.status === 401
            ? { detail: 'No autenticado' }
            : { estado: 'lista_fixture' }),
        )

        assert.ok(result.response.status === state.status, 'BFF preserved authentication status')
        assertForwarded(result, 'GET', '/api/admin/operadores')
        assert.ok(
          result.upstreamRequest.cookie === cookie,
          'Cookie header was forwarded unchanged',
        )
        assert.ok(
          result.response.headers.get('cache-control') === 'no-store',
          'OWNER response remains no-store',
        )
        assertNoSensitiveBody(result.body)
      }

      const forged = await send(
        '/api/admin/operadores',
        {
          headers: {
            cookie: `unrelated=${marker()}`,
            'x-user-role': 'OWNER',
            'x-role': 'OWNER',
            'x-user-id': '1',
          },
        },
        jsonPlan(401, { detail: 'No autenticado' }),
      )
      assert.ok(forged.response.status === 401, 'Forged role headers did not authorize')
      assertForwarded(forged, 'GET', '/api/admin/operadores')
      assert.ok(
        forged.upstreamRequest.cookie?.startsWith('unrelated=') === true,
        'Unrelated cookie remains unrelated to session state',
      )
      assert.ok(
        forged.upstreamRequest.userId === undefined
          || forged.upstreamRequest.userId === '1',
        'BFF did not replace the client user ID header',
      )
      assertNoSensitiveBody(forged.body)
      harness.clearRequests()
    })

    await suite.test('Cajón listing proxy forwards only its session cookie', async () => {
      const sessionToken = marker()
      const unrelatedCookie = marker()
      const deviceToken = marker()
      sensitiveMarkers.push(sessionToken, unrelatedCookie, deviceToken)
      const cookie = `smart_parking_session=${sessionToken}; unrelated=${unrelatedCookie}`
      const payload = { cajones: [], cursor_eventos: '17' }
      const response = await send(
        '/api/admin/cajones',
        {
          headers: {
            cookie,
            'x-user-role': 'OWNER',
            'x-role': 'OWNER',
            'x-user-id': '41',
            authorization: `Bearer ${deviceToken}`,
          },
        },
        jsonPlan(200, payload),
      )

      assert.equal(response.response.status, 200, 'Listing status is preserved')
      assertForwarded(response, 'GET', '/api/cajones')
      assert.equal(
        response.upstreamRequest?.cookie,
        `smart_parking_session=${sessionToken}`,
        'Only the staff session cookie reaches FastAPI',
      )
      assert.equal(response.upstreamRequest?.role, undefined, 'Client role is not forwarded')
      assert.equal(response.upstreamRequest?.roleAlias, undefined, 'Role alias is not forwarded')
      assert.equal(response.upstreamRequest?.userId, undefined, 'Client user ID is not forwarded')
      assert.equal(response.upstreamRequest?.authorization, undefined, 'Device bearer is not forwarded')
      assert.deepEqual(JSON.parse(response.body), payload, 'Valid listing body is preserved')
      assert.equal(response.response.headers.get('cache-control'), 'no-store')
      assertNoSensitiveBody(response.body)

      harness.clearRequests()
      const forgedRole = await send(
        '/api/admin/cajones',
        {
          headers: {
            'x-user-role': 'OWNER',
            'x-role': 'OWNER',
            'x-user-id': '1',
            authorization: `Bearer ${deviceToken}`,
          },
        },
        jsonPlan(401, { detail: 'No autenticado' }),
      )
      assert.equal(forgedRole.response.status, 401, 'Authentication failure is preserved')
      assertForwarded(forgedRole, 'GET', '/api/cajones')
      assert.equal(forgedRole.upstreamRequest?.cookie, undefined)
      assert.equal(forgedRole.upstreamRequest?.role, undefined)
      assert.equal(forgedRole.upstreamRequest?.roleAlias, undefined)
      assert.equal(forgedRole.upstreamRequest?.userId, undefined)
      assert.equal(forgedRole.upstreamRequest?.authorization, undefined)
      assert.equal(forgedRole.response.headers.get('cache-control'), 'no-store')

      const failure = await send(
        '/api/admin/cajones',
        { headers: { cookie: `smart_parking_session=${sessionToken}` } },
        jsonPlan(503, { detail: 'Servicio no disponible' }),
      )
      assert.equal(failure.response.status, 503, 'Upstream failure status is preserved')
      assertForwarded(failure, 'GET', '/api/cajones')
      assert.deepEqual(JSON.parse(failure.body), { detail: 'Servicio no disponible' })
      assert.equal(failure.response.headers.get('cache-control'), 'no-store')
      assertNoSensitiveBody(failure.body)
      harness.clearRequests()
    })

    await suite.test('OWNER modality configuration BFF filters cookies and request fields', async () => {
      const sessionToken = marker()
      const unrelatedCookie = marker()
      const deviceToken = marker()
      const hiddenField = marker()
      sensitiveMarkers.push(sessionToken, unrelatedCookie, deviceToken, hiddenField)
      const cookie = 'smart_parking_session=' + sessionToken
        + '; unrelated=' + unrelatedCookie
      const payload = {
        modalidad: 'PRIVADO',
        revision: 4,
        acceso_suspendido: false,
      }
      const lectura = await send(
        '/api/admin/configuracion/modalidad',
        {
          headers: {
            cookie,
            'x-user-role': 'OWNER',
            'x-role': 'OWNER',
            'x-user-id': '41',
            authorization: 'Bearer ' + deviceToken,
          },
        },
        jsonPlan(200, payload),
      )

      assert.equal(lectura.response.status, 200)
      assertForwarded(lectura, 'GET', '/api/admin/configuracion/modalidad')
      assert.equal(
        lectura.upstreamRequest?.cookie,
        'smart_parking_session=' + sessionToken,
        'Only the session cookie reaches FastAPI',
      )
      assert.equal(lectura.upstreamRequest?.role, undefined)
      assert.equal(lectura.upstreamRequest?.roleAlias, undefined)
      assert.equal(lectura.upstreamRequest?.userId, undefined)
      assert.equal(lectura.upstreamRequest?.authorization, undefined)
      assert.equal(lectura.response.headers.get('cache-control'), 'no-store')
      assert.deepEqual(JSON.parse(lectura.body), payload)

      harness.clearRequests()
      const solicitud = { modalidad: 'MIXTO', revision_esperada: 4 }
      const body = JSON.stringify(solicitud)
      const escritura = await send(
        '/api/admin/configuracion/modalidad',
        {
          method: 'PUT',
          headers: {
            cookie,
            'content-type': 'application/json',
            'x-user-role': 'OWNER',
            'x-role': 'OWNER',
            'x-user-id': '41',
            authorization: 'Bearer ' + deviceToken,
          },
          body,
        },
        jsonPlan(200, {
          modalidad: 'MIXTO',
          revision: 5,
          acceso_suspendido: false,
        }),
      )
      assert.equal(escritura.response.status, 200)
      assertForwarded(escritura, 'PUT', '/api/admin/configuracion/modalidad')
      assert.equal(
        escritura.upstreamRequest?.cookie,
        'smart_parking_session=' + sessionToken,
      )
      assert.equal(escritura.upstreamRequest?.body, body)
      assert.equal(escritura.upstreamRequest?.contentType?.split(';')[0], 'application/json')
      assert.equal(escritura.upstreamRequest?.role, undefined)
      assert.equal(escritura.upstreamRequest?.roleAlias, undefined)
      assert.equal(escritura.upstreamRequest?.userId, undefined)
      assert.equal(escritura.upstreamRequest?.authorization, undefined)
      assert.equal(escritura.response.headers.get('cache-control'), 'no-store')
      assert.deepEqual(JSON.parse(escritura.body), {
        modalidad: 'MIXTO',
        revision: 5,
        acceso_suspendido: false,
      })

      harness.clearRequests()
      const solicitudesAntesDeInvalidas = harness.requests.length
      for (const opciones of [
        {
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            modalidad: 'MIXTO',
            revision_esperada: 4,
            configuracion_privada: hiddenField,
          }),
        },
        {
          headers: { 'content-type': 'text/plain' },
          body: JSON.stringify(solicitud),
        },
      ]) {
        const rechazo = await send(
          '/api/admin/configuracion/modalidad',
          { method: 'PUT', ...opciones },
        )
        assert.ok(rechazo.response.status >= 400)
        assert.equal(rechazo.upstreamRequest, undefined)
        assert.equal(rechazo.response.headers.get('cache-control'), 'no-store')
        assertNoSensitiveBody(rechazo.body)
      }
      assert.equal(harness.requests.length, solicitudesAntesDeInvalidas)

      harness.clearRequests()
      const solicitudAcceso = {
        acceso_suspendido: true,
        revision_esperada: 5,
      }
      const cuerpoAcceso = JSON.stringify(solicitudAcceso)
      const cambioAcceso = await send(
        '/api/admin/configuracion/acceso',
        {
          method: 'PUT',
          headers: {
            cookie,
            'content-type': 'application/json',
            'x-user-role': 'OWNER',
            'x-role': 'OWNER',
            'x-user-id': '41',
            authorization: 'Bearer ' + deviceToken,
          },
          body: cuerpoAcceso,
        },
        jsonPlan(200, {
          modalidad: 'MIXTO',
          revision: 6,
          acceso_suspendido: true,
        }),
      )
      assert.equal(cambioAcceso.response.status, 200)
      assertForwarded(cambioAcceso, 'PUT', '/api/admin/configuracion/acceso')
      assert.equal(
        cambioAcceso.upstreamRequest?.cookie,
        'smart_parking_session=' + sessionToken,
      )
      assert.equal(cambioAcceso.upstreamRequest?.body, cuerpoAcceso)
      assert.equal(cambioAcceso.upstreamRequest?.contentType?.split(';')[0], 'application/json')
      assert.equal(cambioAcceso.upstreamRequest?.role, undefined)
      assert.equal(cambioAcceso.upstreamRequest?.roleAlias, undefined)
      assert.equal(cambioAcceso.upstreamRequest?.userId, undefined)
      assert.equal(cambioAcceso.upstreamRequest?.authorization, undefined)
      assert.equal(cambioAcceso.response.headers.get('cache-control'), 'no-store')
      assert.deepEqual(JSON.parse(cambioAcceso.body), {
        modalidad: 'MIXTO',
        revision: 6,
        acceso_suspendido: true,
      })

      harness.clearRequests()
      for (const opciones of [
        {
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            ...solicitudAcceso,
            configuracion_privada: hiddenField,
          }),
        },
        {
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ acceso_suspendido: 'true', revision_esperada: 5 }),
        },
        {
          headers: { 'content-type': 'text/plain' },
          body: cuerpoAcceso,
        },
      ]) {
        const rechazo = await send(
          '/api/admin/configuracion/acceso',
          { method: 'PUT', ...opciones },
        )
        assert.ok(rechazo.response.status >= 400)
        assert.equal(rechazo.upstreamRequest, undefined)
        assert.equal(rechazo.response.headers.get('cache-control'), 'no-store')
        assertNoSensitiveBody(rechazo.body)
      }
      assert.equal(harness.requests.length, 0)
      harness.clearRequests()
    })

    await suite.test('la ruta de configuración OWNER se renderiza con estado SSR persistido', async () => {
      const sessionToken = marker()
      const cookie = 'smart_parking_session=' + sessionToken
      const indiceSolicitudes = harness.requests.length
      harness.queueResponse(jsonPlan(200, {
        autenticado: true,
        usuario: {
          nombre: 'Propietario',
          apellido_paterno: 'Prueba',
          apellido_materno: null,
          correo: 'owner@example.invalid',
          rol: 'OWNER',
        },
      }))
      harness.queueResponse(jsonPlan(200, {
        modalidad: 'PUBLICO',
        revision: 2,
        acceso_suspendido: false,
      }))

      const respuesta = await fetch(
        harness.origin + '/admin/configuracion',
        { headers: { cookie }, signal: AbortSignal.timeout(20_000) },
      )
      const html = await respuesta.text()
      const solicitudes = harness.requests.slice(indiceSolicitudes)

      assert.equal(respuesta.status, 200)
      assert.match(html, /Configuración del estacionamiento/)
      assert.match(html, /Modalidad actual:[\s\S]*Público/)
      assert.match(html, /Acceso habilitado/)
      assert.match(html, /Fuera de servicio/)
      assert.match(html, /Guardar cambios/)
      assert.match(html, /href="\/admin\/configuracion"/)
      assert.equal(solicitudes.length, 2)
      assert.equal(solicitudes[0]?.path, '/api/autenticacion/me')
      assert.equal(solicitudes[1]?.path, '/api/admin/configuracion/modalidad')
      assert.equal(solicitudes[0]?.cookie, cookie)
      assert.equal(solicitudes[1]?.cookie, cookie)
      assert.equal(solicitudes[1]?.method, 'GET')
      assert.ok(!html.includes(sessionToken), 'Session token is absent from rendered HTML')
      harness.clearRequests()

      harness.queueResponse(jsonPlan(200, {
        autenticado: true,
        usuario: {
          nombre: 'Propietario',
          apellido_paterno: 'Prueba',
          apellido_materno: null,
          correo: 'owner@example.invalid',
          rol: 'OWNER',
        },
      }))
      harness.queueResponse(jsonPlan(200, {
        modalidad: 'MIXTO',
        revision: 3,
        acceso_suspendido: true,
      }))

      const paginaSuspendida = await fetch(
        harness.origin + '/admin/configuracion',
        { headers: { cookie }, signal: AbortSignal.timeout(20_000) },
      )
      const htmlSuspendido = await paginaSuspendida.text()
      assert.equal(paginaSuspendida.status, 200)
      assert.match(htmlSuspendido, /Acceso suspendido/)
      assert.match(htmlSuspendido, /Reanudar acceso/)
      assert.match(htmlSuspendido, /class="modality-options" disabled/)
      assert.match(htmlSuspendido, /Modalidad actual:[\s\S]*Mixto/)
      assert.ok(!htmlSuspendido.includes(sessionToken))
      harness.clearRequests()
    })

    await suite.test('Cajón operational PATCH allow-lists ID, body, and session cookie', async () => {
      const sessionCookie = marker()
      const unrelatedCookie = marker()
      const deviceToken = marker()
      const hiddenField = marker()
      sensitiveMarkers.push(sessionCookie, unrelatedCookie, deviceToken, hiddenField)
      const patchBody = JSON.stringify({
        estado: 'MANTENIMIENTO',
        motivo: 'Inspección',
      })
      const payload = {
        id: 41,
        cambio_aplicado: true,
        estado_operativo: 'MANTENIMIENTO',
      }
      const actualizado = await send(
        '/api/admin/cajones/41/estado-operativo',
        {
          method: 'PATCH',
          headers: {
            cookie: `smart_parking_session=${sessionCookie}; unrelated=${unrelatedCookie}`,
            'content-type': 'application/json',
            'x-user-role': 'OWNER',
            'x-role': 'OWNER',
            'x-user-id': '41',
            authorization: `Bearer ${deviceToken}`,
          },
          body: patchBody,
        },
        jsonPlan(200, payload),
      )

      assert.equal(actualizado.response.status, 200, 'PATCH status is preserved')
      assertForwarded(actualizado, 'PATCH', '/api/cajones/41/estado-operativo')
      assert.equal(actualizado.upstreamRequest?.cookie, `smart_parking_session=${sessionCookie}`)
      assert.equal(actualizado.upstreamRequest?.contentType?.split(';')[0], 'application/json')
      assert.equal(actualizado.upstreamRequest?.body, patchBody, 'Allowed JSON fields are forwarded')
      assert.equal(actualizado.upstreamRequest?.role, undefined)
      assert.equal(actualizado.upstreamRequest?.roleAlias, undefined)
      assert.equal(actualizado.upstreamRequest?.userId, undefined)
      assert.equal(actualizado.upstreamRequest?.authorization, undefined)
      assert.equal(actualizado.response.headers.get('cache-control'), 'no-store')
      assert.deepEqual(JSON.parse(actualizado.body), payload)
      assertNoSensitiveBody(actualizado.body)

      harness.clearRequests()
      const disponible = await send(
        '/api/admin/cajones/41/estado-operativo',
        {
          method: 'PATCH',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ estado: 'DISPONIBLE' }),
        },
        jsonPlan(200, { id: 41, cambio_aplicado: false }),
      )
      assert.equal(disponible.response.status, 200)
      assertForwarded(disponible, 'PATCH', '/api/cajones/41/estado-operativo')
      assert.deepEqual(JSON.parse(disponible.upstreamRequest?.body ?? '{}'), {
        estado: 'DISPONIBLE',
      }, 'DISPONIBLE never forwards an empty motivo')
      assert.equal(disponible.upstreamRequest?.cookie, undefined)
      assert.equal(disponible.response.headers.get('cache-control'), 'no-store')

      harness.clearRequests()
      const sinMotivo = await send(
        '/api/admin/cajones/41/estado-operativo',
        {
          method: 'PATCH',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ estado: 'MANTENIMIENTO', motivo: '   ' }),
        },
        jsonPlan(200, { id: 41, cambio_aplicado: true }),
      )
      assert.equal(sinMotivo.response.status, 200)
      assert.deepEqual(JSON.parse(sinMotivo.upstreamRequest?.body ?? '{}'), {
        estado: 'MANTENIMIENTO',
      }, 'Blank optional reason is omitted before forwarding')

      harness.clearRequests()
      const fallaUpstream = await send(
        '/api/admin/cajones/41/estado-operativo',
        {
          method: 'PATCH',
          headers: {
            cookie: `smart_parking_session=${sessionCookie}`,
            'content-type': 'application/json',
          },
          body: JSON.stringify({ estado: 'MANTENIMIENTO', motivo: 'Ajuste' }),
        },
        jsonPlan(422, { detail: 'Solicitud invalida' }),
      )
      assert.equal(fallaUpstream.response.status, 422, 'FastAPI validation status is preserved')
      assertForwarded(fallaUpstream, 'PATCH', '/api/cajones/41/estado-operativo')
      assert.equal(fallaUpstream.response.headers.get('cache-control'), 'no-store')
      assertNoSensitiveBody(fallaUpstream.body)

      harness.clearRequests()
      const antesInvalidas = harness.requests.length
      for (const [path, body] of [
        ['/api/admin/cajones/0/estado-operativo', { estado: 'DISPONIBLE' }],
        ['/api/admin/cajones/9007199254740992/estado-operativo', { estado: 'DISPONIBLE' }],
        ['/api/admin/cajones/41/estado-operativo', { estado: 'MANTENIMIENTO', motivo: 'x'.repeat(251) }],
        ['/api/admin/cajones/41/estado-operativo', { estado: 'DISPONIBLE', motivo: 'No aplica' }],
        ['/api/admin/cajones/41/estado-operativo', { estado: 'DISPONIBLE', device_secret: hiddenField }],
      ] as const) {
        const rechazo = await send(path, {
          method: 'PATCH',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(body),
        })
        assert.ok(rechazo.response.status >= 400, 'Malformed ID or payload is rejected locally')
        assert.equal(rechazo.upstreamRequest, undefined, 'Invalid input never reaches FastAPI')
        assertNoSensitiveBody(rechazo.body)
      }
      assert.equal(harness.requests.length, antesInvalidas)

      const sinCookie = await send(
        '/api/admin/cajones/41/estado-operativo',
        {
          method: 'PATCH',
          headers: {
            'content-type': 'application/json',
            'x-user-role': 'OWNER',
            'x-role': 'OWNER',
            'x-user-id': '1',
            authorization: `Bearer ${deviceToken}`,
          },
          body: JSON.stringify({ estado: 'DISPONIBLE' }),
        },
        jsonPlan(401, { detail: 'No autenticado' }),
      )
      assert.equal(sinCookie.response.status, 401)
      assertForwarded(sinCookie, 'PATCH', '/api/cajones/41/estado-operativo')
      assert.equal(sinCookie.upstreamRequest?.cookie, undefined)
      assert.equal(sinCookie.upstreamRequest?.authorization, undefined)
      assert.equal(sinCookie.upstreamRequest?.role, undefined)
      assert.equal(sinCookie.upstreamRequest?.roleAlias, undefined)
      assert.equal(sinCookie.upstreamRequest?.userId, undefined)
      assertNoSensitiveBody(sinCookie.body)
      harness.clearRequests()
    })

    await suite.test('login, logout, and session headers/cookies', async () => {
      const loginBody = JSON.stringify({
        correo: 'sp031-login@example.invalid',
        contrasena: password,
      })
      const sessionCookie = `smart_parking_session=${sessionToken}`
      const login = await send(
        '/api/login',
        {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            cookie: `unrelated=${marker()}`,
          },
          body: loginBody,
        },
        jsonPlan(200, { estado: 'credenciales_validas' }, {
          'cache-control': 'no-store',
          'set-cookie': `${sessionCookie}; Path=/; HttpOnly; Secure; SameSite=Lax`,
        }),
      )
      assert.ok(login.response.status === 200, 'Login status was preserved')
      assertForwarded(login, 'POST', '/api/autenticacion/login')
      assert.ok(login.upstreamRequest.contentType?.startsWith('application/json'), 'Login Content-Type was forwarded')
      assert.ok(login.upstreamRequest.body === loginBody, 'Login body was forwarded unchanged')
      assert.ok(login.response.headers.get('cache-control') === 'no-store', 'Login preserved backend no-store')
      const loginCookies = login.response.headers.getSetCookie()
      assert.ok(loginCookies.length === 1, 'Login Set-Cookie count was preserved')
      assert.ok(
        loginCookies[0].includes(sessionToken)
          && /httponly/i.test(loginCookies[0])
          && /secure/i.test(loginCookies[0])
          && /samesite=lax/i.test(loginCookies[0])
          && /path=\//i.test(loginCookies[0]),
        'Login cookie attributes were preserved',
      )
      assertNoSensitiveBody(login.body)

      const me = await send(
        '/api/autenticacion/me',
        { headers: { cookie: sessionCookie } },
        jsonPlan(200, { autenticado: true, usuario: { rol: 'OWNER' } }),
      )
      assert.ok(me.response.status === 200, 'Current-session status was preserved')
      assertForwarded(me, 'GET', '/api/autenticacion/me')
      assert.ok(me.upstreamRequest.cookie === sessionCookie, 'Session cookie reached /me unchanged')
      assert.ok(me.response.headers.get('cache-control') === 'no-store', '/me remains no-store')
      assertNoSensitiveBody(me.body)

      const logout = await send(
        '/api/autenticacion/logout',
        { method: 'POST', headers: { cookie: sessionCookie } },
        jsonPlan(200, { estado: 'sesion_cerrada' }, {
          'cache-control': 'no-store',
          'set-cookie': 'smart_parking_session=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax',
        }),
      )
      assert.ok(logout.response.status === 200, 'Logout status was preserved')
      assertForwarded(logout, 'POST', '/api/autenticacion/logout')
      assert.ok(logout.upstreamRequest.cookie === sessionCookie, 'Logout cookie reached FastAPI')
      assert.ok(logout.response.headers.get('cache-control') === 'no-store', 'Logout remains no-store')
      const logoutCookies = logout.response.headers.getSetCookie()
      assert.ok(logoutCookies.length === 1, 'Logout cookie deletion was preserved')
      assert.ok(
        /max-age=0/i.test(logoutCookies[0])
          && /httponly/i.test(logoutCookies[0])
          && /secure/i.test(logoutCookies[0])
          && /samesite=lax/i.test(logoutCookies[0])
          && /path=\//i.test(logoutCookies[0]),
        'Logout cookie deletion attributes were preserved',
      )
      assertNoSensitiveBody(logout.body)
      harness.clearRequests()
    })

    await suite.test('operator create, query, path, and mutation forwarding', async () => {
      const createBody = JSON.stringify({
        nombre: 'Prueba',
        apellido_paterno: 'Sintetica',
        apellido_materno: '',
        correo: `sp031-${randomUUID()}@example.invalid`,
        rol: 'OWNER',
        user_id: 1,
      })
      const create = await send(
        '/api/admin/operadores',
        {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            cookie: `smart_parking_session=${marker()}`,
          },
          body: createBody,
        },
        jsonPlan(422, { detail: 'Solicitud invalida' }),
      )
      assert.ok(create.response.status === 422, 'Unexpected identity fields remain rejected')
      assertForwarded(create, 'POST', '/api/admin/operadores')
      assert.ok(create.upstreamRequest.contentType?.startsWith('application/json'), 'Create Content-Type was preserved')
      assert.ok(matchesFlatJson(create.upstreamRequest.body, JSON.parse(createBody)), 'Create body fields were forwarded without injection or removal')
      assert.ok(create.response.headers.get('cache-control') === 'no-store', 'Create response remains no-store')
      assertNoSensitiveBody(create.body)

      const acceptedCreateBody = JSON.stringify({
        nombre: 'Prueba',
        apellido_paterno: 'Sintetica',
        apellido_materno: '',
        correo: `sp031-${randomUUID()}@example.invalid`,
      })
      const acceptedCreate = await send(
        '/api/admin/operadores',
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: acceptedCreateBody,
        },
        jsonPlan(201, { estado: 'operador_creado' }),
      )
      assert.ok(acceptedCreate.response.status === 201, 'Create status remains 201')
      assertForwarded(acceptedCreate, 'POST', '/api/admin/operadores')
      assert.ok(matchesFlatJson(acceptedCreate.upstreamRequest.body, JSON.parse(acceptedCreateBody)), 'Valid create body reached FastAPI without additions')
      assertNoSensitiveBody(acceptedCreate.body)

      const page = await send(
        `/api/admin/operadores?pagina=2&rol=OWNER&user_id=${marker()}`,
        { headers: { cookie: `smart_parking_session=${marker()}` } },
        jsonPlan(200, { pagina: 2, operadores: [] }),
      )
      assert.ok(page.response.status === 200, 'Paginated list was successful')
      assertForwarded(page, 'GET', '/api/admin/operadores?pagina=2')
      assert.ok(page.upstreamRequest.query === '?pagina=2', 'Only intended pagination query was forwarded')

      const searchCookie = 'smart_parking_session=' + marker()
      const searchedPage = await send(
        '/api/admin/operadores?pagina=2&buscar=Coincidencia+Global&rol=OWNER&user_id=' + marker(),
        { headers: { cookie: searchCookie } },
        jsonPlan(200, { pagina: 2, operadores: [], total: 0, total_paginas: 0 }),
      )
      assert.ok(searchedPage.response.status === 200, 'Search list status was preserved')
      assertForwarded(
        searchedPage,
        'GET',
        '/api/admin/operadores?pagina=2&buscar=Coincidencia+Global',
      )
      assert.ok(
        searchedPage.upstreamRequest.query === '?pagina=2&buscar=Coincidencia+Global',
        'Only page and the allowlisted search value were forwarded',
      )
      assert.ok(
        searchedPage.upstreamRequest.cookie === searchCookie,
        'The OWNER session cookie remains forwarded',
      )
      assert.ok(
        searchedPage.response.headers.get('cache-control') === 'no-store',
        'Search results remain no-store',
      )

      const invalidPage = await send(
        '/api/admin/operadores?pagina=invalid',
        {},
        jsonPlan(422, { detail: 'Solicitud invalida' }),
      )
      assert.ok(invalidPage.response.status === 422, 'Invalid page status was preserved')
      assertForwarded(invalidPage, 'GET', '/api/admin/operadores?pagina=invalid')

      const malformedBody = '{"correo":'
      const malformed = await send(
        '/api/login',
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: malformedBody,
        },
        jsonPlan(422, { detail: 'Solicitud invalida' }),
      )
      assert.ok(malformed.response.status === 422, 'Malformed JSON keeps backend validation status')
      assertForwarded(malformed, 'POST', '/api/autenticacion/login')
      assert.ok(malformed.upstreamRequest.body === malformedBody, 'Malformed body was not rewritten')

      const detail = await send(
        '/api/admin/operadores/41?id=999&rol=OWNER',
        { headers: { cookie: `smart_parking_session=${marker()}` } },
        jsonPlan(200, { id: 41, estado_cuenta: 'acceso_habilitado' }),
      )
      assert.ok(detail.response.status === 200, 'Detail status was preserved')
      assertForwarded(detail, 'GET', '/api/admin/operadores/41')
      assert.ok(detail.upstreamRequest.path.endsWith('/41'), 'Path ID was not replaced by query data')

      const nonexistent = await send(
        '/api/admin/operadores/999999',
        {},
        jsonPlan(404, { detail: 'Operador no encontrado' }),
      )
      assert.ok(nonexistent.response.status === 404, 'Nonexistent target stayed not found')
      assertForwarded(nonexistent, 'GET', '/api/admin/operadores/999999')

      const nonnumeric = await send(
        '/api/admin/operadores/no-numerico',
        {},
        jsonPlan(422, { detail: 'Solicitud invalida' }),
      )
      assert.ok(nonnumeric.response.status === 422, 'Nonnumeric ID stayed rejected by backend')
      assertForwarded(nonnumeric, 'GET', '/api/admin/operadores/no-numerico')

      for (const action of [
        'desactivar',
        'reactivar',
        'reenviar-invitacion',
        'regenerar-contrasena',
      ]) {
        const path = `/api/admin/operadores/41/${action}`
        const result = await send(
          path,
          {
            method: 'POST',
            headers: { cookie: `smart_parking_session=${marker()}` },
          },
          jsonPlan(200, { estado: 'accion_fixture' }),
        )
        assert.ok(result.response.status === 200, 'Operator action status was preserved')
        assertForwarded(result, 'POST', path)
        assert.ok(result.response.headers.get('cache-control') === 'no-store', 'Operator mutation remains no-store')
      }

      const resendBefore = harness.requests.length
      const invalidResend = await send(
        '/api/admin/operadores/no-numerico/reenviar-invitacion',
        { method: 'POST' },
      )
      assert.ok(invalidResend.response.status === 404, 'Invalid resend ID is locally not found')
      assert.ok(harness.requests.length === resendBefore, 'Invalid resend ID did not reach FastAPI')

      const encoded = await send(
        '/api/admin/operadores/41%2F88',
        {},
        jsonPlan(422, { detail: 'Solicitud invalida' }),
      )
      assert.ok(encoded.response.status !== 200, 'Encoded path separator cannot select a successful target')
      if (encoded.upstreamRequest) {
        assert.ok(
          encoded.upstreamRequest.path.startsWith('/api/admin/operadores/'),
          'Encoded path edge stayed inside the operator route',
        )
      }
      harness.clearRequests()
    })

    await suite.test('unified SSE forwards its private stream and cancels upstream', async () => {
      const cookie = `smart_parking_session=${marker()}`
      const payload = 'id: 41\nevent: operador.actualizado\ndata: {"recurso_tipo":"operador","recurso_id":9}\n\n'
      let cerrarUpstream!: () => void
      const upstreamCerrado = new Promise<void>((resolve) => {
        cerrarUpstream = resolve
      })
      harness.queueResponse({
        status: 200,
        body: payload,
        stream: true,
        headers: {
          'content-type': 'text/event-stream; charset=utf-8',
          'cache-control': 'no-store',
        },
        onClose: cerrarUpstream,
      })

      const respuesta = await fetch(
        `${harness.origin}/api/eventos?cursor_eventos=41&rol=OWNER&topic=operador.creado`,
        { headers: { cookie }, signal: AbortSignal.timeout(10_000) },
      )
      assert.equal(respuesta.status, 200, 'SSE response status is preserved')
      assert.equal(respuesta.headers.get('content-type')?.startsWith('text/event-stream'), true)
      assert.equal(respuesta.headers.get('cache-control'), 'no-store')
      assert.equal(respuesta.headers.get('x-accel-buffering'), 'no')
      const lector = respuesta.body?.getReader()
      assert.ok(lector, 'SSE body is readable as a stream')
      let cuerpoSse = ''
      while (!cuerpoSse.includes('operador.actualizado')) {
        const bloque = await lector.read()
        assert.equal(bloque.done, false, 'Upstream remains open while client reads')
        cuerpoSse += new TextDecoder().decode(bloque.value)
      }
      assert.ok(cuerpoSse.includes('operador.actualizado'), 'SSE event reaches the client')
      const solicitud = harness.requests[0]
      assert.ok(solicitud, 'SSE request reached the private upstream')
      assert.equal(solicitud.path, '/api/eventos')
      assert.equal(solicitud.query, '?cursor_eventos=41', 'Only the validated cursor is forwarded')
      assert.equal(solicitud.cookie, cookie, 'Authenticated cookie is forwarded')
      assert.equal(solicitud.accept, 'text/event-stream', 'Event stream Accept is explicit')
      assert.equal(solicitud.lastEventId, undefined, 'Initial cursor stays distinct from native reconnect state')
      assert.equal(solicitud.role, undefined, 'Browser role is not forwarded')
      assert.equal(solicitud.roleAlias, undefined, 'Role alias is not forwarded')

      void lector.cancel()
      await Promise.race([
        upstreamCerrado,
        delay(3000).then(() => assert.fail('Downstream cancellation did not close upstream')),
      ])
      harness.clearRequests()
    })

    await suite.test('legacy SSE BFF is only an alias to the unified upstream route', async () => {
      const cookie = `smart_parking_session=${marker()}`
      const respuesta = await send(
        '/api/admin/operadores/eventos?cursor_eventos=19',
        { headers: { cookie } },
        jsonPlan(401, { detail: 'No autenticado' }),
      )
      assert.equal(respuesta.response.status, 401)
      assertForwarded(respuesta, 'GET', '/api/eventos?cursor_eventos=19')
      assert.equal(respuesta.upstreamRequest?.cookie, cookie)
      assert.equal(respuesta.response.headers.get('cache-control'), 'no-store')
      assertNoSensitiveBody(respuesta.body)
      harness.clearRequests()
    })

    await suite.test('unified SSE preserves both cursors and rejects malformed initial cursor', async () => {
      const cookie = `smart_parking_session=${marker()}`
      const plan: UpstreamPlan = {
        status: 200,
        body: 'retry: 1000\n\n',
        stream: true,
        headers: { 'content-type': 'text/event-stream' },
      }
      harness.queueResponse(plan)
      const respuesta = await fetch(
        `${harness.origin}/api/eventos?cursor_eventos=41`,
        { headers: { cookie, 'last-event-id': '42' }, signal: AbortSignal.timeout(10_000) },
      )
      const lector = respuesta.body?.getReader()
      assert.ok(lector)
      await lector.read()
      assert.equal(harness.requests[0]?.lastEventId, '42', 'Native reconnect cursor is preserved')
      assert.equal(harness.requests[0]?.query, '?cursor_eventos=41')
      await lector.cancel()

      harness.clearRequests()
      const invalida = await fetch(
        `${harness.origin}/api/eventos?cursor_eventos=4x`,
        { headers: { cookie } },
      )
      await invalida.arrayBuffer()
      assert.equal(invalida.status, 400, 'Malformed cursor is rejected at the same-origin boundary')
      assert.equal(harness.requests.length, 0, 'Malformed cursor does not reach FastAPI')
    })

    await suite.test('successful SSE headers flush before a delayed first body chunk', async () => {
      const cookie = `smart_parking_session=${marker()}`
      let cerrarUpstream!: () => void
      const upstreamCerrado = new Promise<void>((resolve) => {
        cerrarUpstream = resolve
      })
      harness.queueResponse({
        status: 200,
        body: 'retry: 1000\n\n',
        stream: true,
        firstChunkDelayMs: 1800,
        headers: { 'content-type': 'text/event-stream; charset=utf-8' },
        onClose: cerrarUpstream,
      })

      const inicio = Date.now()
      const respuesta = await fetch(`${harness.origin}/api/eventos`, {
        headers: { cookie },
        signal: AbortSignal.timeout(5000),
      })
      const demora = Date.now() - inicio
      assert.equal(respuesta.status, 200)
      assert.ok(demora < 1200, `SSE response headers took ${demora} ms`)
      assert.equal(respuesta.headers.get('content-type')?.startsWith('text/event-stream'), true)
      assert.equal(respuesta.headers.get('cache-control'), 'no-store')
      assert.equal(respuesta.headers.get('x-accel-buffering'), 'no')
      void respuesta.body?.cancel()
      await Promise.race([
        upstreamCerrado,
        delay(3000).then(() => assert.fail('Delayed SSE cancellation did not close upstream')),
      ])
      harness.clearRequests()
    })

    await suite.test('non-SSE error bodies keep status and JSON response semantics', async () => {
      for (const status of [401, 429, 503]) {
        const result = await send(
          '/api/eventos',
          {},
          jsonPlan(status, { detail: `fixture-${status}` }),
        )
        assert.equal(result.response.status, status)
        assert.equal(result.response.headers.get('content-type')?.startsWith('application/json'), true)
        assert.ok(matchesFlatJson(result.body, { detail: `fixture-${status}` }))
      }
      harness.clearRequests()
    })

    await suite.test('all relevant upstream statuses and sanitized errors', async () => {
      const cases = [
        { status: 401, body: { detail: 'No autenticado' } },
        { status: 404, body: { detail: 'No encontrado' } },
        { status: 409, body: { detail: 'Conflicto' } },
        { status: 422, body: { detail: 'Solicitud invalida' } },
        { status: 429, body: { detail: 'Demasiados intentos' }, retryAfter: '17' },
        { status: 500, body: { detail: 'Error interno' } },
        { status: 503, body: { detail: 'Servicio temporalmente no disponible' } },
      ]

      for (const item of cases) {
        const result = await send(
          '/api/admin/operadores',
          {},
          jsonPlan(item.status, item.body, item.retryAfter
            ? { 'retry-after': item.retryAfter }
            : {}),
        )
        assert.ok(result.response.status === item.status, 'Upstream security status was preserved')
        assertForwarded(result, 'GET', '/api/admin/operadores')
        assert.ok(result.response.headers.get('cache-control') === 'no-store', 'Error remains no-store')
        assert.ok(matchesFlatJson(result.body, item.body), 'Sanitized upstream error body was preserved')
        if (item.retryAfter) {
          assert.ok(result.response.headers.get('retry-after') === item.retryAfter, 'Retry-After was preserved')
        }
        assertNoSensitiveBody(result.body)
      }
      harness.clearRequests()
    })

    await suite.test('activation exchange, challenge, completion, and replay proxying', async () => {
      const challengeCookie = `smart_parking_activation_challenge=${challengeToken}`
      const linkBody = JSON.stringify({ token: activationToken })
      const exchange = await send(
        '/api/autenticacion/activacion-operador/enlace',
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: linkBody,
        },
        jsonPlan(204, null, {
          'set-cookie': `${challengeCookie}; Max-Age=600; Path=/api/autenticacion/activacion-operador; HttpOnly; Secure; SameSite=Lax`,
        }),
      )
      assert.ok(exchange.response.status === 204, 'Valid exchange remains 204')
      assert.ok(exchange.body === '', '204 response remains bodyless')
      assertForwarded(exchange, 'POST', '/api/autenticacion/activacion-operador/enlace')
      assert.ok(exchange.upstreamRequest.body === linkBody, 'Activation token body was forwarded unchanged')
      assert.ok(exchange.response.headers.get('cache-control') === 'no-store', 'Activation exchange remains no-store')
      assert.ok(exchange.response.headers.get('referrer-policy') === 'no-referrer', 'Activation exchange remains no-referrer')
      const exchangeCookies = exchange.response.headers.getSetCookie()
      assert.ok(exchangeCookies.length === 1, 'Challenge Set-Cookie survived 204 proxying')
      assert.ok(
        exchangeCookies[0].includes(challengeToken)
          && /httponly/i.test(exchangeCookies[0])
          && /secure/i.test(exchangeCookies[0])
          && /samesite=lax/i.test(exchangeCookies[0])
          && /path=\/api\/autenticacion\/activacion-operador/i.test(exchangeCookies[0]),
        'Challenge cookie attributes survived proxying',
      )

      const injectedBody = JSON.stringify({
        token: activationToken,
        rol: 'OWNER',
        user_id: '900',
        email: 'attacker@example.invalid',
        id: '900',
        estado: 'activo',
      })
      const injected = await send(
        '/api/autenticacion/activacion-operador/enlace',
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: injectedBody,
        },
        jsonPlan(422, { detail: 'Solicitud invalida' }),
      )
      assert.ok(injected.response.status === 422, 'Injected identity fields remain rejected')
      assertForwarded(injected, 'POST', '/api/autenticacion/activacion-operador/enlace')
      assert.ok(matchesFlatJson(injected.upstreamRequest.body, JSON.parse(injectedBody)), 'Injected body reached backend unchanged')

      for (const state of [
        { cookie: undefined, valid: false },
        { cookie: `smart_parking_activation_challenge=${marker()}`, valid: false },
        { cookie: challengeCookie, valid: true },
      ]) {
        const result = await send(
          '/api/autenticacion/activacion-operador/desafio',
          { headers: state.cookie ? { cookie: state.cookie } : {} },
          jsonPlan(200, { valido: state.valid }),
        )
        assert.ok(result.response.status === 200, 'Challenge status response was preserved')
        assertForwarded(result, 'GET', '/api/autenticacion/activacion-operador/desafio')
        assert.ok(result.upstreamRequest.cookie === state.cookie, 'Challenge cookie was forwarded unchanged')
        assert.ok(result.response.headers.get('cache-control') === 'no-store', 'Challenge status remains no-store')
        assert.ok(result.response.headers.get('referrer-policy') === 'no-referrer', 'Challenge status remains no-referrer')
        assertNoSensitiveBody(result.body)
      }

      const completionBody = JSON.stringify({ nueva_contrasena: password })
      const completion = await send(
        '/api/autenticacion/activacion-operador/completar',
        {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            cookie: challengeCookie,
          },
          body: completionBody,
        },
        jsonPlan(200, { estado: 'cuenta_activada' }, {
          'set-cookie': 'smart_parking_activation_challenge=; Max-Age=0; Path=/api/autenticacion/activacion-operador; HttpOnly; Secure; SameSite=Lax',
        }),
      )
      assert.ok(completion.response.status === 200, 'Completion status was preserved')
      assertForwarded(completion, 'POST', '/api/autenticacion/activacion-operador/completar')
      assert.ok(completion.upstreamRequest.cookie === challengeCookie, 'Completion challenge reached FastAPI')
      assert.ok(completion.upstreamRequest.body === completionBody, 'Completion body was forwarded unchanged')
      assert.ok(completion.response.headers.get('cache-control') === 'no-store', 'Completion remains no-store')
      assert.ok(completion.response.headers.get('referrer-policy') === 'no-referrer', 'Completion remains no-referrer')
      const completionCookies = completion.response.headers.getSetCookie()
      assert.ok(completionCookies.length === 1, 'Challenge removal survived completion proxying')
      assert.ok(
        /max-age=0/i.test(completionCookies[0])
          && /httponly/i.test(completionCookies[0])
          && /secure/i.test(completionCookies[0])
          && /samesite=lax/i.test(completionCookies[0])
          && /path=\/api\/autenticacion\/activacion-operador/i.test(completionCookies[0]),
        'Challenge removal attributes survived proxying',
      )

      for (const replay of [
        { cookie: undefined, status: 404 },
        { cookie: `smart_parking_activation_challenge=${marker()}`, status: 404 },
        { cookie: challengeCookie, status: 404 },
      ]) {
        const result = await send(
          '/api/autenticacion/activacion-operador/completar',
          { method: 'POST', headers: replay.cookie ? { cookie: replay.cookie } : {} },
          jsonPlan(replay.status, { detail: 'Activación no disponible' }),
        )
        assert.ok(result.response.status === replay.status, 'Missing, changed, or replayed challenge stayed denied')
        assertForwarded(result, 'POST', '/api/autenticacion/activacion-operador/completar')
        assert.ok(result.response.headers.get('cache-control') === 'no-store', 'Replay response remains no-store')
        assert.ok(result.response.headers.get('referrer-policy') === 'no-referrer', 'Replay response remains no-referrer')
      }

      for (const activationPath of ['/api/activacion/prevalidar', '/api/activacion/manual']) {
        const requestsBefore = harness.requests.length
        const result = await send(
          activationPath,
        )
        assert.ok(result.response.status === 404, 'Retired activation endpoint stays unavailable')
        assert.ok(harness.requests.length === requestsBefore, 'Retired activation endpoint did not reach FastAPI')
      }

      const invalidModeBefore = harness.requests.length
      const invalidMode = await send('/api/activacion/invalid-mode', { method: 'POST' })
      assert.ok(invalidMode.response.status === 404, 'Unknown activation mode is rejected locally')
      assert.ok(harness.requests.length === invalidModeBefore, 'Unknown activation mode did not reach FastAPI')
      harness.clearRequests()
    })

    await suite.test('OWNER activation BFF scopes cookies and strips session credentials', async () => {
      const exchangeBody = JSON.stringify({ token: activationToken })
      const exchange = await send(
        '/api/autenticacion/activacion-propietario/enlace',
        {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            cookie: `smart_parking_session=${sessionToken}`,
          },
          body: exchangeBody,
        },
        {
          status: 204,
          headers: {
            'set-cookie': `smart_parking_owner_activation_challenge=${challengeToken}; Path=/api/autenticacion/activacion-propietario; HttpOnly; Secure; SameSite=Lax`,
            'cache-control': 'no-store',
          },
        },
      )
      assert.ok(exchange.response.status === 204, 'OWNER exchange status was preserved')
      assertForwarded(exchange, 'POST', '/api/autenticacion/activacion-propietario/enlace')
      assert.ok(exchange.upstreamRequest.cookie === undefined, 'Session cookie is not sent during email-token exchange')
      assert.ok(exchange.upstreamRequest.body === exchangeBody, 'Only the opaque email token is forwarded')
      assert.ok(exchange.response.headers.get('cache-control') === 'no-store', 'OWNER exchange is no-store')
      assert.ok(exchange.response.headers.get('referrer-policy') === 'no-referrer', 'OWNER exchange is no-referrer')
      const exchangeCookies = exchange.response.headers.getSetCookie()
      assert.ok(exchangeCookies.length === 1, 'OWNER challenge cookie reached the browser')
      assert.ok(
        /httponly/i.test(exchangeCookies[0])
          && /secure/i.test(exchangeCookies[0])
          && /samesite=lax/i.test(exchangeCookies[0])
          && /path=\/api\/autenticacion\/activacion-propietario/i.test(exchangeCookies[0]),
        'OWNER challenge cookie remains HttpOnly and path-scoped',
      )

      const ownerCookie = `smart_parking_owner_activation_challenge=${challengeToken}`
      const status = await send(
        '/api/autenticacion/activacion-propietario/desafio',
        {
          headers: {
            cookie: `${ownerCookie}; smart_parking_session=${sessionToken}`,
          },
        },
        jsonPlan(200, { valido: true, tipo_cuenta: 'nueva' }),
      )
      assert.ok(status.response.status === 200, 'OWNER challenge status was preserved')
      assertForwarded(status, 'GET', '/api/autenticacion/activacion-propietario/desafio')
      assert.ok(status.upstreamRequest.cookie === ownerCookie, 'Only the scoped OWNER challenge reaches FastAPI')
      assert.ok(status.response.headers.get('cache-control') === 'no-store', 'OWNER challenge status is no-store')
      assert.ok(status.response.headers.get('referrer-policy') === 'no-referrer', 'OWNER challenge status is no-referrer')
      assertNoSensitiveBody(status.body)

      const completionBody = JSON.stringify({
        contrasena_admin: password,
        contrasena_login: sensitiveMarkers[1],
      })
      const completion = await send(
        '/api/autenticacion/activacion-propietario/completar',
        {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            cookie: `${ownerCookie}; smart_parking_session=${sessionToken}`,
          },
          body: completionBody,
        },
        jsonPlan(200, { estado: 'owner_activado' }, {
          'set-cookie': 'smart_parking_owner_activation_challenge=; Max-Age=0; Path=/api/autenticacion/activacion-propietario; HttpOnly; Secure; SameSite=Lax',
        }),
      )
      assert.ok(completion.response.status === 200, 'OWNER completion status was preserved')
      assertForwarded(completion, 'POST', '/api/autenticacion/activacion-propietario/completar')
      assert.ok(completion.upstreamRequest.cookie === ownerCookie, 'Only OWNER challenge cookie reaches completion')
      assert.ok(completion.upstreamRequest.body === completionBody, 'Password body was forwarded to FastAPI')
      assert.ok(completion.response.headers.get('cache-control') === 'no-store', 'OWNER completion is no-store')
      assert.ok(completion.response.headers.get('referrer-policy') === 'no-referrer', 'OWNER completion is no-referrer')
      assertNoSensitiveBody(completion.body)
      const removal = completion.response.headers.getSetCookie()
      assert.ok(removal.length === 1 && /max-age=0/i.test(removal[0]), 'OWNER challenge cookie is removed after activation')
      assert.ok(/path=\/api\/autenticacion\/activacion-propietario/i.test(removal[0]), 'OWNER challenge removal stays path-scoped')
      harness.clearRequests()
    })

    await suite.test('temporary OWNER management BFF scopes its cookie and protects mutations', async () => {
      const ticket = marker()
      const pairingCode = marker()
      const managementToken = marker()
      const ordinarySession = marker()
      sensitiveMarkers.push(ticket, pairingCode, managementToken, ordinarySession)
      const managementCookie = `smart_parking_owner_management=${managementToken}`

      const claimBody = JSON.stringify({
        ticket,
        codigo_apareamiento: pairingCode,
      })
      const claim = await send(
        '/api/gestion-propietario/claim',
        {
          method: 'POST',
          headers: {
            origin: harness.origin,
            'content-type': 'application/json',
            cookie: `smart_parking_session=${ordinarySession}; ${managementCookie}`,
          },
          body: claimBody,
        },
        jsonPlan(200, { activa: true }, {
          'set-cookie': `${managementCookie}; Path=/; HttpOnly; Secure; SameSite=Strict`,
          'cache-control': 'no-store',
        }),
      )
      assert.equal(claim.response.status, 200)
      assertForwarded(claim, 'POST', '/api/gestion-propietario/v1/claim')
      assert.equal(claim.upstreamRequest?.origin, harness.origin)
      assert.equal(claim.upstreamRequest?.cookie, managementCookie)
      assert.equal(claim.upstreamRequest?.body, claimBody)
      assert.equal(claim.response.headers.get('cache-control'), 'no-store')
      assert.equal(claim.response.headers.get('referrer-policy'), 'no-referrer')
      const claimCookies = claim.response.headers.getSetCookie()
      assert.equal(claimCookies.length, 1)
      assert.ok(/httponly/i.test(claimCookies[0]))
      assert.ok(/secure/i.test(claimCookies[0]))
      assert.ok(/samesite=strict/i.test(claimCookies[0]))
      assertNoSensitiveBody(claim.body)

      harness.clearRequests()
      const sinOrigen = await send(
        '/api/gestion-propietario/claim',
        {
          method: 'POST',
          headers: {
            origin: 'https://attacker.invalid',
            'content-type': 'application/json',
          },
          body: claimBody,
        },
      )
      assert.equal(sinOrigen.response.status, 403)
      assert.equal(sinOrigen.upstreamRequest, undefined)
      assertNoSensitiveBody(sinOrigen.body)

      harness.clearRequests()
      const estado = await send(
        '/api/gestion-propietario/estado',
        {
          headers: {
            cookie: `${managementCookie}; smart_parking_session=${ordinarySession}`,
          },
        },
        jsonPlan(200, { owner_activo: false, owner: null, inscripciones: [] }),
      )
      assert.equal(estado.response.status, 200)
      assertForwarded(estado, 'GET', '/api/gestion-propietario/v1/estado')
      assert.equal(estado.upstreamRequest?.cookie, managementCookie)
      assert.equal(estado.response.headers.get('cache-control'), 'no-store')
      assert.equal(estado.response.headers.get('referrer-policy'), 'no-referrer')
      assertNoSensitiveBody(estado.body)

      harness.clearRequests()
      const reenvio = await send(
        '/api/gestion-propietario/inscripciones/17/reenviar',
        {
          method: 'POST',
          headers: {
            origin: harness.origin,
            cookie: `${managementCookie}; smart_parking_session=${ordinarySession}`,
          },
        },
        { status: 204 },
      )
      assert.equal(reenvio.response.status, 204)
      assertForwarded(reenvio, 'POST', '/api/gestion-propietario/v1/inscripciones/17/reenviar')
      assert.equal(reenvio.upstreamRequest?.cookie, managementCookie)
      assert.equal(reenvio.upstreamRequest?.origin, harness.origin)

      const adminPassword = marker()
      sensitiveMarkers.push(adminPassword)
      harness.clearRequests()
      const desvinculacion = await send(
        '/api/gestion-propietario/desvinculacion',
        {
          method: 'POST',
          headers: {
            origin: harness.origin,
            'content-type': 'application/json',
            cookie: managementCookie,
          },
          body: JSON.stringify({ contrasena_admin: adminPassword }),
        },
        jsonPlan(202, { estado: 'confirmacion_enviada' }, {
          'cache-control': 'no-store',
          'referrer-policy': 'no-referrer',
        }),
      )
      assert.equal(desvinculacion.response.status, 202)
      assertForwarded(desvinculacion, 'POST', '/api/gestion-propietario/v1/desvinculacion')
      assert.equal(desvinculacion.upstreamRequest?.cookie, managementCookie)
      assert.equal(desvinculacion.upstreamRequest?.origin, harness.origin)
      assert.equal(
        desvinculacion.upstreamRequest?.body,
        JSON.stringify({ contrasena_admin: adminPassword }),
      )
      assert.equal(desvinculacion.response.headers.get('cache-control'), 'no-store')
      assertNoSensitiveBody(desvinculacion.body)

      const unlinkToken = marker()
      sensitiveMarkers.push(unlinkToken)
      harness.clearRequests()
      const confirmarDesvinculacion = await send(
        '/api/gestion-propietario/desvinculacion/confirmar',
        {
          method: 'POST',
          headers: {
            origin: harness.origin,
            'content-type': 'application/json',
            cookie: managementCookie,
          },
          body: JSON.stringify({ token: unlinkToken }),
        },
        jsonPlan(200, { estado: 'dueno_desvinculado' }, {
          'cache-control': 'no-store',
          'referrer-policy': 'no-referrer',
        }),
      )
      assert.equal(confirmarDesvinculacion.response.status, 200)
      assertForwarded(
        confirmarDesvinculacion,
        'POST',
        '/api/gestion-propietario/v1/desvinculacion/confirmar',
      )
      assert.equal(confirmarDesvinculacion.upstreamRequest?.cookie, undefined)
      assert.equal(confirmarDesvinculacion.upstreamRequest?.origin, harness.origin)
      assert.equal(
        confirmarDesvinculacion.upstreamRequest?.body,
        JSON.stringify({ token: unlinkToken }),
      )
      assert.equal(
        confirmarDesvinculacion.response.headers.get('referrer-policy'),
        'no-referrer',
      )
      assertNoSensitiveBody(confirmarDesvinculacion.body)

      harness.clearRequests()
      const confirmacionSinOrigen = await send(
        '/api/gestion-propietario/desvinculacion/confirmar',
        {
          method: 'POST',
          headers: {
            origin: 'https://attacker.invalid',
            'content-type': 'application/json',
          },
          body: JSON.stringify({ token: unlinkToken }),
        },
      )
      assert.equal(confirmacionSinOrigen.response.status, 403)
      assert.equal(confirmacionSinOrigen.upstreamRequest, undefined)
      assertNoSensitiveBody(confirmacionSinOrigen.body)

      harness.clearRequests()
      const idInvalido = await send(
        '/api/gestion-propietario/inscripciones/0/reenviar',
        { method: 'POST', headers: { origin: harness.origin } },
      )
      assert.equal(idInvalido.response.status, 400)
      assert.equal(idInvalido.upstreamRequest, undefined)

      harness.clearRequests()
      const paginaResponse = jsonPlan(200, { activa: false })
      harness.queueResponse(paginaResponse)
      const pagina = await fetch(`${harness.origin}/admin/gestion-propietario#${ticket}`)
      const paginaBody = await pagina.text()
      assert.equal(pagina.status, 200)
      assert.ok(paginaBody.includes('Navegador no autorizado'))
      assert.ok(!paginaBody.includes('Procesos de registro'))
      assert.ok(!paginaBody.includes('Salir'))
      assert.ok(!paginaBody.includes(ticket))
      assert.ok(!paginaBody.includes(pairingCode))
      assert.ok(!paginaBody.includes(managementToken))
      assert.ok(!paginaBody.includes(ordinarySession))
      assert.ok(harness.requests.some((item) => item.path === '/api/gestion-propietario/v1/sesion'))
      assertNoSensitiveBody(paginaBody)
      harness.clearRequests()

      const previewToken = marker()
      sensitiveMarkers.push(previewToken)
      const confirmacionPublica = await fetch(
        harness.origin + '/confirmar-desvinculacion#desvincular=' + previewToken,
      )
      const confirmacionPublicaBody = await confirmacionPublica.text()
      assert.equal(confirmacionPublica.status, 200)
      assert.equal(confirmacionPublica.headers.get('cache-control'), 'no-store')
      assert.equal(confirmacionPublica.headers.get('referrer-policy'), 'no-referrer')
      assert.ok(!confirmacionPublicaBody.includes(previewToken))
      assert.ok(confirmacionPublicaBody.includes('Confirmación por correo'))
      assert.equal(
        harness.requests.some((item) =>
          item.path.endsWith('/desvinculacion/confirmar')),
        false,
      )
      assertNoSensitiveBody(confirmacionPublicaBody)
      harness.clearRequests()
    })

    await suite.test('credential replacement remains OWNER-only and secret-safe', async () => {
      const cases = [
        { cookie: undefined, status: 401 },
        { cookie: `smart_parking_session=${marker()}`, status: 401 },
        { cookie: `smart_parking_session=${marker()}`, status: 401 },
        { cookie: `smart_parking_session=${marker()}`, status: 401 },
        { cookie: `smart_parking_session=${marker()}`, status: 200 },
        { cookie: `smart_parking_session=${marker()}`, status: 409 },
        { cookie: `smart_parking_session=${marker()}`, status: 503 },
      ]

      for (const item of cases) {
        const result = await send(
          '/api/admin/operadores/41/regenerar-contrasena',
          {
            method: 'POST',
            headers: item.cookie ? { cookie: item.cookie } : {},
          },
          jsonPlan(item.status, item.status === 200
            ? { estado: 'contrasena_regenerada' }
            : { detail: item.status === 503
              ? 'Servicio de correo temporalmente no disponible'
              : item.status === 409
                ? 'Cuenta no elegible'
                : 'No autenticado' }),
        )
        assert.ok(result.response.status === item.status, 'Credential replacement status was preserved')
        assertForwarded(result, 'POST', '/api/admin/operadores/41/regenerar-contrasena')
        assert.ok(result.upstreamRequest.cookie === item.cookie, 'Credential proxy forwarded only the supplied cookie')
        assert.ok(result.response.headers.get('cache-control') === 'no-store', 'Credential result remains no-store')
        assertNoSensitiveBody(result.body)
      }
      harness.clearRequests()
    })
  } finally {
    await harness.close()
    for (const value of sensitiveMarkers) {
      assert.ok(!harness.logs().includes(value), 'Sensitive marker leaked in Nuxt logs')
    }
  }
})
