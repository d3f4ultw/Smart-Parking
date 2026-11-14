import { expect, test, type Page, type Request as PlaywrightRequest } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { abrirDirectorio, baseURL } from './sesion'

type EvidenciaSse = {
  conexiones: Array<{ tieneCursor: boolean }>
  heartbeats: boolean[]
  eventosDirectorio: number
  cierres: number
}

declare global {
  interface Window {
    __evidenciaSseEmpleados?: EvidenciaSse
  }
}

type RespuestaAck = {
  estado: number
  payloadValido: boolean
  csrfPresente: boolean
}

type Telemetria = {
  intentosSse: Array<{ tieneCursor: boolean }>
  estadosSse: number[]
  ultimoSse200At: number
  acks: RespuestaAck[]
  lecturasEmpleados: number
  navegaciones: number
  bajasSesion: number[]
}

async function instrumentarSse(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const claveCierres = '__prueba_empleados_sse_cierres'
    const cierresPrevios = Number(sessionStorage.getItem(claveCierres) ?? '0')
    const evidencia: EvidenciaSse = {
      conexiones: [],
      heartbeats: [],
      eventosDirectorio: 0,
      cierres: cierresPrevios,
    }
    window.__evidenciaSseEmpleados = evidencia

    const FuenteNativa = window.EventSource
    const cerrarNativo = FuenteNativa.prototype.close
    FuenteNativa.prototype.close = function () {
      evidencia.cierres += 1
      sessionStorage.setItem(claveCierres, String(evidencia.cierres))
      return cerrarNativo.call(this)
    }

    window.EventSource = class extends FuenteNativa {
      constructor(url: string | URL, opciones?: EventSourceInit) {
        super(url, opciones)
        const destino = new URL(String(url), location.href)
        evidencia.conexiones.push({
          tieneCursor:
            destino.searchParams.has('despues') || Boolean(this.withCredentials && destino.searchParams.has('cursor')),
        })
        this.addEventListener('empleado.heartbeat', (evento) => {
          evidencia.heartbeats.push(Boolean((evento as MessageEvent).lastEventId))
        })
        this.addEventListener('empleado.directorio.actualizado', () => {
          evidencia.eventosDirectorio += 1
        })
      }
    }
  })
}

function observar(page: Page): Telemetria {
  const telemetria: Telemetria = {
    intentosSse: [],
    estadosSse: [],
    ultimoSse200At: 0,
    acks: [],
    lecturasEmpleados: 0,
    navegaciones: 0,
    bajasSesion: [],
  }
  const ackPendientes = new WeakMap<PlaywrightRequest, { payloadValido: boolean; csrfPresente: boolean }>()

  page.on('request', (request) => {
    if (request.isNavigationRequest()) telemetria.navegaciones += 1
    const url = new URL(request.url())
    if (request.method() === 'GET' && url.pathname === '/api/v1/empleados') telemetria.lecturasEmpleados += 1

    if (request.method() === 'GET' && url.pathname === '/api/v1/eventos/administracion') {
      const headers = request.headers()
      telemetria.intentosSse.push({
        tieneCursor: url.searchParams.has('despues') || Boolean(headers['last-event-id']),
      })
    }

    if (request.method() === 'POST' && url.pathname === '/api/v1/eventos/administracion/heartbeat') {
      let payloadValido = false
      try {
        const cuerpo = JSON.parse(request.postData() ?? '{}') as Record<string, unknown>
        payloadValido = typeof cuerpo.suscripcionId === 'string' && Number.isInteger(cuerpo.secuencia)
      } catch {
        payloadValido = false
      }
      ackPendientes.set(request, {
        payloadValido,
        csrfPresente: Boolean(request.headers()['x-csrf-token']),
      })
    }
  })

  page.on('response', (response) => {
    const request = response.request()
    const url = new URL(response.url())
    if (request.method() === 'GET' && url.pathname === '/api/v1/eventos/administracion') {
      telemetria.estadosSse.push(response.status())
      if (response.status() === 200) telemetria.ultimoSse200At = Date.now()
    }
    if (request.method() === 'POST' && url.pathname === '/api/v1/eventos/administracion/heartbeat') {
      const forma = ackPendientes.get(request)
      telemetria.acks.push({
        estado: response.status(),
        payloadValido: forma?.payloadValido ?? false,
        csrfPresente: forma?.csrfPresente ?? false,
      })
    }
    if (request.method() === 'DELETE' && url.pathname === '/api/v1/sesion') {
      telemetria.bajasSesion.push(response.status())
    }
  })
  return telemetria
}

async function registrarEmpleado(page: Page): Promise<string> {
  const nombre = `Sse-${randomUUID().slice(0, 8)}`
  await page.getByRole('button', { name: 'Registrar empleado' }).first().click()
  const dialogo = page.getByRole('dialog', { name: 'Registrar empleado' })
  await expect(dialogo).toBeVisible()
  await page.getByLabel('Nombres').fill(nombre)
  await page.getByLabel('Primer apellido').fill('Prueba')
  await page.getByLabel('Segundo apellido (opcional)').fill('Sse')
  await page.getByRole('button', { name: 'Registrar', exact: true }).click()
  await expect(dialogo).toBeHidden()
  return nombre
}

