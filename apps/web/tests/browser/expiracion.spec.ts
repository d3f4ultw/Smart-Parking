import { expect, test, type Page } from '@playwright/test'
import { baseURL, iniciarSesion } from './sesion'

type EstadoStreams = { aperturas: number; cierres: number }

declare global {
  interface Window {
    __estadoStreamsExpiracion?: EstadoStreams
  }
}

async function contarStreams(page: Page): Promise<number> {
  return page.evaluate(() => window.__estadoStreamsExpiracion?.aperturas ?? 0)
}

test('sesion inactiva vence a 45s y el destino protegido vuelve al panel', async ({ browser }) => {
  test.setTimeout(130_000)
  const contexto = await browser.newContext()
  const page = await contexto.newPage()
  await page.addInitScript(() => {
    const claveAperturas = '__prueba_expiracion_aperturas'
    const claveCierres = '__prueba_expiracion_cierres'
    const estado: EstadoStreams = {
      aperturas: Number(sessionStorage.getItem(claveAperturas) ?? '0'),
      cierres: Number(sessionStorage.getItem(claveCierres) ?? '0'),
    }
    window.__estadoStreamsExpiracion = estado
    const FuenteNativa = window.EventSource
    const cerrarNativo = FuenteNativa.prototype.close
    FuenteNativa.prototype.close = function () {
      estado.cierres += 1
      sessionStorage.setItem(claveCierres, String(estado.cierres))
      return cerrarNativo.call(this)
    }
    window.EventSource = class extends FuenteNativa {
      constructor(url: string | URL, opciones?: EventSourceInit) {
        super(url, opciones)
        estado.aperturas += 1
        sessionStorage.setItem(claveAperturas, String(estado.aperturas))
      }
    }
  })

  let ackBloqueados = 0
  let validacionesBloqueadas = 0
  let reconexionesAbortadas = 0
  let permitirValidacion = false
  let solicitudesStream = 0
  let solicitudesAck = 0
  let streamTerminado = 0
  let streamFallido = 0
  let streamFinalizadoAt = 0
  const estadosStream: number[] = []

  try {
    await iniciarSesion(page)
    page.on('response', (respuesta) => {
      const url = new URL(respuesta.url())
      if (respuesta.request().method() === 'GET' && url.pathname === '/api/v1/eventos/administracion') {
        estadosStream.push(respuesta.status())
      }
    })
    page.on('request', (solicitud) => {
      const url = new URL(solicitud.url())
      if (solicitud.method() === 'POST' && url.pathname.endsWith('/heartbeat')) solicitudesAck += 1
    })
    page.on('requestfinished', (solicitud) => {
      const url = new URL(solicitud.url())
      if (solicitud.method() === 'GET' && url.pathname === '/api/v1/eventos/administracion') {
        streamTerminado += 1
        streamFinalizadoAt = Date.now()
      }
    })
    page.on('requestfailed', (solicitud) => {
      const url = new URL(solicitud.url())
      if (solicitud.method() === 'GET' && url.pathname === '/api/v1/eventos/administracion') {
        streamFallido += 1
        streamFinalizadoAt = Date.now()
      }
    })
    await page.route('**/api/v1/**', async (route) => {
      const solicitud = route.request()
      const url = new URL(solicitud.url())
      if (solicitud.method() === 'POST' && url.pathname.endsWith('/heartbeat')) {
        ackBloqueados += 1
        await route.abort('failed')
        return
      }
      if (solicitud.method() === 'GET' && url.pathname === '/api/v1/sesion' && !permitirValidacion) {
        validacionesBloqueadas += 1
        await route.abort('failed')
        return
      }
      if (solicitud.method() === 'GET' && url.pathname === '/api/v1/eventos/administracion') {
        solicitudesStream += 1
        if (solicitudesStream > 1) {
          reconexionesAbortadas += 1
          await route.abort('failed')
          return
        }
      }
      await route.continue()
    })

    const inicioInactividad = Date.now()
    await page.goto(`${baseURL}/admin/empleados`)
    await expect(page.getByRole('region', { name: 'Lista de empleados' })).toBeVisible()
    await expect.poll(() => estadosStream.includes(200), { timeout: 15_000 }).toBe(true)
    await page.waitForTimeout(50_000)
    expect(streamTerminado + streamFallido).toBeGreaterThan(0)
    const esperaPosteriorAlCierre = Math.max(0, 65_000 - (Date.now() - streamFinalizadoAt))
    await page.waitForTimeout(esperaPosteriorAlCierre)
    const segundosInactivos = Math.floor((Date.now() - inicioInactividad) / 1000)
    const segundosDesdeCierre = Math.floor((Date.now() - streamFinalizadoAt) / 1000)
    expect(segundosInactivos).toBeGreaterThanOrEqual(45)
    expect(segundosDesdeCierre).toBeGreaterThanOrEqual(45)
    expect(ackBloqueados).toBeGreaterThan(0)

    permitirValidacion = true
    const sesion = await page.evaluate(async () => {
      const respuesta = await fetch('/api/v1/sesion', { credentials: 'same-origin' })
      let autenticada: boolean | undefined
      try {
        const cuerpo = (await respuesta.json()) as Record<string, unknown>
        if (typeof cuerpo.autenticada === 'boolean') autenticada = cuerpo.autenticada
        if (typeof cuerpo.authenticated === 'boolean') autenticada = cuerpo.authenticated
      } catch {
        autenticada = undefined
      }
      return { estado: respuesta.status, autenticada }
    })
    console.log(
      `Inactividad ${segundosInactivos}s; GET sesión ${sesion.estado}; autenticada=${sesion.autenticada ?? 'desconocida'}; ACK observados/bloqueados ${solicitudesAck}/${ackBloqueados}; GET sesión bloqueados ${validacionesBloqueadas}; reconexiones SSE bloqueadas ${reconexionesAbortadas}; streams terminados/fallidos ${streamTerminado}/${streamFallido}`,
    )
    expect(sesion.estado === 401 || (sesion.estado === 200 && sesion.autenticada === false)).toBe(true)
    const aperturasAntesDeRutaProtegida = await contarStreams(page)

    await page.goto(`${baseURL}/admin/empleados`)
    await expect.poll(() => new URL(page.url()).pathname).toBe('/panel')
    expect(await contarStreams(page)).toBe(aperturasAntesDeRutaProtegida)
  } finally {
    await contexto.close()
  }
})
