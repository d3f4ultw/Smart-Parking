import { mkdir, unlink, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'

const webBase = process.env.TEST_WEB_BASE_URL ?? process.env.BASE_URL ?? 'http://web:3000'

async function iniciarSesionDueno(page: Page): Promise<void> {
  const correo = process.env.TEST_OWNER_EMAIL
  const contrasena = process.env.TEST_OWNER_PASSWORD
  if (!correo || !contrasena) throw new Error('Faltan credenciales sintéticas del DUENO.')
  await page.goto(new URL('/panel', webBase).toString())
  await page.getByLabel('Correo electrónico').fill(correo)
  await page.getByRole('textbox', { name: 'Contraseña' }).fill(contrasena)
  await page.getByRole('button', { name: 'Iniciar sesión', exact: true }).click()
  await expect.poll(() => new URL(page.url()).pathname).toBe('/admin')
}

async function ejecutarAsociacionFisica(
  page: Page,
  entidad: 'CLIENTE' | 'EMPLEADO',
  nombre: string,
): Promise<void> {
  const mensajes: string[] = []
  page.on('console', (mensaje) => mensajes.push(mensaje.text()))
  const directorio = process.env.TEST_RFID1_SIGNAL_DIR
  if (!directorio) throw new Error('Falta el directorio privado de señal física.')
  const senal = join(directorio, 'physical-ready')
  await unlink(senal).catch(() => undefined)
  await iniciarSesionDueno(page)
  const ruta = entidad === 'CLIENTE' ? '/admin/clientes' : '/admin/empleados'
  await page.goto(new URL(ruta, webBase).toString())
  await expect(
    page
      .getByRole('region', {
        name: entidad === 'CLIENTE' ? 'Lista de clientes' : 'Lista de empleados',
      })
      .first(),
  ).toBeVisible()
  await page.getByRole('button', { name: `Asociar tarjeta a ${nombre}`, exact: true }).click()
  const dialogo = page.getByRole('dialog')
  await expect(dialogo).toBeVisible()
  const botonInicio = dialogo.getByRole('button', { name: 'Iniciar captura', exact: true })
  await expect(botonInicio, 'la consulta de captura activa debe terminar antes del inicio').toBeVisible({
    timeout: 15_000,
  })
  await expect(botonInicio, 'el botón de inicio debe estar habilitado').toBeEnabled({ timeout: 15_000 })
  const respuestaInicio = page.waitForResponse((respuesta) => {
    const url = new URL(respuesta.url())
    return url.pathname === '/api/v1/rfid-1/capturas' && respuesta.request().method() === 'POST'
  }, { timeout: 20_000 }).catch(() => null)
  await botonInicio.click()
  const inicio = await respuestaInicio
  if (!inicio) throw new Error('No llegó el POST físico de inicio al BFF en 20 segundos.')
  expect(inicio.status(), 'la captura física inicia mediante el BFF real').toBe(201)
  await expect(dialogo.getByRole('status')).toHaveText('Acerque la tarjeta al lector.', {
    timeout: 60_000,
  })

  // El archivo solo avisa al coordinador; no contiene UID ni credenciales.
  await mkdir(directorio, { recursive: true })
  await writeFile(senal, 'Lector listo para una presentación física.\n', { mode: 0o600 })
  await expect(dialogo.getByRole('status')).toHaveText('La tarjeta quedó asociada.', {
    timeout: 120_000,
  })

  const privado = `${await page.content()}\n${mensajes.join('\n')}`
  const token = process.env.TEST_DEVICE_TOKEN
  expect(/\b[0-9a-f]{20}\b/i.test(privado), 'la lectura física no aparece en DOM ni logs').toBe(false)
  expect(Boolean(token && privado.includes(token)), 'el Bearer no aparece en DOM ni logs').toBe(false)
}

test('asociación física CLIENTE @rfid1-fisico-cliente', async ({ page }) => {
  test.skip(process.env.TEST_RFID1_FISICA !== '1', 'Gate A no presenta tarjetas físicas.')
  test.setTimeout(150_000)
  await ejecutarAsociacionFisica(page, 'CLIENTE', 'Cliente Fisico Stage 3 Sintetico')
})

test('asociación física EMPLEADO @rfid1-fisico-empleado', async ({ page }) => {
  test.skip(process.env.TEST_RFID1_FISICA !== '1', 'Gate A no presenta tarjetas físicas.')
  test.setTimeout(150_000)
  await ejecutarAsociacionFisica(page, 'EMPLEADO', 'Empleado Fisico Sintetico')
})
