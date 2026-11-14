import { expect, test, type Locator, type Page } from '@playwright/test'
import { iniciarSesion, webUrl } from './soporte'

const rutaPersonas = '/api/v1/tarjetas-rfid/personas'
type TipoModalidad = 'PUBLICO' | 'PRIVADO' | 'MIXTO'

async function prepararModalidadSintetica(page: Page, tipoEstacionamiento: TipoModalidad) {
  await page.route('**/api/v1/tarjetas-rfid/modalidad', (ruta) =>
    ruta.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ tipoEstacionamiento }),
    }),
  )
}

async function prepararBusquedaSintetica(page: Page): Promise<void> {
  await page.route('**/api/v1/tarjetas-rfid/personas?*', async (ruta) => {
    const destino = new URL(ruta.request().url())
    const termino = destino.searchParams.get('busqueda')
    if (termino?.startsWith('zz-sin-persona')) {
      await ruta.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }
    if (termino !== 'Stage 2') return ruta.continue()
    await ruta.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          tipoEntidad: 'CLIENTE',
          codigoPersona: 'CLI-9999',
          nombreCompleto: 'Cliente Sintético UX',
          estadoAdministrativo: 'ACTIVO',
          elegible: true,
          motivoNoElegible: null,
        },
      ]),
    })
  })
}

async function abrirModal(page: Page, modalidad: TipoModalidad = 'MIXTO') {
  await prepararModalidadSintetica(page, modalidad)
  await prepararBusquedaSintetica(page)
  await iniciarSesion(page)
  await page.goto(webUrl('/admin/tarjetas-rfid'))
  const abrir = page.getByRole('button', { name: 'Asociar tarjeta', exact: true })
  await expect(abrir).toBeEnabled()
  await abrir.click()
  const dialogo = page.getByRole('dialog', { name: 'Asociar tarjeta' })
  await expect(dialogo).toBeVisible()
  return { abrir, dialogo }
}

async function esperarBusqueda(
  page: Page,
  dialogo: Locator,
  tipo: 'CLIENTE' | 'EMPLEADO',
  busqueda: string,
) {
  const respuesta = page.waitForResponse((elemento) => {
    const destino = new URL(elemento.url())
    return (
      destino.pathname === rutaPersonas &&
      destino.searchParams.get('tipoEntidad') === tipo &&
      destino.searchParams.get('busqueda') === busqueda
    )
  })
  await dialogo.getByRole('combobox', { name: 'Buscar' }).fill(busqueda)
  const resultado = await respuesta
  expect(resultado.status()).toBe(200)
  return resultado
}

async function elegirClienteStage2(page: Page, dialogo: Locator): Promise<string> {
  await dialogo.getByRole('button', { name: 'CLIENTE', exact: true }).click()
  await esperarBusqueda(page, dialogo, 'CLIENTE', 'Stage 2')
  const candidato = dialogo.getByRole('option', { name: /CLI-\d{4,}/ }).first()
  await expect(candidato).toBeVisible()
  const codigo = (await candidato.innerText()).match(/CLI-\d{4,}/)?.[0]
  expect(codigo).toBeDefined()
  await candidato.click()
  return codigo
}

test('la búsqueda editada descarta la persona anterior y Cambiar persona vuelve al selector', async ({
  page,
}) => {
  const { dialogo } = await abrirModal(page)
  const buscar = dialogo.getByRole('combobox', { name: 'Buscar' })
  const siguiente = dialogo.getByRole('button', { name: 'Siguiente', exact: true })

  const codigoSeleccionado = await elegirClienteStage2(page, dialogo)
  const cambiar = dialogo.getByRole('button', { name: 'Cambiar persona', exact: true })
  await expect(cambiar).toBeVisible()
  await expect(siguiente).toBeEnabled()
  await expect(dialogo).toContainText(codigoSeleccionado)

  // La respuesta vacía es sintética para no depender de asociaciones creadas por otras pruebas.
  await esperarBusqueda(page, dialogo, 'CLIENTE', 'zz-sin-persona-20261110')
  await expect(dialogo.getByRole('option')).toHaveCount(0)
  await expect(cambiar).toBeHidden()
  await expect(dialogo).not.toContainText(codigoSeleccionado)
  await expect(siguiente).toBeDisabled()

  await elegirClienteStage2(page, dialogo)
  await expect(cambiar).toBeVisible()
  await cambiar.click()
  await expect(buscar).toBeVisible()
  await expect(siguiente).toBeDisabled()
  await expect(dialogo.getByRole('button', { name: 'Iniciar lectura', exact: true })).toHaveCount(0)
})

