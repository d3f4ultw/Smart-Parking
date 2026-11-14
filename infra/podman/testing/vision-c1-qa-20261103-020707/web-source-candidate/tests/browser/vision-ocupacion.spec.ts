import { randomUUID } from 'node:crypto'
import { readFile, rename, unlink, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { expect, test, type APIRequestContext, type Page, type Playwright } from '@playwright/test'
import { baseURL, iniciarSesion } from './sesion'

type Estado = 'LIBRE' | 'OCUPADO' | 'NO_VERIFICABLE'
type Cajon = {
  cajonId: string
  etiqueta: string
  estado: Estado
  ultimoEstadoConfirmado: 'LIBRE' | 'OCUPADO' | null
  observadoEn: string | null
}
type Zona = { visionZoneId: string; etiqueta: string; cajonId: string | null }

const apiURL = process.env.TEST_API_BASE_URL || ''
const fixtureDir = process.env.VISION_FIXTURE_DIR || ''
const rutaVision = '**/api/v1/vision/cajones'
const espera = (milisegundos: number) =>
  new Promise<void>((resolver) => setTimeout(resolver, milisegundos))

function exigirEntornoDesechable(): void {
  if (process.env.VISION_TEST_DISPOSABLE !== 'true' || !fixtureDir || !apiURL) {
    throw new Error('Se requiere el entorno Vision desechable explícito y su fixture aislada.')
  }
  const destino = new URL(apiURL)
  if (destino.hostname !== 'api' || destino.port !== '8080') {
    throw new Error('La API Vision de aceptación debe ser api:8080 en la red de pruebas.')
  }
}

async function fixture(
  accion: string,
  cajonId?: string,
): Promise<{ ok: boolean; cajonId?: string }> {
  const id = randomUUID()
  const temporal = join(fixtureDir, `solicitud-${id}.tmp`)
  const solicitud = join(fixtureDir, 'solicitud.json')
  const respuesta = join(fixtureDir, `respuesta-${id}.json`)
  await writeFile(temporal, JSON.stringify({ id, accion, ...(cajonId ? { cajonId } : {}) }), {
    mode: 0o600,
  })
  await rename(temporal, solicitud)
  for (let intento = 0; intento < 200; intento++) {
    try {
      const resultado = JSON.parse(await readFile(respuesta, 'utf8')) as {
        ok: boolean
        cajonId?: string
      }
      await unlink(respuesta)
      if (!resultado.ok) throw new Error(`Falló el fixture aislado: ${accion}`)
      return resultado
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
      await espera(100)
    }
  }
  throw new Error(`El fixture aislado no respondió a ${accion}`)
}

async function clienteAutenticado(
  playwright: Playwright,
  url: string,
  rol: 'dueno' | 'operador' | 'cliente',
): Promise<APIRequestContext> {
  const prefijo =
    rol === 'cliente' ? 'TEST_CLIENT' : rol === 'operador' ? 'TEST_OPERATOR' : 'TEST_OWNER'
  const correo = process.env[`${prefijo}_EMAIL`]
  const contrasena = process.env[`${prefijo}_PASSWORD`]
  if (!correo || !contrasena) throw new Error(`Faltan credenciales sintéticas para ${rol}.`)
  const contexto = await playwright.request.newContext({ baseURL: url })
  const csrfRuta = rol === 'cliente' ? '/api/v1/clientes/csrf' : '/api/v1/csrf'
  const sesionRuta = rol === 'cliente' ? '/api/v1/clientes/sesion' : '/api/v1/sesion'
  const csrf = await contexto.get(csrfRuta)
  expect(csrf.status()).toBe(200)
  const token = (await csrf.json()).token as string
  const sesion = await contexto.post(sesionRuta, {
    data: { correo, contrasena },
    headers: { 'X-CSRF-TOKEN': token },
  })
  expect(sesion.status()).toBe(200)
  return contexto
}

async function tokenCsrf(api: APIRequestContext): Promise<string> {
  const respuesta = await api.get('/api/v1/csrf')
  expect(respuesta.status()).toBe(200)
  return String((await respuesta.json()).token)
}

async function leerCajones(api: APIRequestContext): Promise<Cajon[]> {
  const respuesta = await api.get('/api/v1/vision/cajones')
  expect(respuesta.status()).toBe(200)
  expect(respuesta.headers()['cache-control']).toContain('no-store')
  return (await respuesta.json()) as Cajon[]
}

async function calibrar(
  api: APIRequestContext,
  fuente: string,
  revision: number,
  zonas: Zona[],
): Promise<Zona[]> {
  const respuesta = await api.put(`/api/v1/vision/fuentes/${fuente}/calibracion`, {
    data: { revisionCalibracion: revision, hashCalibracion: String(revision).repeat(64), zonas },
    headers: { 'X-CSRF-TOKEN': await tokenCsrf(api) },
  })
  expect(respuesta.status()).toBe(200)
  return ((await respuesta.json()) as { zonas: Zona[] }).zonas
}

function seccion(page: Page) {
  return page.getByRole('region', { name: 'Ocupación física' })
}

function indicador(page: Page, nombre: string) {
  return seccion(page)
    .locator('dl > div')
    .filter({ has: page.getByText(nombre, { exact: true }) })
    .locator('dd')
}

async function comprobarSnapshot(page: Page, cajones: Cajon[]): Promise<void> {
  const region = seccion(page)
  const items = region.locator('li.cajon-vision')
  // La fixture SQL no emite SSE; se espera la reconciliación de 30 s y su margen de respuesta.
  const limite = Date.now() + 40_000
  const restante = () => Math.max(1, limite - Date.now())
  await expect(items).toHaveCount(cajones.length, { timeout: restante() })
  const conteos = {
    registrados: cajones.length,
    ocupados: cajones.filter((cajon) => cajon.estado === 'OCUPADO').length,
    libres: cajones.filter((cajon) => cajon.estado === 'LIBRE').length,
    noVerificables: cajones.filter((cajon) => cajon.estado === 'NO_VERIFICABLE').length,
  }
  expect(conteos.registrados).toBe(conteos.ocupados + conteos.libres + conteos.noVerificables)
  await expect(indicador(page, 'Cajones registrados')).toHaveText(String(conteos.registrados), {
    timeout: restante(),
  })
  await expect(indicador(page, 'Ocupados físicamente')).toHaveText(String(conteos.ocupados), {
    timeout: restante(),
  })
  await expect(indicador(page, 'Libres físicamente')).toHaveText(String(conteos.libres), {
    timeout: restante(),
  })
  await expect(indicador(page, 'No verificables')).toHaveText(String(conteos.noVerificables), {
    timeout: restante(),
  })
  for (const cajon of cajones) {
    const tarjeta = items.filter({
      has: page.getByRole('heading', { name: cajon.etiqueta, exact: true }),
    })
    await expect(tarjeta).toHaveCount(1, { timeout: restante() })
    const estado =
      cajon.estado === 'LIBRE' ? 'Libre' : cajon.estado === 'OCUPADO' ? 'Ocupado' : 'No verificable'
    await expect(tarjeta.locator('.estado-cajon')).toHaveText(estado, { timeout: restante() })
    if (cajon.observadoEn)
      await expect(tarjeta.locator(`time[datetime="${cajon.observadoEn}"]`)).toBeVisible({
        timeout: restante(),
      })
    else await expect(tarjeta).toContainText('Sin observaciones', { timeout: restante() })
    if (cajon.estado === 'NO_VERIFICABLE' && cajon.ultimoEstadoConfirmado) {
      await expect(tarjeta).toContainText('Última confirmación histórica:', { timeout: restante() })
    }
  }
}

test.describe.configure({ timeout: 240_000 })

test('Java y PostgreSQL reales: cero, ocho, nueve, inactivos, alta y borrado con reconciliación', async ({
  page,
  playwright,
}) => {
  exigirEntornoDesechable()
  await fixture('reiniciar_vision')
  const api = await clienteAutenticado(playwright, apiURL, 'dueno')
  const errores: string[] = []
  page.on('pageerror', (error) => errores.push(error.name))
  page.on('console', (mensaje) => {
    if (/hydration|mismatch/i.test(mensaje.text())) errores.push('hidratación')
  })
  let documentos = 0
  let getBrowser = 0
  page.on('request', (solicitud) => {
    if (solicitud.isNavigationRequest() && solicitud.frame() === page.mainFrame()) documentos++
    if (
      solicitud.method() === 'GET' &&
      new URL(solicitud.url()).pathname === '/api/v1/vision/cajones'
    )
      getBrowser++
  })

  expect(await leerCajones(api)).toEqual([])
  await iniciarSesion(page)
  await expect(seccion(page)).toBeVisible()
  await expect(seccion(page)).toContainText(
    'La ocupación física no confirma disponibilidad para ingreso.',
  )
  await expect(seccion(page)).toContainText('Todavía no hay cajones registrados.')
  await comprobarSnapshot(page, [])

  const fuente = randomUUID()
  const registro = await api.post('/api/v1/vision/fuentes', {
    data: { fuenteId: fuente },
    headers: { 'X-CSRF-TOKEN': await tokenCsrf(api) },
  })
  expect(registro.status()).toBe(200)
  const zonas = Array.from({ length: 8 }, (_, i) => ({
    visionZoneId: randomUUID(),
    etiqueta: `C${String(i + 1).padStart(2, '0')}`,
    cajonId: null,
  }))
  const mapeo = await calibrar(api, fuente, 1, zonas)
  await fixture('sembrar_estados')
  const ocho = await leerCajones(api)
  expect(ocho).toHaveLength(8)
  expect(ocho.find((c) => c.etiqueta === 'C01')?.estado).toBe('LIBRE')
  expect(ocho.find((c) => c.etiqueta === 'C02')?.estado).toBe('OCUPADO')
  expect(ocho.find((c) => c.etiqueta === 'C03')?.estado).toBe('NO_VERIFICABLE')
  const documentosAntes = documentos
  await comprobarSnapshot(page, ocho)
  expect(documentos).toBe(documentosAntes)

  const contadorUrl = process.env.TEST_VISION_COUNTER_URL
  const contador = contadorUrl ? await playwright.request.newContext() : null
  if (contadorUrl) {
    const destino = new URL(contadorUrl)
    if (
      destino.hostname !== 'vision-counter' ||
      destino.port !== '8081' ||
      destino.pathname !== '/__conteo'
    ) {
      throw new Error('El contador debe pertenecer a la red desechable de pruebas.')
    }
    // Salir por CSR cancela el temporizador anterior antes de contar el nuevo SSR.
    await page
      .getByRole('navigation', { name: 'Principal' })
      .first()
      .getByRole('link', { name: 'Empleados' })
      .click()
    await expect(page).toHaveURL(/\/admin\/empleados$/)
  }
  const leerContador = async () => {
    if (!contador || !contadorUrl) return null
    const respuesta = await contador.get(contadorUrl)
    expect(respuesta.status()).toBe(200)
    const count: unknown = (await respuesta.json()).count
    expect(typeof count === 'number' && Number.isSafeInteger(count) && count >= 0).toBe(true)
    return count as number
  }
  const cuentaAntes = await leerContador()
  const lecturaBrowserAntes = getBrowser
  const inicioSsr = Date.now()
  const respuestaSsr = await page.goto(`${baseURL}/admin`)
  expect(respuestaSsr?.status()).toBe(200)
  const html = await respuestaSsr!.text()
  expect(html).toContain('Ocupación física')
  expect(html).toContain('C01')
  await page.waitForFunction(() =>
    Boolean(
      (document.querySelector('#__nuxt') as HTMLElement & { __vue_app__?: unknown })?.__vue_app__,
    ),
  )
  await page.waitForTimeout(1200)
  expect(getBrowser - lecturaBrowserAntes).toBe(0)
  const cuentaDespues = await leerContador()
  if (cuentaAntes !== null && cuentaDespues !== null) {
    expect(Date.now() - inicioSsr).toBeLessThan(5_000)
    expect(cuentaDespues - cuentaAntes).toBe(1)
    console.log('SSR/hidratación: exactamente 1 GET upstream y 0 GET browser.')
  }
  await contador?.dispose()
  expect(errores).toEqual([])
  await comprobarSnapshot(page, ocho)

  const novena = { visionZoneId: randomUUID(), etiqueta: 'C09', cajonId: null }
  const mapaNueve = await calibrar(api, fuente, 2, [...mapeo, novena])
  const nueve = await leerCajones(api)
  expect(nueve).toHaveLength(9)
  const antesDeCambios = documentos
  await comprobarSnapshot(page, nueve)
  await fixture('sembrar_estados')
  const nueveVigentes = await leerCajones(api)
  expect(nueveVigentes.find((c) => c.etiqueta === 'C01')?.estado).toBe('LIBRE')
  await comprobarSnapshot(page, nueveVigentes)
  const mapaSinPrimera = mapaNueve.filter((zona) => zona.etiqueta !== 'C01')
  await calibrar(api, fuente, 3, mapaSinPrimera)
  const conservados = await leerCajones(api)
  expect(conservados).toHaveLength(9)
  expect(conservados.find((c) => c.etiqueta === 'C01')?.estado).toBe('NO_VERIFICABLE')
  await comprobarSnapshot(page, conservados)

  const creado = await fixture('crear_suelto')
  expect(creado.cajonId).toBeTruthy()
  const diez = await leerCajones(api)
  expect(diez).toHaveLength(10)
  expect(diez.some((c) => c.cajonId === creado.cajonId && c.etiqueta === 'Prueba dinámica')).toBe(
    true,
  )
  await comprobarSnapshot(page, diez)
  await fixture('borrar_suelto', creado.cajonId)
  const trasBorrar = await leerCajones(api)
  expect(trasBorrar).toHaveLength(9)
  expect(trasBorrar.some((c) => c.cajonId === creado.cajonId)).toBe(false)
  await comprobarSnapshot(page, trasBorrar)
  expect(documentos).toBe(antesDeCambios)

  for (const viewport of [
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 1440, height: 900 },
  ]) {
    await page.setViewportSize(viewport)
    await expect(seccion(page)).toBeVisible()
    const medidas = await page.evaluate(() => ({
      ventana: window.innerWidth,
      documento: document.documentElement.scrollWidth,
      cuerpo: document.body.scrollWidth,
    }))
    expect(Math.max(medidas.documento, medidas.cuerpo)).toBeLessThanOrEqual(medidas.ventana + 1)
  }
  await api.dispose()
})

