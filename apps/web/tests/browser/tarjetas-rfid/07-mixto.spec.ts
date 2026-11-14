import { expect, test } from '@playwright/test'
import { baseURL, iniciarSesion } from './soporte'

const url = (ruta: string) => new URL(ruta, baseURL).toString()

test('MIXTO se aplica al directorio y modal sin cambiar el tipo real al capturar', async ({
  page,
}) => {
  await iniciarSesion(page)

  let liberarModalidad!: () => void
  const modalidadPendiente = new Promise<void>((resolve) => {
    liberarModalidad = resolve
  })
  const consultasDirectorio: URL[] = []
  const consultasPersonas: URL[] = []

  page.on('request', (solicitud) => {
    const destino = new URL(solicitud.url())
    if (destino.pathname === '/api/v1/tarjetas-rfid') consultasDirectorio.push(destino)
    if (destino.pathname === '/api/v1/tarjetas-rfid/personas') consultasPersonas.push(destino)
  })

  await page.route('**/api/v1/panel', async (ruta) => {
    await modalidadPendiente
    await ruta.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ estacionamiento: { tipo: 'MIXTO' } }),
    })
  })
  await page.route('**/api/v1/rfid-1/estado-conexion', (ruta) =>
    ruta.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ estado: 'DESCONOCIDO', actualizadoEn: null }),
    }),
  )
  await page.route('**/api/v1/tarjetas-rfid?*', async (ruta) => {
    const destino = new URL(ruta.request().url())
    if (destino.pathname !== '/api/v1/tarjetas-rfid') return ruta.continue()
    await ruta.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], pagina: 1, tamano: 10, total: 0, totalPaginas: 0 }),
    })
  })
  await page.route('**/api/v1/rfid-1/capturas', async (ruta) => {
    if (ruta.request().method() !== 'POST') return ruta.continue()
    await ruta.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        capturaId: 'a'.repeat(32),
        estado: 'ESCANEANDO',
        expiraEn: '2026-10-29T00:05:00Z',
      }),
    })
  })

  await page.goto(url('/admin/tarjetas-rfid'))
  const botonAsociar = page.getByRole('button', { name: 'Asociar tarjeta', exact: true })
  await expect(botonAsociar).toBeDisabled()
  await expect(page.locator('section[aria-labelledby="titulo-directorio-rfid"]')).toBeVisible()

  const peticionDirectorio = page.waitForRequest((solicitud) => {
    const destino = new URL(solicitud.url())
    return (
      destino.pathname === '/api/v1/tarjetas-rfid' &&
      destino.searchParams.get('tipoEntidad') === 'MIXTO'
    )
  })
  liberarModalidad()
  const solicitudDirectorio = await peticionDirectorio
  const consultaDirectorio = new URL(solicitudDirectorio.url())
  expect(consultaDirectorio.searchParams.get('estado')).toBe('TODAS')
  expect(consultaDirectorio.searchParams.get('pagina')).toBe('1')
  await expect(botonAsociar).toBeEnabled()
  expect(consultasDirectorio).toHaveLength(1)

  const directorio = page.locator('section[aria-labelledby="titulo-directorio-rfid"]')
  await expect(directorio.getByLabel('Persona')).toHaveValue('MIXTO')
  await botonAsociar.click()

  const dialogo = page.getByRole('dialog', { name: 'Asociar tarjeta' })
  await expect(
    dialogo.getByRole('group', { name: 'Persona' }).getByRole('button', { name: 'Mixto' }),
  ).toHaveAttribute('aria-pressed', 'true')
  const busqueda = dialogo.getByRole('combobox', { name: 'Buscar' })
  await expect(busqueda).toHaveValue('')
  expect(consultasPersonas).toHaveLength(0)
  await busqueda.fill('A')
  await page.waitForTimeout(450)
  expect(consultasPersonas, 'un carácter no busca candidatos').toHaveLength(0)

  const peticionPersonas = page.waitForRequest((solicitud) => {
    const destino = new URL(solicitud.url())
    return (
      destino.pathname === '/api/v1/tarjetas-rfid/personas' &&
      destino.searchParams.get('tipoEntidad') === 'MIXTO' &&
      destino.searchParams.get('busqueda') === 'Stage 2'
    )
  })
  const respuestaPersonas = page.waitForResponse((respuesta) => {
    const destino = new URL(respuesta.url())
    return (
      destino.pathname === '/api/v1/tarjetas-rfid/personas' &&
      destino.searchParams.get('tipoEntidad') === 'MIXTO' &&
      destino.searchParams.get('busqueda') === 'Stage 2'
    )
  })
  await busqueda.fill('Stage 2')
  await page.waitForTimeout(450)
  const [solicitudPersonas, respuesta] = await Promise.all([peticionPersonas, respuestaPersonas])
  expect(new URL(solicitudPersonas.url()).searchParams.get('tipoEntidad')).toBe('MIXTO')
  const cuerpo: unknown = await respuesta.json().catch(() => null)
  const candidatos = Array.isArray(cuerpo)
    ? cuerpo.filter(
        (elemento): elemento is Record<string, unknown> =>
          typeof elemento === 'object' && elemento !== null,
      )
    : []
  const tipos = [
    ...new Set(
      candidatos.map(({ tipoEntidad }) =>
        tipoEntidad === 'CLIENTE' || tipoEntidad === 'EMPLEADO' ? tipoEntidad : 'TIPO_DESCONOCIDO',
      ),
    ),
  ].sort()
  const codigos = candidatos.map(({ tipoEntidad, codigoPersona }) => {
    const sintetico =
      typeof codigoPersona === 'string' &&
      ((tipoEntidad === 'CLIENTE' && /^CLI-\d{4,}$/.test(codigoPersona)) ||
        (tipoEntidad === 'EMPLEADO' && /^E-\d{4,}$/.test(codigoPersona)))
    return sintetico ? codigoPersona : 'CODIGO_NO_SINTETICO'
  })
  const diagnostico = { status: respuesta.status(), tipos, codigos }
  expect(
    diagnostico,
    `La respuesta MIXTO no cumple el contrato. Diagnóstico seguro: ${JSON.stringify(diagnostico)}`,
  ).toEqual(
    expect.objectContaining({
      status: 200,
      tipos: expect.arrayContaining(['CLIENTE', 'EMPLEADO']),
      codigos: expect.arrayContaining([
        expect.stringMatching(/^CLI-\d{4,}$/),
        expect.stringMatching(/^E-\d{4,}$/),
      ]),
    }),
  )
  const cliente = dialogo.getByRole('option', { name: /CLI-\d{4,}/ }).first()
  await expect(cliente).toBeVisible()
  const empleado = dialogo.getByRole('option', { name: /Empleado Stage 2 Sintetico/ }).first()
  await expect(empleado).toContainText('EMPLEADO')
  const codigoEmpleado = (await empleado.innerText()).match(/E-\d+/)?.[0]
  expect(codigoEmpleado).toBeDefined()
  expect(codigoEmpleado).toMatch(/^E-\d+/)
  await empleado.click()
  await expect(dialogo.getByText(`EMPLEADO · ${codigoEmpleado}`, { exact: true })).toBeVisible()
  await dialogo.getByRole('button', { name: 'Siguiente', exact: true }).click()

  const peticionCaptura = page.waitForRequest(
    (solicitud) =>
      new URL(solicitud.url()).pathname === '/api/v1/rfid-1/capturas' &&
      solicitud.method() === 'POST',
  )
  await dialogo.getByRole('button', { name: 'Iniciar lectura', exact: true }).click()
  const captura = await peticionCaptura
  expect(JSON.parse(captura.postData() ?? '{}')).toEqual({
    tipoEntidad: 'EMPLEADO',
    codigoPersona: codigoEmpleado,
  })
  await expect(dialogo.getByRole('heading', { name: 'Lee la tarjeta' })).toBeVisible()
})
