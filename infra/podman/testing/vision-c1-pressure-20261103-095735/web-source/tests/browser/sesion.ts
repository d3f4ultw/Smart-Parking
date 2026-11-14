import { expect, type Page } from '@playwright/test'

export const baseURL =
  process.env.BASE_URL || process.env.TEST_WEB_BASE_URL || 'http://127.0.0.1:3000'

export async function iniciarSesion(page: Page): Promise<void> {
  const correo = process.env.TEST_OWNER_EMAIL
  const contrasena = process.env.TEST_OWNER_PASSWORD
  if (!correo || !contrasena)
    throw new Error('Faltan credenciales sinteticas en el entorno del runner.')

  let intentoGetConCredenciales = false
  await page.route('**/panel?*', async (route) => {
    const url = new URL(route.request().url())
    if (url.searchParams.has('correo') || url.searchParams.has('contrasena')) {
      intentoGetConCredenciales = true
      await route.abort('aborted')
      return
    }
    await route.continue()
  })

  await page.goto(`${baseURL}/panel`)
  await page.waitForLoadState('networkidle')
  await expect(page.getByRole('button', { name: 'Mostrar contraseña', exact: true })).toBeVisible()
  const campoContrasena = page.getByRole('textbox', { name: 'Contraseña' })
  await page.getByRole('button', { name: 'Mostrar contraseña', exact: true }).click()
  await expect(campoContrasena).toHaveAttribute('type', 'text')
  await page.getByRole('button', { name: 'Ocultar contraseña', exact: true }).click()
  await expect(campoContrasena).toHaveAttribute('type', 'password')

  await page.getByLabel('Correo electrónico').fill(correo)
  await campoContrasena.fill(contrasena)
  await page.getByRole('button', { name: 'Iniciar sesión' }).click({ noWaitAfter: true })
  await expect.poll(() => new URL(page.url()).pathname, { timeout: 15_000 }).toBe('/admin')
  if (intentoGetConCredenciales)
    throw new Error('Se bloqueó un submit GET con credenciales antes del envío.')
}

export async function abrirDirectorio(page: Page): Promise<void> {
  await iniciarSesion(page)
  await page.goto(`${baseURL}/admin/empleados`)
  await page.waitForFunction(() => {
    const raiz = document.querySelector('#__nuxt') as
      | (HTMLElement & { __vue_app__?: unknown })
      | null
    return Boolean(raiz?.__vue_app__)
  })
  await expect(page.getByRole('region', { name: 'Lista de empleados' }).first()).toBeVisible()
}
