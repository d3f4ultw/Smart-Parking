import { expect, test, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { abrirDirectorio, baseURL } from './sesion'

const nombreBotonRegistro = 'Registrar empleado'
const nombrePaginador = 'Páginas de empleados'

function paginador(page: Page) {
  return page.locator(`[aria-label="${nombrePaginador}"]`)
}

async function crearEmpleadoSintetico(page: Page): Promise<number> {
  const nombre = `Aceptacion-${randomUUID().slice(0, 8)}`
  let estadoAlta = 0
  const recibirRespuesta = (respuesta: import('@playwright/test').Response) => {
    const solicitud = respuesta.request()
    const url = new URL(respuesta.url())
    if (solicitud.method() === 'POST' && url.pathname === '/api/v1/empleados') estadoAlta = respuesta.status()
  }
  page.on('response', recibirRespuesta)
  await page.getByRole('button', { name: nombreBotonRegistro }).first().click()
  const dialogo = page.getByRole('dialog', { name: nombreBotonRegistro })
  await expect(dialogo).toBeVisible()
  await page.getByLabel('Nombres').fill(nombre)
  await page.getByLabel('Primer apellido').fill('Prueba')
  await page.getByLabel('Segundo apellido (opcional)').fill('Paginacion')
  await page.getByRole('button', { name: 'Registrar', exact: true }).click()
  await expect(dialogo).toBeHidden()
  page.off('response', recibirRespuesta)
  expect(estadoAlta).toBe(201)
  return estadoAlta
}

async function asegurarTerceraPagina(page: Page): Promise<void> {
  const botonTres = paginador(page).locator('button, a').filter({ hasText: /^3$/ })
  const estadosAltas: number[] = []
  for (let cantidad = 0; cantidad < 25 && !(await botonTres.isVisible().catch(() => false)); cantidad += 1) {
    estadosAltas.push(await crearEmpleadoSintetico(page))
  }
  if (!(await botonTres.isVisible().catch(() => false))) {
    const respuesta = await page.request.get(`${baseURL}/api/v1/empleados?pagina=1`)
    let forma: Record<string, unknown> = {}
    try {
      forma = (await respuesta.json()) as Record<string, unknown>
    } catch {
      forma = {}
    }
    const resumen = await page.evaluate(() => {
      const paginacion = document.querySelector('[aria-label="Páginas de empleados"]')
      return {
        ruta: location.pathname,
        filasVisibles: document.querySelectorAll('tbody tr').length,
        paginadorPresente: Boolean(paginacion),
        rolPaginador: paginacion?.getAttribute('role') ?? null,
        etiquetaPaginador: paginacion?.getAttribute('aria-label') ?? null,
        paginasVisibles: Array.from(paginacion?.querySelectorAll('button, a') ?? [])
          .map((control) => ({
            nombre: control.getAttribute('aria-label') || control.getAttribute('title') || (control.textContent ?? '').trim(),
            role: control.getAttribute('role'),
          })),
      }
    })
    const camposNumericos = Object.fromEntries(
      Object.entries(forma).filter(([, valor]) => typeof valor === 'number'),
    )
    const tamanosListas = Object.fromEntries(
      Object.entries(forma).filter(([, valor]) => Array.isArray(valor)).map(([clave, valor]) => [clave, valor.length]),
    )
    throw new Error(
      `No aparecio pagina 3; resumen=${JSON.stringify({
        estadoBff: respuesta.status(),
        claves: Object.keys(forma).sort(),
        camposNumericos,
        tamanosListas,
        altas201: estadosAltas.filter((estado) => estado === 201).length,
        totalAltas: estadosAltas.length,
        ...resumen,
      })}`,
    )
  }
}

test('pagina 2 abre directamente y conserva paginacion al recargar y usar historial', async ({ page }) => {
  test.setTimeout(150_000)
  await abrirDirectorio(page)
  await asegurarTerceraPagina(page)

  const paginaActual = () => new URL(page.url()).searchParams.get('pagina')
  const paginaDos = paginador(page).locator('button, a').filter({ hasText: /^2$/ })
  await paginaDos.click()
  await expect.poll(paginaActual).toBe('2')
  const filasEnPaginaDos = await page.locator('tbody tr').count()
  expect(filasEnPaginaDos).toBeGreaterThan(0)

  await page.goBack()
  await expect.poll(paginaActual).not.toBe('2')
  await page.goForward()
  await expect.poll(paginaActual).toBe('2')

  await page.goto(`${baseURL}/admin/empleados?pagina=2`)
  await expect(page.getByRole('region', { name: 'Lista de empleados' })).toBeVisible()
  expect(await page.locator('tbody tr').count()).toBe(filasEnPaginaDos)
  await page.reload()
  await expect.poll(paginaActual).toBe('2')
  expect(await page.locator('tbody tr').count()).toBe(filasEnPaginaDos)
  await expect(paginador(page).locator('button, a').filter({ hasText: /^2$/ })).toBeVisible()
})

test('respuesta atrasada de pagina 2 no reemplaza pagina 1 tras browser Back', async ({ page }) => {
  test.setTimeout(45_000)
  await abrirDirectorio(page)
  await asegurarTerceraPagina(page)

  let anunciarRespuesta!: () => void
  let liberarRespuesta!: () => void
  const respuestaCapturada = new Promise<void>((resolve) => {
    anunciarRespuesta = resolve
  })
  const barrera = new Promise<void>((resolve) => {
    liberarRespuesta = resolve
  })
  let respuestaPaginaDosCapturada = false
  let respuestaObsoletaEntregada = false
  const estadosPorPagina: Array<{ pagina: string | null; estado: number }> = []

  page.on('response', (respuesta) => {
    const url = new URL(respuesta.url())
    if (respuesta.request().method() === 'GET' && url.pathname === '/api/v1/empleados') {
      estadosPorPagina.push({ pagina: url.searchParams.get('pagina'), estado: respuesta.status() })
    }
  })
  await page.route('**/api/v1/empleados?*', async (route) => {
    const solicitud = route.request()
    const url = new URL(solicitud.url())
    if (!respuestaPaginaDosCapturada && solicitud.method() === 'GET' && url.searchParams.get('pagina') === '2') {
      respuestaPaginaDosCapturada = true
      const respuesta = await route.fetch()
      const cuerpo = await respuesta.body()
      anunciarRespuesta()
      await barrera
      try {
        await route.fulfill({ response: respuesta, body: cuerpo })
        respuestaObsoletaEntregada = true
      } catch {
        respuestaObsoletaEntregada = false
      }
      return
    }
    await route.continue()
  })

  try {
    const paginaUnoInicial = await page.locator('tbody tr').first().innerText()
    const paginaDos = paginador(page).locator('button, a').filter({ hasText: /^2$/ })
    const navegacionDos = paginaDos.click({ noWaitAfter: true })
    await respuestaCapturada
    await expect.poll(() => new URL(page.url()).searchParams.get('pagina')).toBe('2')

    await page.goBack()
    await expect
      .poll(() => {
        const pagina = new URL(page.url()).searchParams.get('pagina')
        return pagina === null || pagina === '1'
      })
      .toBe(true)
    await expect(page.getByRole('region', { name: 'Lista de empleados' })).toBeVisible()
    const paginaUnoBff = estadosPorPagina.some((item) => item.pagina === '1' && item.estado === 200)
    liberarRespuesta()
    await navegacionDos.catch(() => undefined)
    await page.waitForTimeout(500)
    test.skip(!respuestaObsoletaEntregada, 'El navegador canceló la respuesta antigua antes de entregarla al cliente.')
    const paginaFinal = new URL(page.url()).searchParams.get('pagina')
    expect(paginaFinal === null || paginaFinal === '1').toBe(true)
    await expect(page.locator('tbody tr').first()).toBeVisible()
    const primeraFilaTrasRespuestaAntigua = await page.locator('tbody tr').first().innerText()
    expect(primeraFilaTrasRespuestaAntigua === paginaUnoInicial).toBe(true)
    console.log(`GET BFF pagina 1 tras Back: ${paginaUnoBff}; respuesta obsoleta entregada: ${respuestaObsoletaEntregada}`)
  } finally {
    liberarRespuesta()
  }
})
