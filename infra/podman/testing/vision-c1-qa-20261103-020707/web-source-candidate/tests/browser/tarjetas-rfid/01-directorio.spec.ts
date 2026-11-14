import { expect, test } from '@playwright/test'
import { baseURL, iniciarSesion } from './soporte'

function url(ruta: string): string {
  return new URL(ruta, baseURL).toString()
}

test('el módulo aparece en navegación de escritorio y móvil', async ({ page }) => {
  await iniciarSesion(page)
  await page.goto(url('/admin'))

  const navegacion = page.getByRole('navigation', { name: 'Principal' }).first()
  await navegacion.getByRole('link', { name: 'Tarjetas RFID', exact: true }).click()
  await expect(page).toHaveURL(/\/admin\/tarjetas-rfid$/)
  await expect(page.getByRole('heading', { name: 'Tarjetas RFID' }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Asociar tarjeta', exact: true })).toBeVisible()

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(url('/admin'))
  await page.getByRole('button', { name: 'Abrir navegación' }).click()
  const drawer = page.locator('#menu-movil-admin')
  await expect(drawer).toBeVisible()
  await drawer.getByRole('link', { name: 'Tarjetas RFID', exact: true }).click()
  await expect(page).toHaveURL(/\/admin\/tarjetas-rfid$/)
  await expect(drawer).toBeHidden()
  await expect(page.getByRole('button', { name: 'Asociar tarjeta', exact: true })).toBeVisible()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  )
  expect(overflow, 'el módulo no desborda el viewport móvil').toBe(false)
})

test('la búsqueda inicia vacía, espera dos caracteres y comparte CLIENTE/EMPLEADO', async ({
  page,
}) => {
  const consultasPersonas: URL[] = []
  page.on('request', (solicitud) => {
    const destino = new URL(solicitud.url())
    if (destino.pathname === '/api/v1/tarjetas-rfid/personas') consultasPersonas.push(destino)
  })

  await iniciarSesion(page)
  await page.goto(url('/admin/tarjetas-rfid'))
  await page.getByRole('button', { name: 'Asociar tarjeta', exact: true }).click()
  const dialogo = page.getByRole('dialog', { name: 'Asociar tarjeta' })
  const busqueda = dialogo.getByRole('combobox', { name: 'Buscar' })

  await expect(busqueda).toBeFocused()
  await dialogo.getByRole('button', { name: 'CLIENTE', exact: true }).click()

  await expect(busqueda).toHaveValue('')
  await page.waitForTimeout(450)
  expect(consultasPersonas.length, 'abrir el modal no busca candidatos').toBe(0)

  await busqueda.fill('S')
  await page.waitForTimeout(450)
  expect(consultasPersonas.length, 'un carácter no inicia la búsqueda').toBe(0)

  const respuestaCliente = page.waitForResponse((respuesta) => {
    const destino = new URL(respuesta.url())
    return (
      destino.pathname === '/api/v1/tarjetas-rfid/personas' &&
      destino.searchParams.get('tipoEntidad') === 'CLIENTE' &&
      destino.searchParams.get('busqueda') === 'Stage 2'
    )
  })
  await busqueda.fill('Stage 2')
  const respuestaInicial = await respuestaCliente
  expect(respuestaInicial.status()).toBe(200)
  await expect(dialogo.getByRole('option', { name: /^CLI-\d{4,} · / }).first()).toBeVisible()
  expect(consultasPersonas.length, 'una escritura estabilizada produce una consulta').toBe(1)

  await dialogo.getByRole('button', { name: 'EMPLEADO', exact: true }).click()
  await expect(busqueda).toHaveValue('')
  await page.waitForTimeout(450)
  expect(consultasPersonas.length, 'cambiar de tipo limpia resultados sin buscar de nuevo').toBe(1)
  const respuestaEmpleado = page.waitForResponse((respuesta) => {
    const destino = new URL(respuesta.url())
    return (
      destino.pathname === '/api/v1/tarjetas-rfid/personas' &&
      destino.searchParams.get('tipoEntidad') === 'EMPLEADO' &&
      destino.searchParams.get('busqueda') === 'Stage 2'
    )
  })
  await busqueda.fill('Stage 2')
  const respuestaSecundaria = await respuestaEmpleado
  expect(respuestaSecundaria.status()).toBe(200)
  await expect(
    dialogo.getByRole('option', { name: /Empleado Stage 2 Sintetico/ }).first(),
  ).toBeVisible()
  expect(consultasPersonas.length).toBe(2)

  await busqueda.press('ArrowDown')
  await busqueda.press('Enter')
  await dialogo.getByRole('button', { name: 'Siguiente', exact: true }).click()
  await expect(dialogo.getByText('2. Leer tarjeta', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialogo).toBeHidden()
  await expect(page.getByRole('button', { name: 'Asociar tarjeta', exact: true })).toBeFocused()
})

test('una respuesta de búsqueda obsoleta no reemplaza el resultado más reciente', async ({
  page,
}) => {
  let liberarBusquedaAntigua!: () => void
  let notificarInicioAntigua!: () => void
  let notificarFinAntigua!: () => void
  let inicioAntigua = false
  const antiguaLiberada = new Promise<void>((resolve) => {
    liberarBusquedaAntigua = resolve
  })
  const antiguaIniciada = new Promise<void>((resolve) => {
    notificarInicioAntigua = resolve
  })
  const antiguaTerminada = new Promise<void>((resolve) => {
    notificarFinAntigua = resolve
  })

  await iniciarSesion(page)
  await page.goto(url('/admin/tarjetas-rfid'))
  await page.getByRole('button', { name: 'Asociar tarjeta', exact: true }).click()
  const dialogo = page.getByRole('dialog', { name: 'Asociar tarjeta' })
  const busqueda = dialogo.getByRole('combobox', { name: 'Buscar' })
  await page.route('**/api/v1/tarjetas-rfid/personas?*', async (ruta) => {
    const destino = new URL(ruta.request().url())
    if (destino.searchParams.get('busqueda') === 'Stage 2') {
      inicioAntigua = true
      notificarInicioAntigua()
      await antiguaLiberada
    }
    await ruta.continue().catch(() => undefined)
    if (destino.searchParams.get('busqueda') === 'Stage 2') notificarFinAntigua()
  })

  try {
    await busqueda.fill('Stage 2')
    await antiguaIniciada
    const respuestaNueva = page.waitForResponse((respuesta) => {
      const destino = new URL(respuesta.url())
      return (
        destino.pathname === '/api/v1/tarjetas-rfid/personas' &&
        destino.searchParams.get('busqueda') === 'zz'
      )
    })
    await busqueda.fill('zz')
    expect((await respuestaNueva).status()).toBe(200)
    expect(await dialogo.getByRole('option', { name: /^CLI-\d{4,} · / }).count()).toBe(0)
    liberarBusquedaAntigua()
    await antiguaTerminada
    await page.waitForTimeout(250)
    expect(await dialogo.getByRole('option', { name: /^CLI-\d{4,} · / }).count()).toBe(0)
  } finally {
    liberarBusquedaAntigua()
    if (inicioAntigua) await antiguaTerminada
    await page.unroute('**/api/v1/tarjetas-rfid/personas?*')
  }
})
