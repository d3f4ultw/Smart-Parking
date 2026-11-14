import { expect, type Page } from '@playwright/test'

const BASE_URL = process.env.BASE_URL || process.env.TEST_WEB_BASE_URL || 'http://127.0.0.1:3000'

type EscenarioRecuperacion = 'exitoso' | 'persistente' | 'anonimo'

export async function comprobarRecuperacionLogin(
  page: Page,
  correo: string,
  contrasena: string,
  destino: '/admin' | '/operador',
  escenario: EscenarioRecuperacion = 'exitoso',
): Promise<void> {
  let publicacionesSesion = 0
  let fallosVerificacionInducidos = 0
  let consultasSesion = 0

  await page.route('**/api/v1/sesion', async (ruta) => {
    const solicitud = ruta.request()
    if (solicitud.method() === 'POST') {
      publicacionesSesion += 1
      await ruta.continue()
      return
    }

    if (solicitud.method() === 'GET' && publicacionesSesion > 0) {
      consultasSesion += 1
      if (escenario === 'anonimo' && fallosVerificacionInducidos >= 2) {
        await ruta.fulfill({
          status: 401,
          contentType: 'application/json',
          body: JSON.stringify({ codigo: 'SESION_NO_VIGENTE' }),
        })
        return
      }
      if (escenario === 'persistente' || fallosVerificacionInducidos < 2) {
        fallosVerificacionInducidos += 1
        await ruta.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ codigo: 'API_NO_DISPONIBLE' }),
        })
        return
      }
    }

    await ruta.continue()
  })

  await page.goto(`${BASE_URL}/panel`)
  await page.waitForLoadState('networkidle')
  await expect(page.getByRole('textbox', { name: 'Correo electrónico' })).toBeVisible()
  await page.getByRole('textbox', { name: 'Correo electrónico' }).fill(correo)
  await page.getByRole('textbox', { name: 'Contraseña' }).fill(contrasena)

  const respuestaLogin = page.waitForResponse((respuesta) => {
    const url = new URL(respuesta.url())
    return url.pathname === '/api/v1/sesion' && respuesta.request().method() === 'POST'
  })
  await page.getByRole('button', { name: 'Iniciar sesión', exact: true }).click()
  expect((await respuestaLogin).status()).toBe(200)
  await expect(page.getByRole('alert')).toContainText('No pudimos conectar con Smart Parking')
  await expect(page.getByRole('button', { name: 'Reintentar', exact: true })).toBeVisible()
  expect(publicacionesSesion).toBe(1)
  expect(fallosVerificacionInducidos).toBe(2)

  const botonReintentar = page.getByRole('button', { name: 'Reintentar', exact: true })
  if (escenario === 'persistente') {
    for (let intento = 1; intento <= 2; intento += 1) {
      await botonReintentar.click()
      await expect.poll(() => consultasSesion).toBe(intento * 2 + 2)
      await expect(botonReintentar).toBeEnabled()
      expect(publicacionesSesion).toBe(1)
      await page.waitForTimeout(250)
      expect(consultasSesion).toBe(intento * 2 + 2)
      await expect(page).toHaveURL(/\/panel$/)
    }
    return
  }

  if (escenario === 'anonimo') {
    const verificacionAnonima = page.waitForResponse((respuesta) => {
      const url = new URL(respuesta.url())
      return (
        url.pathname === '/api/v1/sesion' &&
        respuesta.request().method() === 'GET' &&
        respuesta.status() === 401
      )
    })
    await botonReintentar.click()
    await verificacionAnonima
    await expect(page.getByRole('textbox', { name: 'Correo electrónico' })).toBeVisible()
    await expect(page.getByRole('alert')).toContainText('No encontramos una sesión activa.')
    expect(publicacionesSesion).toBe(1)
    return
  }

  const verificacionRecuperada = page.waitForResponse((respuesta) => {
    const url = new URL(respuesta.url())
    return (
      url.pathname === '/api/v1/sesion' &&
      respuesta.request().method() === 'GET' &&
      respuesta.status() === 200
    )
  })
  await botonReintentar.click()
  await verificacionRecuperada
  await expect.poll(() => new URL(page.url()).pathname).toBe(destino)
  expect(publicacionesSesion).toBe(1)
}