test('el BFF y Java deniegan Vision a OPERADOR y CLIENTE', async ({ playwright }) => {
  exigirEntornoDesechable()
  for (const rol of ['operador', 'cliente'] as const) {
    const api = await clienteAutenticado(playwright, apiURL, rol)
    const web = await clienteAutenticado(playwright, baseURL, rol)
    const directo = await api.get('/api/v1/vision/cajones')
    const bff = await web.get('/api/v1/vision/cajones')
    expect([401, 403]).toContain(directo.status())
    expect([401, 403]).toContain(bff.status())
    console.log(`Permisos ${rol}: Java=${directo.status()}, BFF=${bff.status()}`)
    const admin = await web.get('/admin', { maxRedirects: 0 })
    expect(admin.status()).not.toBe(200)
    expect(await admin.text()).not.toContain('Ocupación física')
    await api.dispose()
    await web.dispose()
  }
})

test('fallos marcan histórico y reintentan con límites 5, 10, 20 y 30 segundos', async ({
  page,
}) => {
  exigirEntornoDesechable()
  await page.clock.install({ time: new Date('2026-11-02T12:00:00Z') })
  await iniciarSesion(page)
  await expect(seccion(page)).toBeVisible()
  const instantePausa = await page.evaluate(() => Date.now() + 1_000)
  await page.clock.pauseAt(instantePausa)
  let consultas = 0
  let fallar = false
  const libre: Cajon[] = [
    {
      cajonId: '00000000-0000-4000-8000-000000000001',
      etiqueta: 'Prueba libre',
      estado: 'LIBRE',
      ultimoEstadoConfirmado: 'LIBRE',
      observadoEn: '2026-11-02T12:00:00Z',
    },
  ]
  await page.route(rutaVision, async (ruta) => {
    consultas++
    await ruta.fulfill({
      status: fallar ? 503 : 200,
      contentType: 'application/json',
      headers: {
        'x-eventos-cursor': '00000000-0000-4000-8000-000000000001:0',
        'x-vision-vigencia-restante-ms': '120000',
      },
      body: JSON.stringify(fallar ? { codigo: 'VISION_NO_DISPONIBLE' } : libre),
    })
  })
  await seccion(page).getByRole('button', { name: 'Actualizar' }).click()
  await expect.poll(() => consultas).toBe(1)
  await expect(seccion(page)).toContainText('Prueba libre')
  await expect(indicador(page, 'Libres físicamente')).toHaveText('1')
  await expect(seccion(page).getByRole('button', { name: 'Actualizar' })).toBeEnabled()
  fallar = true
  await seccion(page).getByRole('button', { name: 'Actualizar' }).click()
  await expect.poll(() => consultas).toBe(2)
  await expect(indicador(page, 'Libres físicamente')).toHaveText('—')
  await expect(seccion(page).locator('.estado-cajon')).toHaveText('Sin actualizar')
  await expect(seccion(page)).toContainText('Los datos mostrados son históricos.')
  await expect(seccion(page).getByRole('button', { name: 'Reintentar' })).toBeEnabled()
  for (const [indice, retraso] of [5_000, 10_000, 20_000, 30_000].entries()) {
    if (indice === 3) fallar = false
    if (indice === 3) await page.keyboard.press('Tab')
    await page.clock.fastForward(retraso - 1)
    expect(consultas).toBe(2 + indice)
    await page.clock.fastForward(1)
    await expect.poll(() => consultas).toBe(3 + indice)
    if (indice < 3)
      await expect(seccion(page).getByRole('button', { name: 'Reintentar' })).toBeEnabled()
  }
  await expect(indicador(page, 'Libres físicamente')).toHaveText('1')
  await expect(seccion(page).locator('.estado-cajon')).toHaveText('Libre')
})