async function evidenciaDe(page: Page): Promise<EvidenciaSse> {
  return page.evaluate(() =>
    window.__evidenciaSseEmpleados ?? { conexiones: [], heartbeats: [], eventosDirectorio: 0, cierres: 0 },
  )
}

test('dos sesiones mantienen SSE, reconocen heartbeat y refrescan por evento sin recargar', async ({ browser }) => {
  test.setTimeout(150_000)
  const contextoA = await browser.newContext()
  const contextoB = await browser.newContext()
  const paginaA = await contextoA.newPage()
  const paginaB = await contextoB.newPage()
  await instrumentarSse(paginaA)
  await instrumentarSse(paginaB)

  const telemetriaA = observar(paginaA)
  const telemetriaB = observar(paginaB)
  let intentosA = 0
  await paginaA.route('**/api/v1/eventos/administracion**', async (route) => {
    if (route.request().method() === 'GET') {
      intentosA += 1
      if (intentosA === 1) {
        await route.abort('failed')
        return
      }
    }
    await route.continue()
  })

  try {
    await abrirDirectorio(paginaA)
    await abrirDirectorio(paginaB)
    const cookiesA = await contextoA.cookies(baseURL)
    const cookiesB = await contextoB.cookies(baseURL)
    const sesionA = cookiesA.find((cookie) => cookie.name === 'JSESSIONID')
    const sesionB = cookiesB.find((cookie) => cookie.name === 'JSESSIONID')
    expect(Boolean(sesionA && sesionB && sesionA.value !== sesionB.value)).toBe(true)

    await expect.poll(() => telemetriaA.estadosSse.includes(200), { timeout: 30_000 }).toBe(true)
    await expect.poll(() => telemetriaA.intentosSse.length, { timeout: 20_000 }).toBeGreaterThanOrEqual(2)
    await expect.poll(() => telemetriaB.estadosSse.includes(200), { timeout: 20_000 }).toBe(true)
    const reintentoConCursor = telemetriaA.intentosSse[1]?.tieneCursor ?? false
    expect(reintentoConCursor).toBe(true)

    telemetriaA.navegaciones = 0
    telemetriaB.navegaciones = 0
    const lecturasAntesDelHeartbeat = telemetriaA.lecturasEmpleados
    const inicioSseEstable = telemetriaA.ultimoSse200At
    await paginaA.waitForTimeout(26_000)
    expect(Date.now() - inicioSseEstable).toBeGreaterThanOrEqual(25_000)
    await expect.poll(async () => (await evidenciaDe(paginaA)).heartbeats.length).toBeGreaterThan(0)
    await expect.poll(() => telemetriaA.acks.some((ack) => ack.estado === 204), { timeout: 10_000 }).toBe(true)
    const ackValido = telemetriaA.acks.find((ack) => ack.estado === 204)
    expect(Boolean(ackValido?.payloadValido && ackValido.csrfPresente)).toBe(true)
    const idsHeartbeat = (await evidenciaDe(paginaA)).heartbeats
    expect(idsHeartbeat.length).toBeGreaterThan(0)
    expect(idsHeartbeat.every((tieneId) => !tieneId)).toBe(true)
    await paginaA.waitForTimeout(1_000)
    expect(telemetriaA.lecturasEmpleados).toBe(lecturasAntesDelHeartbeat)

    const lecturasB = telemetriaB.lecturasEmpleados
    const navegacionesB = telemetriaB.navegaciones
    await registrarEmpleado(paginaA)
    await expect.poll(() => telemetriaB.lecturasEmpleados, { timeout: 15_000 }).toBeGreaterThan(lecturasB)
    await expect
      .poll(async () => (await evidenciaDe(paginaB)).eventosDirectorio, { timeout: 15_000 })
      .toBeGreaterThan(0)
    expect(telemetriaB.navegaciones - navegacionesB).toBe(0)

    const enlacePanel = paginaA.locator('a[href="/admin"]').first()
    await enlacePanel.click()
    await expect.poll(() => new URL(paginaA.url()).pathname).toBe('/admin')
    await expect.poll(async () => (await evidenciaDe(paginaA)).cierres).toBeGreaterThan(0)

    await paginaB.getByRole('button', { name: /cerrar sesión/i }).click()
    await expect.poll(() => new URL(paginaB.url()).pathname).toBe('/panel')
    await expect.poll(() => telemetriaB.bajasSesion.includes(200)).toBe(true)
    await expect.poll(async () => (await evidenciaDe(paginaB)).cierres).toBeGreaterThan(0)
    await paginaB.goto(`${baseURL}/admin/empleados`)
    await expect.poll(() => new URL(paginaB.url()).pathname).toBe('/panel')
  } finally {
    await contextoA.close()
    await contextoB.close()
  }
})
