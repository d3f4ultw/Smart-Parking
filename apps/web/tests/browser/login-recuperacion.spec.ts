import { expect, test } from '@playwright/test'
import { comprobarRecuperacionLogin } from './recuperacion-login'

test('DUENO recupera la sesión existente sin repetir el inicio de sesión', async ({ page }) => {
  const correo = process.env.TEST_OWNER_EMAIL
  const contrasena = process.env.TEST_OWNER_PASSWORD
  if (!correo || !contrasena) {
    throw new Error('Faltan credenciales sintéticas DUENO en el entorno del runner.')
  }

  await comprobarRecuperacionLogin(page, correo, contrasena, '/admin')
  await expect(page.locator('.resumen-estacionamiento')).toBeVisible()
})

test('GET de sesión persistentemente fallido ofrece reintentos manuales sin repetir el POST', async ({
  page,
}) => {
  const correo = process.env.TEST_OWNER_EMAIL
  const contrasena = process.env.TEST_OWNER_PASSWORD
  if (!correo || !contrasena) {
    throw new Error('Faltan credenciales sintéticas DUENO en el entorno del runner.')
  }

  await comprobarRecuperacionLogin(page, correo, contrasena, '/admin', 'persistente')
  await expect(page.getByRole('alert')).toContainText('No pudimos conectar con Smart Parking')
  await expect(page.getByRole('button', { name: 'Reintentar', exact: true })).toBeEnabled()
})

test('la sesión anónima tras verificar restaura el formulario sin reenviar credenciales', async ({
  page,
}) => {
  const correo = process.env.TEST_OWNER_EMAIL
  const contrasena = process.env.TEST_OWNER_PASSWORD
  if (!correo || !contrasena) {
    throw new Error('Faltan credenciales sintéticas DUENO en el entorno del runner.')
  }

  await comprobarRecuperacionLogin(page, correo, contrasena, '/admin', 'anonimo')
})