test('Escape cierra primero las sugerencias y después el modal', async ({ page }) => {
  const { abrir, dialogo } = await abrirModal(page)
  await dialogo.getByRole('button', { name: 'CLIENTE', exact: true }).click()
  const buscar = dialogo.getByRole('combobox', { name: 'Buscar' })
  await esperarBusqueda(page, dialogo, 'CLIENTE', 'Stage 2')
  await expect(dialogo.getByRole('option').first()).toBeVisible()

  await buscar.press('Escape')
  await expect(dialogo).toBeVisible()
  await expect(dialogo.getByRole('option')).toHaveCount(0)
  await expect(buscar).toBeFocused()

  await page.keyboard.press('Escape')
  await expect(dialogo).toBeHidden()
  await expect(abrir).toBeFocused()
})

test('PUBLICO limita la asociación a clientes', async ({ page }) => {
  const { dialogo } = await abrirModal(page, 'PUBLICO')
  await expect(dialogo.getByRole('button', { name: 'CLIENTE', exact: true })).toBeVisible()
  await expect(dialogo.getByRole('button', { name: 'EMPLEADO', exact: true })).toHaveCount(0)
  await expect(dialogo.getByRole('button', { name: 'Mixto', exact: true })).toHaveCount(0)
})

test('PRIVADO limita la asociación a empleados', async ({ page }) => {
  const { dialogo } = await abrirModal(page, 'PRIVADO')
  await expect(dialogo.getByRole('button', { name: 'EMPLEADO', exact: true })).toBeVisible()
  await expect(dialogo.getByRole('button', { name: 'CLIENTE', exact: true })).toHaveCount(0)
  await expect(dialogo.getByRole('button', { name: 'Mixto', exact: true })).toHaveCount(0)
})

test('MIXTO ofrece ambos tipos y la consulta combinada', async ({ page }) => {
  const { dialogo } = await abrirModal(page, 'MIXTO')
  await expect(dialogo.getByRole('button', { name: 'CLIENTE', exact: true })).toBeVisible()
  await expect(dialogo.getByRole('button', { name: 'EMPLEADO', exact: true })).toBeVisible()
  await expect(dialogo.getByRole('button', { name: 'Mixto', exact: true })).toBeVisible()
})

test('el modal presenta la conexión del lector como contexto sin bloquear el flujo', async ({
  page,
}) => {
  await iniciarSesion(page)
  await prepararModalidadSintetica(page, 'PUBLICO')
  await prepararBusquedaSintetica(page)
  let iniciosCaptura = 0
  page.on('request', (solicitud) => {
    const destino = new URL(solicitud.url())
    if (destino.pathname === '/api/v1/rfid-1/capturas' && solicitud.method() === 'POST') {
      iniciosCaptura += 1
    }
  })
  await page.route('**/api/v1/rfid-1/estado-conexion', (ruta) =>
    ruta.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ estado: 'DESCONECTADO', actualizadoEn: '2026-11-10T12:00:00Z' }),
    }),
  )
  await page.goto(webUrl('/admin/tarjetas-rfid'))
  const estadoEncabezado = page.getByRole('status', {
    name: /Estado de conexión del ESP32 RFID 1/i,
  })
  await expect(estadoEncabezado).toContainText('Sin conexión')

  await page.getByRole('button', { name: 'Asociar tarjeta', exact: true }).click()
  const dialogo = page.getByRole('dialog', { name: 'Asociar tarjeta' })
  await elegirClienteStage2(page, dialogo)
  await dialogo.getByRole('button', { name: 'Siguiente', exact: true }).click()
  const estadoEnModal = dialogo.getByRole('status', { name: /conexión con el lector/i })
  await expect(estadoEnModal).toContainText('Sin conexión')
  await expect(dialogo.getByRole('button', { name: 'Iniciar lectura', exact: true })).toBeEnabled()
  expect(iniciosCaptura).toBe(0)
})
