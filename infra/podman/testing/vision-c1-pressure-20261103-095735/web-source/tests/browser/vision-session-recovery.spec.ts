import { randomUUID } from 'node:crypto'
import { access, writeFile } from 'node:fs/promises'
import { expect, test, type Page, type Request as PlaywrightRequest } from '@playwright/test'
import { baseURL, iniciarSesion } from './sesion'

type Evento = { tipo: string; enMs: number }
type MetricasPagina = {
  fuentes: EventSource[]
  aperturas: number
  cierres: number
  errores: number
  eventos: Evento[]
  cerrarTodo: () => void
}
declare global {
  interface Window {
    __qaSesionRecovery?: MetricasPagina
  }
}

type InfoAlta = {
  estadoHttp: number
  codigoSeguro: string | null
  csrfPresente: boolean
  encabezadosIdempotencia: string[]
  clavesPayload: string[]
  inicioMs: number
  finMs: number
}

const pausa = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

async function instrumentar(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const datos: MetricasPagina = {
      fuentes: [],
      aperturas: 0,
      cierres: 0,
      errores: 0,
      eventos: [],
      cerrarTodo: () => {},
    }
    const yaCerradas = new WeakSet<EventSource>()
    const Original = window.EventSource
    class EventSourceMedido extends Original {
      constructor(url: string | URL, opciones?: EventSourceInit) {
        super(url, opciones)
        datos.aperturas += 1
        datos.fuentes.push(this)
        this.addEventListener('empleado.directorio.actualizado', () => {
          datos.eventos.push({ tipo: 'empleado.directorio.actualizado', enMs: Date.now() })
        })
        this.addEventListener('vision.ocupacion.actualizada', () => {
          datos.eventos.push({ tipo: 'vision.ocupacion.actualizada', enMs: Date.now() })
        })
        this.addEventListener('error', () => {
          datos.errores += 1
        })
      }
      close(): void {
        if (!yaCerradas.has(this)) {
          yaCerradas.add(this)
          datos.cierres += 1
        }
        super.close()
      }
    }
    window.EventSource = EventSourceMedido
    datos.cerrarTodo = () => {
      for (const fuente of datos.fuentes) fuente.close()
    }
    window.__qaSesionRecovery = datos
  })
}

async function telemetria(page: Page) {
  return page.evaluate(() => {
    const datos = window.__qaSesionRecovery
    if (!datos) return null
    return {
      aperturas: datos.aperturas,
      cierres: datos.cierres,
      errores: datos.errores,
      readyStates: datos.fuentes.map((fuente) => fuente.readyState),
      eventos: datos.eventos.map((evento) => ({ ...evento })),
    }
  })
}

function percentil(valores: number[], p: number): number | null {
  if (!valores.length) return null
  const ordenados = [...valores].sort((a, b) => a - b)
  return ordenados[Math.min(ordenados.length - 1, Math.ceil(p * ordenados.length) - 1)]
}

async function estadoPagina(page: Page, contexto: import('@playwright/test').BrowserContext, nombreEmpleado: string) {
  const dom = await page.evaluate(() => {
    const localStorageKeys = Array.from({ length: localStorage.length }, (_, indice) => localStorage.key(indice) || '')
    const sessionStorageKeys = Array.from({ length: sessionStorage.length }, (_, indice) => sessionStorage.key(indice) || '')
    return {
      ruta: location.pathname,
      cantidadLocalStorage: localStorage.length,
      cantidadSessionStorage: sessionStorage.length,
      hayClaveSesion: [...localStorageKeys, ...sessionStorageKeys].some((clave) => /session|sesion|auth/i.test(clave)),
    }
  })
  const listaEmpleadosVisible = await page.getByRole('region', { name: 'Lista de empleados' }).first().isVisible().catch(() => false)
  const nombreSinteticoVisible = await page.getByText(nombreEmpleado, { exact: true }).isVisible().catch(() => false)
  const formularioLoginVisible = await page.getByLabel('Correo electrónico').isVisible().catch(() => false)
  const cookies = await contexto.cookies(baseURL)
  const cookiesPrivadas = cookies.map((cookie) => ({ nombre: cookie.name, httpOnly: cookie.httpOnly }))
  return { ...dom, listaEmpleadosVisible, nombreSinteticoVisible, formularioLoginVisible, cookiesPrivadas }
}

async function esperarMarca(nombre: string, tiempoMaximoMs: number): Promise<boolean> {
  const limite = Date.now() + tiempoMaximoMs
  while (Date.now() < limite) {
    try {
      await access('/results/' + nombre)
      return true
    } catch {
      await pausa(100)
    }
  }
  return false
}

async function escribirMarca(nombre: string, contenido: unknown): Promise<void> {
  await writeFile('/results/' + nombre, JSON.stringify(contenido), { mode: 0o600 })
}