test('oculto y sin conexión pausan y reconcilian sin interacción al regresar', async ({
  page,
  context,
}) => {
  exigirEntornoDesechable()
  await iniciarSesion(page)
  await expect(seccion(page)).toBeVisible()
  await page.clock.install()
  let consultas = 0
  await page.route(rutaVision, async (ruta) => {
    consultas++
    await ruta.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: {
        'x-eventos-cursor': '00000000-0000-4000-8000-000000000001:0',
        'x-vision-vigencia-restante-ms': '120000',
      },
      body: JSON.stringify([
        {
          cajonId: '00000000-0000-4000-8000-000000000001',
          etiqueta: `Consulta ${consultas}`,
          estado: 'LIBRE',
          ultimoEstadoConfirmado: 'LIBRE',
          observadoEn: '2026-11-02T12:00:00Z',
        },
      ]),
    })
  })
  await seccion(page).getByRole('button', { name: 'Actualizar' }).click()
  await expect.poll(() => consultas).toBe(1)
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await expect(indicador(page, 'Cajones registrados')).toHaveText('—')
  await page.clock.fastForward(10_000)
  expect(consultas).toBe(1)
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await page.clock.fastForward(1)
  await expect.poll(() => consultas).toBe(2)
  await expect(indicador(page, 'Cajones registrados')).not.toHaveText('—')
  await context.setOffline(true)
  await expect(indicador(page, 'Cajones registrados')).toHaveText('—')
  await page.clock.fastForward(10_000)
  expect(consultas).toBe(2)
  await context.setOffline(false)
  await page.clock.fastForward(1)
  await expect.poll(() => consultas).toBe(3)
  await expect(indicador(page, 'Cajones registrados')).not.toHaveText('—')
  await page.clock.fastForward(30_000)
  await expect.poll(() => consultas).toBe(4)
  await expect(seccion(page)).toContainText('Consulta 4')
})

