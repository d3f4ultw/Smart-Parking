import { expect, test } from '@playwright/test'
import { abrirDirectorio } from './sesion'

test('backoff SSE crece hasta 30 segundos y vuelve a 1 segundo tras onopen', async ({ page }) => {
  test.setTimeout(140_000)
  const intentos: number[] = []
  let respuestaAbierta = false
  let respuestasAbiertas = 0
  await page.route('**/api/v1/eventos/administracion**', async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    const indice = intentos.length
    intentos.push(Date.now())
    if (indice < 6 || indice === 7) {
      await route.abort('failed')
      return
    }
    if (indice === 6) {
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': heartbeat\n\n' })
      respuestaAbierta = true
      respuestasAbiertas += 1
      return
    }
    await route.abort('failed')
  })

  await abrirDirectorio(page)
  await expect.poll(() => intentos.length, { timeout: 120_000 }).toBe(8)
  expect(respuestaAbierta).toBe(true)
  expect(respuestasAbiertas).toBe(1)

  const intervalos = intentos.slice(1).map((instante, indice) => instante - intentos[indice])
  const ventanas = [
    [500, 2_500],
    [1_000, 3_500],
    [2_000, 6_500],
    [5_000, 12_000],
    [11_000, 23_000],
    [22_000, 40_000],
  ]
  for (let indice = 0; indice < ventanas.length; indice += 1) {
    expect(intervalos[indice]).toBeGreaterThanOrEqual(ventanas[indice][0])
    expect(intervalos[indice]).toBeLessThanOrEqual(ventanas[indice][1])
  }
  expect(intervalos[6]).toBeGreaterThanOrEqual(500)
  expect(intervalos[6]).toBeLessThanOrEqual(3_500)
  console.log(`Intervalos SSE observados en ms: ${intervalos.join(',')}; ultimo tras onopen=${intervalos[6]}`)
})
