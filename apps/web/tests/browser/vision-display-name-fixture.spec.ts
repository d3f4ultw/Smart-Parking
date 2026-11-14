import { spawn, type ChildProcess } from 'node:child_process'
import { createServer, type Server, type ServerResponse } from 'node:http'
import { setTimeout as esperar } from 'node:timers/promises'
import { expect, test, type Page } from '@playwright/test'

type Cajon = {
  cajonId: string
  etiqueta: string
  displayName?: string | null
  estado: 'LIBRE' | 'OCUPADO' | 'NO_VERIFICABLE'
  ultimoEstadoConfirmado: 'LIBRE' | 'OCUPADO' | null
  observadoEn: string | null
}

type Guardado = { ruta: string; csrf: string | undefined; cookie: string; displayName: unknown }

const csrfSintetico = 'csrf-solo-fixture'
const cookieDueno = 'JSESSIONID=vision-ui-fixture-dueno'
const cookieOperador = 'JSESSIONID=vision-ui-fixture-operador'
let cajones: Cajon[] = []
let guardados: Guardado[] = []
let lecturas: number[] = []
let lecturasCapacidad = 0
let fallarGuardado = false
let fallarLectura = false
let fallarSesion = false
let correoSesion: string | null = null
let denegarVision = false
let fallarCapacidad = false
let vigenciaRestante = 120_000
let pausaLectura: Promise<void> | null = null
let liberarLectura: (() => void) | undefined
let pausaCapacidad: Promise<void> | null = null
let liberarCapacidad: (() => void) | undefined
let pausaGuardado: Promise<void> | null = null
let liberarGuardado: (() => void) | undefined
const conexionesSse = new Set<ServerResponse>()
let aperturasSse = 0
let cursoresSse: (string | null)[] = []
let secuenciaSse = 1
let api: Server | undefined
let nitro: ChildProcess | undefined
let base = ''
let salidaNitro = ''

function responder(respuesta: ServerResponse, estado: number, datos: unknown, extra = {}) {
  respuesta.writeHead(estado, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store, private',
    ...extra,
  })
  respuesta.end(JSON.stringify(datos))
}

function crearCajones(cantidad: number): Cajon[] {
  return Array.from({ length: cantidad }, (_, indice) => {
    const numero = indice + 1
    const confirmado = numero % 2 ? 'LIBRE' : 'OCUPADO'
    return {
      cajonId: `00000000-0000-4000-8000-${String(numero).padStart(12, '0')}`,
      etiqueta: `C${String(numero).padStart(2, '0')}`,
      ...(numero === 1 ? {} : { displayName: numero === 2 ? 'Zona techada' : numero === 3 ? '  ' : null }),
      estado: numero === 3 ? 'NO_VERIFICABLE' : confirmado,
      ultimoEstadoConfirmado: confirmado,
      observadoEn: '2026-11-02T12:00:00Z',
    }
  })
}

async function puertoLibre(): Promise<number> {
  const servidor = createServer()
  await new Promise<void>((resolver) => servidor.listen(0, '127.0.0.1', resolver))
  const direccion = servidor.address()
  if (!direccion || typeof direccion === 'string') throw new Error('No hay puerto disponible.')
  const puerto = direccion.port
  await new Promise<void>((resolver, rechazar) => servidor.close((error) => error ? rechazar(error) : resolver()))
  return puerto
}

function region(page: Page) {
  return page.getByRole('region', { name: 'Ocupación física' })
}

async function entrar(page: Page, rol: 'DUENO' | 'OPERADOR' = 'DUENO') {
  const valor = rol === 'DUENO' ? 'vision-ui-fixture-dueno' : 'vision-ui-fixture-operador'
  await page.context().addCookies([{ name: 'JSESSIONID', value: valor, url: base }])
  const ruta = rol === 'DUENO' ? '/admin/vision' : '/operador/monitoreo'
  const respuesta = await page.goto(`${base}${ruta}`)
  expect(respuesta?.status()).toBe(200)
  await expect(region(page)).toBeVisible()
  return respuesta!
}

function emitirVision() {
  secuenciaSse++
  for (const conexion of conexionesSse) {
    conexion.write(`id: aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa:${secuenciaSse}\nevent: vision.ocupacion.actualizada\ndata: {}\n\n`)
  }
}