test('timeout cancela y no solapa solicitudes ni acepta respuestas tardías', async ({ page }) => {
  exigirEntornoDesechable()
  await iniciarSesion(page)
  await expect(seccion(page)).toBeVisible()
  await page.clock.install()
  let consultas = 0
  let liberar!: () => void
  const bloqueada = new Promise<void>((resolver) => {
    liberar = resolver
  })
  await page.route(rutaVision, async (ruta) => {
    consultas++
    if (consultas === 1) {
      await bloqueada
      try {
        await ruta.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([
            {
              cajonId: '00000000-0000-4000-8000-000000000002',
              etiqueta: 'Respuesta fuera de plazo',
              estado: 'LIBRE',
              ultimoEstadoConfirmado: 'LIBRE',
              observadoEn: '2026-11-02T12:00:00Z',
            },
          ]),
        })
      } catch {
        // El navegador puede haber cancelado la ruta al vencer el timeout.
      }
      return
    }
    await ruta.continue()
  })
  await seccion(page).getByRole('button', { name: 'Actualizar' }).click()
  await expect.poll(() => consultas).toBe(1)
  await page.clock.fastForward(7_999)
  expect(consultas).toBe(1)
  await page.clock.fastForward(1)
  await expect(indicador(page, 'Cajones registrados')).toHaveText('—')
  await expect(seccion(page)).toContainText('históricos')
  liberar()
  await expect(seccion(page)).not.toContainText('Respuesta fuera de plazo')
  await page.clock.fastForward(5_000)
  await expect.poll(() => consultas).toBe(2)
  await expect(indicador(page, 'Cajones registrados')).not.toHaveText('—')
  await expect(seccion(page)).not.toContainText('Respuesta fuera de plazo')
})