async function crearEmpleadoDesdeUI(page: Page): Promise<{ nombreSintetico: string; info: InfoAlta }> {
  const nombreSintetico = 'QA Cierre ' + randomUUID().slice(0, 8)
  await page.getByRole('button', { name: 'Agregar empleado', exact: true }).first().click()
  const dialogo = page.getByRole('dialog', { name: 'Agregar empleado' })
  await expect(dialogo).toBeVisible()
  await dialogo.getByLabel('Nombres').fill(nombreSintetico)
  await dialogo.getByLabel('Primer apellido').fill('Sintetico')
  await dialogo.getByLabel('Segundo apellido (opcional)').fill('Cierre')
  const solicitudPromise = page.waitForRequest((solicitud) =>
    solicitud.method() === 'POST' && new URL(solicitud.url()).pathname === '/api/v1/empleados',
  )
  const respuestaPromise = page.waitForResponse((respuesta) =>
    respuesta.request().method() === 'POST' && new URL(respuesta.url()).pathname === '/api/v1/empleados',
  )
  const inicioMs = Date.now()
  await dialogo.getByRole('button', { name: 'Agregar', exact: true }).click()
  const [solicitud, respuesta] = await Promise.all([solicitudPromise, respuestaPromise])
  const finMs = Date.now()
  const encabezados = solicitud.headers()
  const cabecerasIdempotencia = Object.keys(encabezados).filter((clave) => /idempot/i.test(clave)).sort()
  let clavesPayload: string[] = []
  try {
    clavesPayload = Object.keys(JSON.parse(solicitud.postData() || '{}')).sort()
  } catch {
    clavesPayload = []
  }
  let codigoSeguro: string | null = null
  try {
    const cuerpo = await respuesta.json()
    const codigo = cuerpo && typeof cuerpo === 'object' ? (cuerpo as Record<string, unknown>).codigo : null
    if (typeof codigo === 'string' && /^[A-Z0-9_]{1,64}$/.test(codigo)) codigoSeguro = codigo
  } catch {
    codigoSeguro = null
  }
  return {
    nombreSintetico,
    info: {
      estadoHttp: respuesta.status(),
      codigoSeguro,
      csrfPresente: Boolean(encabezados['x-csrf-token']),
      encabezadosIdempotencia: cabecerasIdempotencia,
      clavesPayload,
      inicioMs,
      finMs,
    },
  }
}

test('perder sesión por restart limpia el panel y una sesión nueva recupera SSE', async ({ browser }) => {
  test.setTimeout(180_000)
  const contexto = await browser.newContext()
  const page = await contexto.newPage()
  await instrumentar(page)
  const navegaciones: string[] = []
  const sesionesHttp: number[] = []
  const respuestasEmpleados: number[] = []
  page.on('framenavigated', (frame) => {
    if (frame === page.mainFrame()) {
      try {
        navegaciones.push(new URL(frame.url()).pathname)
      } catch {
        // Ignora navegaciones no HTTP.
      }
    }
  })
  page.on('response', (respuesta) => {
    const ruta = new URL(respuesta.url()).pathname
    if (ruta === '/api/v1/sesion') sesionesHttp.push(respuesta.status())
    if (ruta === '/api/v1/empleados') respuestasEmpleados.push(respuesta.status())
  })

  try {
    await iniciarSesion(page)
    await page.goto(baseURL + '/admin/empleados')
    await expect(page.getByRole('region', { name: 'Lista de empleados' }).first()).toBeVisible()
    await expect.poll(async () => (await telemetria(page))?.readyStates.includes(1) ?? false).toBe(true)

    const alta = await crearEmpleadoDesdeUI(page)
    await expect.poll(async () => (await telemetria(page))?.eventos.length ?? 0).toBeGreaterThan(0)
    const eventosAntesRestart = (await telemetria(page))?.eventos.filter(
      (evento) => evento.tipo === 'empleado.directorio.actualizado',
    ) || []
    const latenciasAltaSseMs = eventosAntesRestart.map((evento) => evento.enMs - alta.info.inicioMs)
    const preRestart = {
      pagina: await estadoPagina(page, contexto, alta.nombreSintetico),
      eventosEmpleado: eventosAntesRestart.length,
      altaUI: alta.info,
      latenciaAltaASseSinRafagaMs: {
        muestras: latenciasAltaSseMs.length,
        p50: percentil(latenciasAltaSseMs, 0.5),
        p95: percentil(latenciasAltaSseMs, 0.95),
        maximo: latenciasAltaSseMs.length ? Math.max(...latenciasAltaSseMs) : null,
      },
    }
    await escribirMarca('session2-ready-open.json', preRestart)

    if (!(await esperarMarca('session2-api-restarted.json', 45_000)))
      throw new Error('Timeout esperando restart API QA.')
    const respuestaReload = await page.reload({ waitUntil: 'domcontentloaded', timeout: 20_000 }).catch(() => null)
    const limiteRuta = Date.now() + 15_000
    while (Date.now() < limiteRuta && new URL(page.url()).pathname !== '/panel') await pausa(100)
    const postRestart = {
      reloadHttp: respuestaReload?.status() ?? null,
      pagina: await estadoPagina(page, contexto, alta.nombreSintetico),
      telemetria: await telemetria(page),
      navegaciones,
      respuestasSesion: sesionesHttp,
      respuestasEmpleados: respuestasEmpleados,
    }
    await escribirMarca('session2-after-restart.json', postRestart)

    await iniciarSesion(page)
    await page.goto(baseURL + '/admin')
    await expect(page.getByRole('region', { name: 'Ocupación física' })).toBeVisible()
    const limiteSse = Date.now() + 15_000
    let nuevaSse = false
    while (Date.now() < limiteSse) {
      const datos = await telemetria(page)
      nuevaSse = Boolean(datos?.readyStates.some((estado) => estado === 1))
      if (nuevaSse) break
      await pausa(100)
    }
    const recuperacionSesionNueva = {
      pagina: await estadoPagina(page, contexto, alta.nombreSintetico),
      telemetria: await telemetria(page),
      nuevaSesionHttp: sesionesHttp,
      sseDisponible: nuevaSse,
    }
    await escribirMarca('session2-new-login-sse.json', recuperacionSesionNueva)
  } finally {
    await contexto.close()
  }
})
