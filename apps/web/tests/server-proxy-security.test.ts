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
}

type CapturedRequest = {
  method: string
  path: string
  query: string
  cookie?: string
  contentType?: string
  role?: string
  roleAlias?: string
  userId?: string
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
    contentType: headerValue(request.headers['content-type']),
    role: headerValue(request.headers['x-user-role']),
    roleAlias: headerValue(request.headers['x-role']),
    userId: headerValue(request.headers['x-user-id']),
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
    await suite.test('cookie matrix and ADMIN denial semantics', async () => {
      const states = [
        { name: 'anonymous', value: undefined, status: 401 },
        { name: 'ADMIN', value: marker(), status: 200 },
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
          'ADMIN response remains no-store',
        )
        assertNoSensitiveBody(result.body)
      }

      const forged = await send(
        '/api/admin/operadores',
        {
          headers: {
            cookie: `unrelated=${marker()}`,
            'x-user-role': 'ADMIN',
            'x-role': 'ADMIN',
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
        jsonPlan(200, { autenticado: true, usuario: { rol: 'ADMIN' } }),
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
        rol: 'ADMIN',
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
        `/api/admin/operadores?pagina=2&rol=ADMIN&user_id=${marker()}`,
        { headers: { cookie: `smart_parking_session=${marker()}` } },
        jsonPlan(200, { pagina: 2, operadores: [] }),
      )
      assert.ok(page.response.status === 200, 'Paginated list was successful')
      assertForwarded(page, 'GET', '/api/admin/operadores?pagina=2')
      assert.ok(page.upstreamRequest.query === '?pagina=2', 'Only intended pagination query was forwarded')

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
        '/api/admin/operadores/41?id=999&rol=ADMIN',
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
        rol: 'ADMIN',
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

      for (const activationPath of [
        '/api/activacion/prevalidar',
        '/api/activacion/manual',
      ]) {
        const responsePath = activationPath.endsWith('prevalidar')
          ? '/api/autenticacion/activacion/prevalidar'
          : '/api/autenticacion/activar/manual'
        const result = await send(
          activationPath,
          {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ token: activationToken }),
          },
          jsonPlan(422, { detail: 'Solicitud invalida' }, { 'cache-control': 'no-store' }),
        )
        assert.ok(result.response.status === 422, 'General activation status was preserved')
        assertForwarded(result, 'POST', responsePath)
        assert.ok(result.response.headers.get('cache-control') === 'no-store', 'General activation preserved backend no-store')
      }

      const invalidModeBefore = harness.requests.length
      const invalidMode = await send('/api/activacion/invalid-mode', { method: 'POST' })
      assert.ok(invalidMode.response.status === 404, 'Unknown activation mode is rejected locally')
      assert.ok(harness.requests.length === invalidModeBefore, 'Unknown activation mode did not reach FastAPI')
      harness.clearRequests()
    })

    await suite.test('credential replacement remains ADMIN-only and secret-safe', async () => {
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