test('navegación CSR y logout limpian monitoreo y respuestas de la sesión anterior', async ({
  page,
}) => {
  exigirEntornoDesechable()
  await iniciarSesion(page)
  await expect(seccion(page)).toBeVisible()
  await page.clock.install()
  let consultas = 0
  let liberar!: () => void
  const bloqueada = new Promise<void>((resolver) => {
    liberar = resolver
  })
  await page.route(rutaVision, async (ruta) => {
    consultas++
    await bloqueada
    try {
      await ruta.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            cajonId: '00000000-0000-4000-8000-000000000003',
            etiqueta: 'Respuesta de sesión anterior',
            estado: 'LIBRE',
            ultimoEstadoConfirmado: 'LIBRE',
            observadoEn: '2026-11-02T12:00:00Z',
          },
        ]),
      })
    } catch {
      // Una solicitud cancelada no tiene que aceptar la respuesta simulada.
    }
  })
  await seccion(page).getByRole('button', { name: 'Actualizar' }).click()
  await expect.poll(() => consultas).toBe(1)
  await page
    .getByRole('navigation', { name: 'Principal' })
    .first()
    .getByRole('link', { name: 'Empleados' })
    .click()
  await expect(page).toHaveURL(/\/admin\/empleados$/)
  await expect(page.getByRole('region', { name: 'Lista de empleados' }).first()).toBeVisible()
  liberar()
  await page.clock.fastForward(30_000)
  expect(consultas).toBe(1)
  await page.unroute(rutaVision)
  await page
    .getByRole('navigation', { name: 'Principal' })
    .first()
    .getByRole('link', { name: 'Inicio' })
    .click()
  await expect(page).toHaveURL(/\/admin$/)
  await expect(seccion(page)).toBeVisible()
  await expect(seccion(page)).not.toContainText('Respuesta de sesión anterior')

  let lecturasTrasSalir = 0
  await page.route(rutaVision, async (ruta) => {
    lecturasTrasSalir++
    await ruta.continue()
  })
  await page.getByRole('button', { name: 'Cerrar sesión' }).click()
  await expect(page).toHaveURL(/\/panel$/)
  await expect(page.getByLabel('Correo electrónico')).toBeVisible()
  await page.clock.fastForward(30_000)
  expect(lecturasTrasSalir).toBe(0)
  await expect(page.getByText('Ocupación física')).toHaveCount(0)
})