test.describe.serial('Dashboard Vision con API sintética aislada', () => {
  test.beforeAll(async () => {
    const entrada = process.env.VISION_UI_NITRO_ENTRY
    if (process.env.VISION_UI_FIXTURE_MODE !== 'true' || !entrada?.startsWith('/')) {
      throw new Error('Se requiere una build Nitro aislada y el modo explícito de fixture.')
    }
    api = createServer(async (solicitud, respuesta) => {
      const url = new URL(solicitud.url ?? '/', 'http://127.0.0.1')
      const ruta = url.pathname
      const cookie = solicitud.headers.cookie ?? ''
      const partesCookie = cookie.split(';').map((parte) => parte.trim())
      const rol = partesCookie.includes(cookieDueno)
        ? 'DUENO' : partesCookie.includes(cookieOperador) ? 'OPERADOR' : null
      if (ruta === '/api/v1/csrf' && solicitud.method === 'GET') {
        responder(respuesta, 200, { token: csrfSintetico })
        return
      }
      if (ruta === '/api/v1/sesion' && solicitud.method === 'GET') {
        if (fallarSesion) {
          responder(respuesta, 503, { codigo: 'SESION_NO_DISPONIBLE' })
          return
        }
        responder(respuesta, 200, rol
          ? { autenticada: true, correo: correoSesion ?? `${rol.toLowerCase()}@example.invalid`, rol }
          : { autenticada: false })
        return
      }
      if (!rol) {
        responder(respuesta, 401, { codigo: 'SESION_NO_VIGENTE' })
        return
      }
      if (ruta === '/api/v1/panel' && solicitud.method === 'GET') {
        responder(respuesta, 200, {
          propietario: { nombres: 'Dueño', primerApellido: 'Sintético', correo: 'dueno@example.invalid' },
          estacionamiento: {
            nombre: 'Estacionamiento sintético',
            tipo: 'PRIVADO',
            horario: { modo: 'CONTINUO_24_7', zonaHoraria: 'UTC', horaApertura: null, horaCierre: null },
          },
        })
        return
      }
      if (ruta === '/api/v1/vision/cajones' && solicitud.method === 'GET') {
        lecturas.push(cajones.length)
        const espera = pausaLectura
        pausaLectura = null
        if (espera) await espera
        if (fallarLectura) {
          responder(respuesta, 503, { codigo: 'VISION_NO_DISPONIBLE' })
          return
        }
        if (denegarVision) {
          responder(respuesta, 403, { codigo: 'PERMISO_INSUFICIENTE' })
          return
        }
        responder(respuesta, 200, cajones, {
          'x-eventos-cursor': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa:1',
          'x-vision-vigencia-restante-ms': String(vigenciaRestante),
        })
        return
      }
      if (ruta === '/api/v1/accesos/capacidad' && solicitud.method === 'GET') {
        lecturasCapacidad++
        const espera = pausaCapacidad
        pausaCapacidad = null
        if (espera) await espera
        if (fallarCapacidad) {
          responder(respuesta, 503, { codigo: 'SERVICIO_NO_DISPONIBLE' })
          return
        }
        responder(respuesta, 200, {
          capacidadTotal: 12,
          vehiculosDentro: 4,
          capacidadDisponible: 8,
          cursorEventos: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa:1',
        })
        return
      }
      if (ruta === '/api/v1/eventos/administracion' && solicitud.method === 'GET') {
        respuesta.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-store' })
        aperturasSse++
        cursoresSse.push(url.searchParams.get('despues'))
        conexionesSse.add(respuesta)
        respuesta.on('close', () => conexionesSse.delete(respuesta))
        respuesta.write(': fixture lista\n\n')
        return
      }
      const coincidencia = /^\/api\/v1\/vision\/cajones\/([0-9a-f-]{36})\/display-name$/.exec(ruta)
      if (coincidencia && solicitud.method === 'PUT') {
        const partes: Buffer[] = []
        for await (const parte of solicitud) partes.push(Buffer.from(parte))
        const cuerpo = JSON.parse(Buffer.concat(partes).toString('utf8')) as { displayName?: unknown }
        guardados.push({ ruta, csrf: solicitud.headers['x-csrf-token'], cookie, displayName: cuerpo.displayName })
        const espera = pausaGuardado
        pausaGuardado = null
        if (espera) await espera
        if (solicitud.headers['x-csrf-token'] !== csrfSintetico) {
          responder(respuesta, 403, { codigo: 'CSRF_RECHAZADO' })
          return
        }
        if (fallarGuardado) {
          fallarGuardado = false
          responder(respuesta, 503, { codigo: 'VISION_NO_DISPONIBLE' })
          return
        }
        const cajon = cajones.find((item) => item.cajonId === coincidencia[1])
        if (!cajon || (cuerpo.displayName !== null && typeof cuerpo.displayName !== 'string')) {
          responder(respuesta, 409, { codigo: 'VISION_CONFLICTO' })
          return
        }
        cajon.displayName = typeof cuerpo.displayName === 'string' && cuerpo.displayName.trim()
          ? cuerpo.displayName : null
        respuesta.writeHead(204, { 'cache-control': 'no-store, private' })
        respuesta.end()
        emitirVision()
        return
      }
      responder(respuesta, 404, { codigo: 'RUTA_FUERA_DE_FIXTURE' })
    })
    await new Promise<void>((resolver) => api!.listen(0, '127.0.0.1', resolver))
    const direccion = api.address()
    if (!direccion || typeof direccion === 'string') throw new Error('La API sintética no inició.')
    const puertoNitro = await puertoLibre()
    base = `http://127.0.0.1:${puertoNitro}`
    nitro = spawn(process.execPath, [entrada], {
      env: {
        PATH: process.env.PATH,
        NODE_ENV: 'production',
        NUXT_API_INTERNAL_BASE: `http://127.0.0.1:${direccion.port}`,
        NITRO_HOST: '127.0.0.1',
        NITRO_PORT: String(puertoNitro),
        HOST: '127.0.0.1',
        PORT: String(puertoNitro),
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    nitro.stdout?.on('data', (parte) => { salidaNitro += String(parte).slice(0, 1000) })
    nitro.stderr?.on('data', (parte) => { salidaNitro += String(parte).slice(0, 1000) })
    for (let intento = 0; intento < 100; intento++) {
      if (nitro.exitCode !== null) break
      try {
        const respuesta = await fetch(`${base}/api/v1/csrf`)
        if (respuesta.status === 200) return
      } catch {}
      await esperar(100)
    }
    throw new Error(`Nitro aislado no inició: ${salidaNitro.slice(-2000)}`)
  })

  test.afterAll(async () => {
    if (nitro && nitro.exitCode === null) {
      nitro.kill('SIGTERM')
      for (let intento = 0; intento < 50 && nitro.exitCode === null; intento++) await esperar(100)
      if (nitro.exitCode === null) nitro.kill('SIGKILL')
    }
    if (api) {
      api.closeAllConnections()
      await new Promise<void>((resolver) => api!.close(() => resolver()))
    }
  })

  test.beforeEach(async ({ page }) => {
    cajones = []
    guardados = []
    lecturas = []
    lecturasCapacidad = 0
    fallarGuardado = false
    fallarLectura = false
    fallarSesion = false
    correoSesion = null
    denegarVision = false
    fallarCapacidad = false
    vigenciaRestante = 120_000
    pausaLectura = null
    pausaCapacidad = null
    pausaGuardado = null
    liberarLectura = undefined
    liberarCapacidad = undefined
    liberarGuardado = undefined
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => true })
    })
  })

  test.afterEach(() => {
    liberarLectura?.()
    liberarCapacidad?.()
    liberarGuardado?.()
  })

  test('renderiza todos los cajones activos y sus nombres predeterminados', async ({ page }) => {
    const errores: string[] = []
    page.on('pageerror', (error) => errores.push(error.message))
    page.on('console', (mensaje) => {
      if (/hydration|mismatch/i.test(mensaje.text())) errores.push('hidratación')
    })
    for (const cantidad of [0, 3, 8, 9, 10]) {
      cajones = crearCajones(cantidad)
      const lecturasAnteriores = lecturas.length
      await entrar(page)
      await expect.poll(() => lecturas.slice(lecturasAnteriores)).toContain(cantidad)
      const tarjetas = region(page).locator('li.cajon-vision')
      await expect(tarjetas).toHaveCount(cantidad)
      const indicador = region(page).locator('.indicador-ocupacion')
        .filter({ has: page.getByText('Cajones registrados', { exact: true }) }).locator('dd')
      await expect(indicador).toHaveText(String(cantidad))
      await expect(region(page).locator('.aviso-ocupacion')).toHaveCount(0)
      if (cantidad === 0) {
        await expect(region(page).locator('.vacio-ocupacion')).toBeVisible()
      } else {
        await expect(region(page).getByRole('heading', { name: 'Cajón 1', exact: true })).toBeVisible()
        await expect(region(page).getByRole('heading', { name: 'Zona techada', exact: true })).toBeVisible()
        await expect(region(page).getByRole('heading', { name: 'Cajón 3', exact: true })).toBeVisible()
        if (cantidad >= 9) {
          await expect(region(page).getByRole('heading', { name: 'Cajón 9', exact: true })).toBeVisible()
        }
        if (cantidad === 10) {
          await expect(region(page).getByRole('heading', { name: 'Cajón 10', exact: true })).toBeVisible()
        }
      }
    }
    expect(errores).toEqual([])
  })

  test('guarda y restablece inline, conserva identidad y muestra el fallo en la tarjeta', async ({ page }) => {
    cajones = crearCajones(3)
    guardados = []
    fallarGuardado = false
    const original = { ...cajones[0], displayName: null }
    await entrar(page)
    let tarjeta = region(page).locator('li.cajon-vision').filter({
      has: page.getByRole('heading', { name: 'Cajón 1', exact: true }),
    })
    const cambiar = tarjeta.getByRole('button', { name: 'Cambiar nombre de Cajón 1' })
    await cambiar.focus()
    await page.keyboard.press('Enter')
    await expect(tarjeta.getByLabel('Nombre visible')).toBeFocused()
    await tarjeta.getByLabel('Nombre visible').fill('Entrada principal')
    await tarjeta.getByRole('button', { name: 'Guardar' }).click()
    await expect(region(page).getByRole('heading', { name: 'Entrada principal', exact: true })).toBeVisible()
    await expect(region(page).getByRole('button', { name: 'Cambiar nombre de Entrada principal' })).toBeFocused()
    expect(guardados).toHaveLength(1)
    expect(guardados[0]).toEqual({
      ruta: `/api/v1/vision/cajones/${original.cajonId}/display-name`,
      csrf: csrfSintetico,
      cookie: cookieDueno,
      displayName: 'Entrada principal',
    })
    expect({ ...cajones[0], displayName: null }).toEqual(original)
    await page.reload()
    await expect(region(page).getByRole('heading', { name: 'Entrada principal', exact: true })).toBeVisible()
    tarjeta = region(page).locator('li.cajon-vision').filter({
      has: page.getByRole('heading', { name: 'Entrada principal', exact: true }),
    })
    await tarjeta.getByRole('button', { name: 'Cambiar nombre de Entrada principal' }).click()
    await tarjeta.getByLabel('Nombre visible').fill('   ')
    await tarjeta.getByRole('button', { name: 'Guardar' }).click()
    await expect(region(page).getByRole('heading', { name: 'Cajón 1', exact: true })).toBeVisible()
    expect(cajones[0]?.displayName).toBeNull()
    expect({ ...cajones[0], displayName: null }).toEqual(original)
    await page.reload()
    tarjeta = region(page).locator('li.cajon-vision').filter({
      has: page.getByRole('heading', { name: 'Cajón 1', exact: true }),
    })
    fallarGuardado = true
    await tarjeta.getByRole('button', { name: 'Cambiar nombre de Cajón 1' }).click()
    await tarjeta.getByLabel('Nombre visible').fill('Nombre no guardado')
    await tarjeta.getByRole('button', { name: 'Guardar' }).click()
    await expect(tarjeta.getByRole('alert')).toContainText('No pudimos confirmar el guardado')
    await expect(tarjeta.getByLabel('Nombre visible')).toHaveValue('Nombre no guardado')
    await expect(tarjeta.getByRole('button', { name: 'Guardar' })).toBeEnabled()
    expect(cajones[0]?.displayName).toBeNull()
  })

  test('cancelar devuelve el foco y descarta el borrador sin guardar', async ({ page }) => {
    cajones = crearCajones(3)
    await entrar(page)
    const tarjeta = region(page).locator('li.cajon-vision').filter({
      has: page.getByRole('heading', { name: 'Cajón 1', exact: true }),
    })
    const cambiar = tarjeta.getByRole('button', { name: 'Cambiar nombre de Cajón 1' })
    await cambiar.click()
    await tarjeta.getByLabel('Nombre visible').fill('Borrador descartado')
    await tarjeta.getByRole('button', { name: 'Cancelar' }).click()
    await expect(cambiar).toBeFocused()
    await expect(tarjeta.getByLabel('Nombre visible')).toHaveCount(0)
    expect(guardados).toHaveLength(0)
    await cambiar.click()
    await expect(tarjeta.getByLabel('Nombre visible')).not.toHaveValue('Borrador descartado')
  })

  test('sincroniza nombres entre propietario y operador sin perder datos ni borradores', async ({ page, browser }) => {
    cajones = crearCajones(3)
    const otraSesion = await browser.newContext()
    try {
      // Dos usuarios en dispositivos distintos mantienen ambas vistas visibles.
      const mantenerVisible = () => {
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
        Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => true })
      }
      await page.context().addInitScript(mantenerVisible)
      await otraSesion.addInitScript(mantenerVisible)
      const otraPagina = await otraSesion.newPage()
      const conexionesAntes = aperturasSse
      await entrar(page, 'DUENO')
      await entrar(otraPagina, 'OPERADOR')
      await expect.poll(() => aperturasSse).toBeGreaterThanOrEqual(conexionesAntes + 2)
      let navegaciones = 0
      otraPagina.on('framenavigated', (marco) => {
        if (marco === otraPagina.mainFrame()) navegaciones++
      })

      const tarjetaOperador = region(otraPagina).locator('li.cajon-vision').filter({
        has: otraPagina.getByRole('heading', { name: 'Zona techada', exact: true }),
      })
      await tarjetaOperador.getByRole('button', { name: 'Cambiar nombre de Zona techada' }).click()
      const borrador = tarjetaOperador.getByLabel('Nombre visible')
      await borrador.fill('Borrador del operador')

      const tarjetaDueno = region(page).locator('li.cajon-vision').first()
      await tarjetaDueno.getByRole('button', { name: 'Cambiar nombre de Cajón 1' }).click()
      await tarjetaDueno.getByLabel('Nombre visible').fill('Entrada compartida')
      await tarjetaDueno.getByRole('button', { name: 'Guardar' }).click()
      await expect(region(otraPagina).getByRole('heading', { name: 'Entrada compartida' })).toBeVisible({ timeout: 5_000 })
      await expect(region(otraPagina).locator('li.cajon-vision')).toHaveCount(3)
      await expect(borrador).toHaveValue('Borrador del operador')
      await expect(borrador).toBeFocused()
      await expect(region(otraPagina)).toContainText('No verificable')
      expect(navegaciones).toBe(0)

      await tarjetaOperador.getByRole('button', { name: 'Guardar' }).click()
      await expect(region(page).getByRole('heading', { name: 'Borrador del operador' })).toBeVisible({ timeout: 5_000 })
      expect(guardados).toHaveLength(2)
      expect(guardados[0]?.cookie).toBe(cookieDueno)
      expect(guardados[1]?.cookie).toBe(cookieOperador)
    } finally {
      await otraSesion.close()
    }
  })

  test('mantiene la vista y el borrador durante refrescos y avisos SSE', async ({ page }) => {
    cajones = crearCajones(3)
    const aperturasPrevias = aperturasSse
    await entrar(page)
    await expect.poll(() => aperturasSse).toBeGreaterThan(aperturasPrevias)
    const tarjeta = region(page).locator('li.cajon-vision').filter({
      has: page.getByRole('heading', { name: 'Cajón 1', exact: true }),
    })
    const nodo = await tarjeta.elementHandle()
    expect(nodo).not.toBeNull()
    const actualizar = region(page).getByRole('button', { name: 'Actualizar' })
    const capacidad = page.getByRole('region', { name: 'Capacidad del estacionamiento' })
    const actualizarCapacidad = capacidad.getByRole('button', { name: 'Actualizar' })
    const lecturasPrevias = lecturas.length
    pausaLectura = new Promise<void>((resolver) => { liberarLectura = resolver })
    await actualizar.click()
    await expect.poll(() => lecturas.length).toBeGreaterThan(lecturasPrevias)
    await expect(tarjeta).toBeVisible()
    expect(await nodo!.evaluate((elemento) => elemento.isConnected)).toBe(true)
    await expect(tarjeta.locator('.estado-cajon')).toHaveText('Libre')
    liberarLectura?.()
    await expect(actualizar).toBeEnabled()

    await tarjeta.getByRole('button', { name: 'Cambiar nombre de Cajón 1' }).click()
    const campo = tarjeta.getByLabel('Nombre visible')
    await campo.fill('Borrador durante SSE')
    cajones[0]!.estado = 'OCUPADO'
    cajones[0]!.ultimoEstadoConfirmado = 'OCUPADO'
    const lecturasAntesDeSse = lecturas.length
    const capacidadAntesDeSse = lecturasCapacidad
    pausaLectura = new Promise<void>((resolver) => { liberarLectura = resolver })
    pausaCapacidad = new Promise<void>((resolver) => { liberarCapacidad = resolver })
    emitirVision()
    await expect.poll(() => lecturas.length).toBeGreaterThan(lecturasAntesDeSse)
    await expect.poll(() => lecturasCapacidad).toBeGreaterThan(capacidadAntesDeSse)
    await expect(actualizar).toBeVisible()
    await expect(actualizar).toBeEnabled()
    await expect(actualizar).toHaveText('Actualizar')
    await expect(actualizarCapacidad).toBeVisible()
    await expect(actualizarCapacidad).toBeEnabled()
    await expect(actualizarCapacidad).toHaveText('Actualizar')
    await expect(capacidad).toContainText('8')
    await expect(tarjeta).toBeVisible()
    expect(await nodo!.evaluate((elemento) => elemento.isConnected)).toBe(true)
    await expect(campo).toHaveValue('Borrador durante SSE')
    await expect(campo).toBeFocused()
    liberarLectura?.()
    liberarCapacidad?.()
    await expect(tarjeta.locator('.estado-cajon')).toHaveText('Ocupado')
    await expect(campo).toHaveValue('Borrador durante SSE')
    await nodo!.dispose()
  })

  test('conserva los cajones registrados mientras falla temporalmente la sesión', async ({ page }) => {
    cajones = crearCajones(3).map((cajon) => ({ ...cajon, estado: 'NO_VERIFICABLE' }))
    await entrar(page, 'OPERADOR')
    const tarjetas = region(page).locator('li.cajon-vision')
    const registrados = region(page).locator('.indicador-ocupacion')
      .filter({ has: page.getByText('Cajones registrados', { exact: true }) }).locator('dd')
    await expect(tarjetas).toHaveCount(3)
    await expect(registrados).toHaveText('3')
    await tarjetas.first().getByRole('button', { name: 'Cambiar nombre de Cajón 1' }).click()
    const borrador = tarjetas.first().getByLabel('Nombre visible')
    await borrador.fill('Nombre sin guardar')
    await expect.poll(() => conexionesSse.size).toBeGreaterThan(0)
    fallarSesion = true
    for (const conexion of conexionesSse) conexion.end()
    await expect(region(page)).toContainText('No pudimos confirmar tu acceso', { timeout: 10_000 })
    await expect(tarjetas).toHaveCount(3)
    await expect(registrados).toHaveText('3')
    await expect(tarjetas.first().locator('.estado-cajon')).toHaveText('No verificable')
    await expect(borrador).toHaveValue('Nombre sin guardar')
    fallarSesion = false
    pausaLectura = new Promise<void>((resolver) => { liberarLectura = resolver })
    await region(page).getByRole('button', { name: 'Reintentar' }).click()
    await expect.poll(() => pausaLectura === null).toBe(true)
    await expect(tarjetas).toHaveCount(3)
    await expect(borrador).toHaveValue('Nombre sin guardar')
    liberarLectura?.()
    await expect(registrados).toHaveText('3')
  })

  test('conserva los cajones registrados al perder y recuperar la conexión', async ({ page }) => {
    cajones = crearCajones(3).map((cajon) => ({ ...cajon, estado: 'NO_VERIFICABLE' }))
    await entrar(page, 'OPERADOR')
    const tarjetas = region(page).locator('li.cajon-vision')
    const registrados = region(page).locator('.indicador-ocupacion')
      .filter({ has: page.getByText('Cajones registrados', { exact: true }) }).locator('dd')
    await expect(tarjetas).toHaveCount(3)
    const anteriores = lecturas.length
    await page.evaluate(() => {
      Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => false })
      window.dispatchEvent(new Event('offline'))
    })
    await expect(region(page)).toContainText('Sin conexión.')
    await expect(tarjetas).toHaveCount(3)
    await expect(registrados).toHaveText('3')
    await expect(tarjetas.first().locator('.estado-cajon')).toHaveText('No verificable')
    await page.evaluate(() => {
      Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => true })
      window.dispatchEvent(new Event('online'))
    })
    await expect.poll(() => lecturas.length).toBeGreaterThan(anteriores)
    await expect(tarjetas).toHaveCount(3)
    await expect(registrados).toHaveText('3')
  })

  test('actualiza los nombres sin perder los cajones cuando el SSE está interrumpido', async ({ page }) => {
    cajones = crearCajones(3).map((cajon) => ({ ...cajon, estado: 'NO_VERIFICABLE' }))
    await entrar(page, 'OPERADOR')
    await expect(region(page).locator('li.cajon-vision')).toHaveCount(3)
    await expect.poll(() => conexionesSse.size).toBeGreaterThan(0)
    let liberarReconexion: () => void = () => {}
    const espera = new Promise<void>((resolver) => { liberarReconexion = resolver })
    await page.route('**/api/v1/eventos/administracion?*', async (ruta) => {
      await espera
      await ruta.abort().catch(() => {})
    })
    try {
      const anteriores = lecturas.length
      for (const conexion of conexionesSse) conexion.end()
      await expect(region(page)).toContainText('La conexión de actualizaciones se interrumpió')
      await expect.poll(() => lecturas.length).toBeGreaterThan(anteriores)
      await expect(region(page).locator('li.cajon-vision')).toHaveCount(3)
      const registrados = region(page).locator('.indicador-ocupacion')
        .filter({ has: page.getByText('Cajones registrados', { exact: true }) }).locator('dd')
      await expect(registrados).toHaveText('3')
      cajones[0]!.displayName = 'Nombre actualizado sin SSE'
      await expect(region(page).getByRole('heading', { name: 'Nombre actualizado sin SSE' }))
        .toBeVisible({ timeout: 8_000 })
    } finally {
      liberarReconexion()
      await page.unroute('**/api/v1/eventos/administracion?*')
    }
  })

  test('no conserva los cajones de otra identidad al recuperar la sesión', async ({ page }) => {
    cajones = crearCajones(3)
    await entrar(page, 'OPERADOR')
    await expect(region(page).getByRole('heading', { name: 'Cajón 1' })).toBeVisible()
    await expect.poll(() => conexionesSse.size).toBeGreaterThan(0)
    fallarSesion = true
    for (const conexion of conexionesSse) conexion.end()
    await expect(region(page)).toContainText('No pudimos confirmar tu acceso', { timeout: 10_000 })
    fallarSesion = false
    correoSesion = 'otra-persona@example.invalid'
    cajones[0]!.displayName = 'Datos de la nueva sesión'
    pausaLectura = new Promise<void>((resolver) => { liberarLectura = resolver })
    await page.evaluate(() => {
      history.pushState(history.state, '', `${location.pathname}?prueba=otra-sesion`)
      window.dispatchEvent(new PopStateEvent('popstate', { state: history.state }))
    })
    await expect.poll(() => pausaLectura === null).toBe(true)
    await expect(region(page).locator('li.cajon-vision')).toHaveCount(0)
    liberarLectura?.()
    await expect(region(page).getByRole('heading', { name: 'Datos de la nueva sesión' })).toBeVisible()
  })

  test('una sesión cerrada deja de mostrar los cajones conservados', async ({ page }) => {
    cajones = crearCajones(3)
    await entrar(page, 'OPERADOR')
    await expect(region(page).locator('li.cajon-vision')).toHaveCount(3)
    await expect.poll(() => conexionesSse.size).toBeGreaterThan(0)
    fallarSesion = true
    for (const conexion of conexionesSse) conexion.end()
    await expect(region(page)).toContainText('No pudimos confirmar tu acceso', { timeout: 10_000 })
    await expect(region(page).locator('li.cajon-vision')).toHaveCount(3)
    fallarSesion = false
    await page.context().clearCookies()
    await page.evaluate(() => {
      history.pushState(history.state, '', `${location.pathname}?prueba=sesion-cerrada`)
      window.dispatchEvent(new PopStateEvent('popstate', { state: history.state }))
    })
    await expect(page).toHaveURL(/\/panel$/, { timeout: 10_000 })
    await expect(region(page)).toHaveCount(0)
  })

  test('una denegación de acceso elimina los cajones visibles', async ({ page }) => {
    cajones = crearCajones(3)
    await entrar(page, 'OPERADOR')
    await expect(region(page).locator('li.cajon-vision')).toHaveCount(3)
    denegarVision = true
    await region(page).getByRole('button', { name: 'Actualizar' }).click()
    await expect(region(page)).toContainText('No tienes acceso para consultar la ocupación.')
    await expect(region(page).locator('li.cajon-vision')).toHaveCount(0)
  })

  test('recupera Monitoreo después de una falla temporal al comprobar la sesión', async ({ page }) => {
    cajones = crearCajones(3)
    await entrar(page, 'OPERADOR')
    await expect(region(page).locator('li.cajon-vision')).toHaveCount(3)
    await expect.poll(() => conexionesSse.size).toBeGreaterThan(0)
    fallarSesion = true
    for (const conexion of conexionesSse) conexion.end()
    await expect(region(page)).toContainText('No pudimos confirmar tu acceso', { timeout: 10_000 })
    fallarSesion = false
    await region(page).getByRole('button', { name: 'Reintentar' }).click()
    await expect(region(page).locator('li.cajon-vision')).toHaveCount(3, { timeout: 15_000 })
    const lecturasAntes = lecturas.length
    await region(page).getByRole('button', { name: 'Actualizar' }).click()
    await expect.poll(() => lecturas.length).toBeGreaterThan(lecturasAntes)
  })

  for (const rol of ['DUENO', 'OPERADOR'] as const) {
    test(`recupera Monitoreo de ${rol} si otra navegación revalida la sesión interrumpida`, async ({ page }) => {
      cajones = crearCajones(3)
      await entrar(page, rol)
      await expect(region(page).locator('li.cajon-vision')).toHaveCount(3)
      await expect.poll(() => conexionesSse.size).toBeGreaterThan(0)
      fallarSesion = true
      for (const conexion of conexionesSse) conexion.end()
      await expect(region(page)).toContainText('No pudimos confirmar tu acceso', { timeout: 10_000 })
      fallarSesion = false
      await page.evaluate(() => {
        history.pushState(history.state, '', `${location.pathname}?prueba=recuperacion`)
        window.dispatchEvent(new PopStateEvent('popstate', { state: history.state }))
      })
      await expect(region(page).locator('li.cajon-vision')).toHaveCount(3, { timeout: 10_000 })
      const lecturasAntes = lecturas.length
      pausaLectura = new Promise<void>((resolver) => { liberarLectura = resolver })
      const actualizar = region(page).getByRole('button', { name: 'Actualizar' })
      await actualizar.click()
      await expect.poll(() => lecturas.length).toBeGreaterThan(lecturasAntes)
      await expect(region(page).locator('li.cajon-vision')).toHaveCount(3)
      liberarLectura?.()
      await expect(actualizar).toBeEnabled()
    })
  }

  test('distingue error inicial, recuperación y observaciones vencidas', async ({ page }) => {
    cajones = crearCajones(3)
    fallarLectura = true
    await entrar(page)
    await expect(region(page).getByRole('alert')).toBeVisible()
    await expect(region(page).locator('li.cajon-vision')).toHaveCount(0)
    fallarLectura = false
    await region(page).getByRole('button', { name: 'Reintentar' }).click()
    await expect(region(page).locator('li.cajon-vision')).toHaveCount(3)
    await expect(region(page).locator('.estado-cajon').first()).toHaveText('Libre')
    vigenciaRestante = 0
    await region(page).getByRole('button', { name: 'Actualizar' }).click()
    await expect(region(page).locator('.estado-cajon').first()).toHaveText('No verificable')
    await expect(region(page).locator('li.cajon-vision').first()).toContainText('Última confirmación: Libre')
    await expect(region(page)).toContainText('Los datos mostrados son históricos.')
    vigenciaRestante = 120_000
    await region(page).getByRole('button', { name: 'Reintentar' }).click()
    await expect(region(page).locator('.estado-cajon').first()).toHaveText('Libre')
  })

  test('capacidad no disponible muestra guiones y permite recuperar la lectura', async ({ page }) => {
    cajones = crearCajones(3)
    fallarCapacidad = true
    await entrar(page)
    const capacidad = page.getByRole('region', { name: 'Capacidad del estacionamiento' })
    const valor = capacidad.locator('dl > div').filter({
      has: page.getByText('Espacios disponibles estimados', { exact: true }),
    }).locator('dd')
    await expect(capacidad.getByRole('alert')).toBeVisible()
    await expect(valor).toHaveText('—')
    fallarCapacidad = false
    await capacidad.getByRole('button', { name: 'Actualizar' }).click()
    await expect(valor).toHaveText('8')
  })

  test('dos clics sincrónicos solicitan una sola actualización por panel', async ({ page }) => {
    cajones = crearCajones(3)
    await entrar(page)
    const capacidad = page.getByRole('region', { name: 'Capacidad del estacionamiento' })
    const actualizarVision = region(page).getByRole('button', { name: 'Actualizar' })
    const actualizarCapacidad = capacidad.getByRole('button', { name: 'Actualizar' })
    await expect(actualizarVision).toBeEnabled()
    await expect(actualizarCapacidad).toBeEnabled()
    const antesVision = lecturas.length
    const antesCapacidad = lecturasCapacidad
    pausaLectura = new Promise<void>((resolver) => { liberarLectura = resolver })
    pausaCapacidad = new Promise<void>((resolver) => { liberarCapacidad = resolver })
    await actualizarVision.evaluate((boton) => {
      const control = boton as HTMLButtonElement
      control.click()
      control.click()
    })
    await actualizarCapacidad.evaluate((boton) => {
      const control = boton as HTMLButtonElement
      control.click()
      control.click()
    })
    await expect.poll(() => lecturas.length).toBe(antesVision + 1)
    await expect.poll(() => lecturasCapacidad).toBe(antesCapacidad + 1)
    await expect(actualizarVision).toBeDisabled()
    await expect(actualizarCapacidad).toBeDisabled()
    expect(lecturas).toHaveLength(antesVision + 1)
    expect(lecturasCapacidad).toBe(antesCapacidad + 1)
    liberarLectura?.()
    liberarCapacidad?.()
    await expect(actualizarVision).toBeEnabled()
    await expect(actualizarCapacidad).toBeEnabled()
    expect(lecturas).toHaveLength(antesVision + 1)
    expect(lecturasCapacidad).toBe(antesCapacidad + 1)
  })

  test('evita envíos duplicados y mantiene los estados físicos independientes de RFID', async ({ page }) => {
    cajones = crearCajones(3)
    await entrar(page)
    const capacidad = page.getByRole('region', { name: 'Capacidad del estacionamiento' })
    await expect(capacidad).toContainText('Espacios disponibles estimados')
    await expect(capacidad).toContainText('8')
    await expect(capacidad).toContainText('4')
    await expect(capacidad).toContainText('12')
    const tarjetas = region(page).locator('li.cajon-vision')
    await expect(tarjetas.nth(0).locator('.estado-cajon')).toHaveText('Libre')
    await expect(tarjetas.nth(1).locator('.estado-cajon')).toHaveText('Ocupado')
    await expect(tarjetas.nth(2).locator('.estado-cajon')).toHaveText('No verificable')
    await expect(tarjetas.nth(2)).toContainText('Última confirmación: Libre')
    const fecha = region(page).locator('time[datetime="2026-11-02T12:00:00Z"]')
    await expect(fecha).toHaveCount(1)
    await expect(fecha).toContainText('UTC')

    const primera = tarjetas.nth(0)
    await primera.getByRole('button', { name: 'Cambiar nombre de Cajón 1' }).click()
    await primera.getByLabel('Nombre visible').fill('Acceso principal')
    pausaGuardado = new Promise<void>((resolver) => { liberarGuardado = resolver })
    const guardar = primera.getByRole('button', { name: 'Guardar' })
    await guardar.click()
    await expect.poll(() => guardados.length).toBe(1)
    await expect(guardar).toBeDisabled()
    await guardar.evaluate((boton) => (boton as HTMLButtonElement).click())
    expect(guardados).toHaveLength(1)
    liberarGuardado?.()
    await expect(region(page).getByRole('heading', { name: 'Acceso principal' })).toBeVisible()
    await expect(capacidad).toContainText('8')
  })

  test('propietario y operador ven Monitoreo y el operador puede editar', async ({ page }) => {
    cajones = crearCajones(3)
    for (const rol of ['DUENO', 'OPERADOR'] as const) {
      const errores: string[] = []
      const observar = (mensaje: { text(): string }) => {
        if (/hydration|mismatch/i.test(mensaje.text())) errores.push(mensaje.text())
      }
      page.on('console', observar)
      const respuesta = await entrar(page, rol)
      expect(await respuesta.text()).toContain('Ocupación física')
      await expect(page.getByRole('heading', { name: 'Monitoreo', exact: true })).toBeVisible()
      await expect(region(page).getByRole('heading', { name: 'Cajón 1' })).toBeVisible()
      page.off('console', observar)
      expect(errores).toEqual([])
    }
    const tarjeta = region(page).locator('li.cajon-vision').first()
    await tarjeta.getByRole('button', { name: 'Cambiar nombre de Cajón 1' }).click()
    await tarjeta.getByLabel('Nombre visible').fill('Nombre del operador')
    await tarjeta.getByRole('button', { name: 'Guardar' }).click()
    await expect(region(page).getByRole('heading', { name: 'Nombre del operador' })).toBeVisible()
    expect(guardados.at(-1)?.cookie).toBe(cookieOperador)
    expect(guardados.at(-1)?.csrf).toBe(csrfSintetico)
  })

  test('navega de Inicio a Monitoreo por CSR sin errores ni solicitudes inesperadas', async ({ page }) => {
    cajones = crearCajones(3)
    const errores: string[] = []
    let documentos = 0
    page.on('pageerror', (error) => errores.push(error.message))
    page.on('console', (mensaje) => {
      if (mensaje.type() === 'error' || /hydration|mismatch/i.test(mensaje.text())) {
        errores.push(mensaje.text())
      }
    })
    page.on('request', (solicitud) => {
      if (solicitud.isNavigationRequest() && solicitud.frame() === page.mainFrame()) documentos++
    })
    page.on('response', (respuesta) => {
      if (respuesta.status() >= 400) errores.push(`${respuesta.status()} ${new URL(respuesta.url()).pathname}`)
    })
    await page.context().addCookies([{ name: 'JSESSIONID', value: 'vision-ui-fixture-dueno', url: base }])
    await page.goto(`${base}/admin`)
    await expect(page.getByRole('heading', { name: 'Inicio', exact: true })).toBeVisible()
    const documentosAntes = documentos
    await page.getByRole('link', { name: 'Monitoreo', exact: true }).click()
    await expect(page).toHaveURL(/\/admin\/vision$/)
    await expect(region(page).locator('li.cajon-vision')).toHaveCount(3)
    expect(documentos).toBe(documentosAntes)
    expect(errores).toEqual([])
  })

  test('muestra fechas individuales si las observaciones son diferentes', async ({ page }) => {
    cajones = crearCajones(3)
    cajones[1]!.observadoEn = '2026-11-03T01:02:03Z'
    await entrar(page)
    await expect(region(page).locator('li.cajon-vision time')).toHaveCount(3)
    await expect(region(page).locator('time[datetime="2026-11-03T01:02:03Z"]')).toContainText('UTC')
  })

  test('reconecta SSE con el cursor y mantiene alineados los paneles en distintos anchos', async ({ page }) => {
    cajones = crearCajones(10)
    const aperturasPrevias = aperturasSse
    await entrar(page)
    await expect.poll(() => aperturasSse).toBeGreaterThan(aperturasPrevias)
    const lecturasAntes = lecturas.length
    emitirVision()
    await expect.poll(() => lecturas.length).toBeGreaterThan(lecturasAntes)
    const cursor = `aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa:${secuenciaSse}`
    const aperturasAntesDeCorte = aperturasSse
    for (const conexion of conexionesSse) conexion.end()
    await expect.poll(() => aperturasSse, { timeout: 15_000 }).toBeGreaterThan(aperturasAntesDeCorte)
    expect(cursoresSse).toContain(cursor)
    for (const ancho of [1440, 1024, 390]) {
      await page.setViewportSize({ width: ancho, height: 900 })
      const capacidad = await page.getByRole('region', { name: 'Capacidad del estacionamiento' }).boundingBox()
      const vision = await region(page).boundingBox()
      expect(capacidad).not.toBeNull()
      expect(vision).not.toBeNull()
      expect(Math.abs(capacidad!.x - vision!.x)).toBeLessThanOrEqual(2)
      expect(Math.abs(capacidad!.width - vision!.width)).toBeLessThanOrEqual(2)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    }
  })
})
