import { expect, test } from '@playwright/test'

test('el formulario SSR no envía credenciales por GET antes de hidratar', async ({
  browser,
  baseURL,
}) => {
  const contexto = await browser.newContext({ javaScriptEnabled: false })
  const pagina = await contexto.newPage()
  let metodo = ''
  let direccion = ''
  let cuerpo = ''
  await pagina.route('**/panel', async (ruta) => {
    if (ruta.request().method() !== 'POST') return ruta.continue()
    metodo = ruta.request().method()
    direccion = ruta.request().url()
    cuerpo = ruta.request().postData() ?? ''
    await ruta.fulfill({ status: 204, body: '' })
  })
  await pagina.goto(`${baseURL}/panel`)
  const formulario = pagina.locator('form.formulario-acceso')
  await expect(formulario).toHaveAttribute('method', 'post')
  await expect(formulario.locator('input[type="email"]')).toBeDisabled()
  await expect(formulario.locator('input[type="password"]')).toBeDisabled()
  await expect(formulario.locator('button[type="submit"]')).toBeDisabled()
  await formulario.evaluate((elemento: HTMLFormElement) => {
    for (const input of elemento.querySelectorAll('input')) input.value = 'prueba-sintetica'
    HTMLFormElement.prototype.submit.call(elemento)
  })
  await expect.poll(() => metodo).toBe('POST')
  expect(direccion).not.toContain('prueba-sintetica')
  expect(cuerpo).not.toContain('prueba-sintetica')
  await contexto.close()
})

test('la hidratación habilita el acceso sin divergencias', async ({ page }) => {
  const fallos: string[] = []
  page.on('console', (mensaje) => {
    if (/hydration|hydrating/i.test(mensaje.text()) && mensaje.type() !== 'log') {
      fallos.push(mensaje.type())
    }
  })
  await page.goto('/panel')
  await expect(page.locator('form.formulario-acceso input[type="email"]')).toBeEnabled()
  await expect(page.locator('form.formulario-acceso input[type="password"]')).toBeEnabled()
  await expect(page.locator('form.formulario-acceso button[type="submit"]')).toBeEnabled()
  expect(fallos).toEqual([])
})