test('una sesión revocada borra ocupación privada y detiene las consultas', async ({ page }) => {
  exigirEntornoDesechable()
  await page.clock.install()
  await iniciarSesion(page)
  await expect(seccion(page)).toBeVisible()
  let consultas = 0
  let sesionRevocada = false
  const respuestasTrasRevocacion: number[] = []
  await page.route(rutaVision, async (ruta) => {
    consultas++
    await ruta.continue()
  })
  page.on('response', (respuesta) => {
    if (sesionRevocada && new URL(respuesta.url()).pathname === '/api/v1/vision/cajones')
      respuestasTrasRevocacion.push(respuesta.status())
  })
  const csrf = await page.context().request.get(`${baseURL}/api/v1/csrf`)
  expect(csrf.status()).toBe(200)
  const token = String((await csrf.json()).token)
  const cierre = await page.context().request.delete(`${baseURL}/api/v1/sesion`, {
    headers: { 'X-CSRF-TOKEN': token },
  })
  expect(cierre.status()).toBe(200)
  sesionRevocada = true
  await page.clock.fastForward(30_000)
  await expect(page).toHaveURL(/\/panel$/)
  await expect(page.getByText('Ocupación física')).toHaveCount(0)
  await page.clock.fastForward(30_000)
  expect(consultas).toBeLessThanOrEqual(1)
  expect(respuestasTrasRevocacion.every((estado) => estado === 401 || estado === 403)).toBe(true)
  const lecturaRevocada = await page.context().request.get(`${baseURL}/api/v1/vision/cajones`)
  expect([401, 403]).toContain(lecturaRevocada.status())
})

test('401 Vision con sesión vigente borra datos y permite recuperación acotada', async ({
  page,
}) => {
  exigirEntornoDesechable()
  await iniciarSesion(page)
  await expect(seccion(page)).toBeVisible()
  await expect(seccion(page).locator('li.cajon-vision').first()).toBeVisible()
  await page.clock.install()
  let consultas = 0
  let rechazar = true
  await page.route(rutaVision, async (ruta) => {
    consultas++
    if (rechazar) {
      await ruta.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ codigo: 'SESION_NO_VIGENTE' }),
      })
    } else {
      await ruta.continue()
    }
  })
  await seccion(page).getByRole('button', { name: 'Actualizar' }).click()
  await expect.poll(() => consultas).toBe(1)
  await expect(page).toHaveURL(/\/admin$/)
  await expect(seccion(page).locator('li.cajon-vision')).toHaveCount(0)
  await expect(indicador(page, 'Cajones registrados')).toHaveText('—')
  await expect(seccion(page)).toContainText('No pudimos confirmar tu acceso a la ocupación.')
  await expect(seccion(page).getByRole('button', { name: 'Reintentar' })).toBeVisible()
  await page.clock.fastForward(4_999)
  expect(consultas).toBe(1)
  rechazar = false
  await page.clock.fastForward(1)
  await expect.poll(() => consultas).toBe(2)
  await expect(seccion(page).locator('li.cajon-vision').first()).toBeVisible()
  await expect(indicador(page, 'Cajones registrados')).not.toHaveText('—')
})

test('403 Vision conserva la denegación y retira datos anteriores', async ({ page }) => {
  exigirEntornoDesechable()
  await iniciarSesion(page)
  await expect(seccion(page).locator('li.cajon-vision').first()).toBeVisible()
  await page.clock.install()
  let consultas = 0
  await page.route(rutaVision, async (ruta) => {
    consultas++
    await ruta.fulfill({
      status: 403,
      contentType: 'application/json',
      body: JSON.stringify({ codigo: 'PERMISO_INSUFICIENTE' }),
    })
  })
  await seccion(page).getByRole('button', { name: 'Actualizar' }).click()
  await expect.poll(() => consultas).toBe(1)
  await expect(page).toHaveURL(/\/admin$/)
  await expect(seccion(page).locator('li.cajon-vision')).toHaveCount(0)
  await expect(indicador(page, 'Cajones registrados')).toHaveText('—')
  await expect(seccion(page)).toContainText('No tienes acceso para consultar la ocupación.')
  await page.clock.fastForward(30_000)
  expect(consultas).toBe(1)
})

test('401 seguido de error de sesión se recupera con revalidación antes de consultar Vision', async ({
  page,
}) => {
  exigirEntornoDesechable()
  await iniciarSesion(page)
  await expect(seccion(page).locator('li.cajon-vision').first()).toBeVisible()
  let lecturasVision = 0
  let lecturasSesion = 0
  let fallaTemporal = true
  await page.route(rutaVision, async (ruta) => {
    lecturasVision++
    if (fallaTemporal) {
      await ruta.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ codigo: 'SESION_NO_VIGENTE' }),
      })
    } else {
      await ruta.continue()
    }
  })
  await page.route('**/api/v1/sesion', async (ruta) => {
    if (ruta.request().method() !== 'GET') return ruta.continue()
    lecturasSesion++
    if (fallaTemporal) {
      await ruta.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ codigo: 'API_NO_DISPONIBLE' }),
      })
    } else {
      await ruta.continue()
    }
  })
  await seccion(page).getByRole('button', { name: 'Actualizar' }).click()
  await expect.poll(() => lecturasSesion).toBeGreaterThanOrEqual(1)
  await expect(page.locator('li.cajon-vision')).toHaveCount(0)
  await expect(
    page.getByRole('alert').filter({ hasText: 'No pudimos conectar con Smart Parking' }),
  ).toBeVisible()
  const consultasInicialesSesion = lecturasSesion
  expect(lecturasVision).toBe(1)
  await page.waitForTimeout(4_000)
  expect(lecturasVision).toBe(1)
  expect(lecturasSesion).toBe(consultasInicialesSesion)
  fallaTemporal = false
  await expect
    .poll(() => lecturasSesion, { timeout: 12_000 })
    .toBeGreaterThan(consultasInicialesSesion)
  await expect.poll(() => lecturasVision, { timeout: 12_000 }).toBe(2)
  await expect(seccion(page).locator('li.cajon-vision').first()).toBeVisible()
})
