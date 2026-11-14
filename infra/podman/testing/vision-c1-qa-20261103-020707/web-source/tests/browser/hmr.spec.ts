import { expect, test } from '@playwright/test'
import { readFile, writeFile } from 'node:fs/promises'

const baseURL = process.env.TEST_WEB_BASE_URL ?? 'http://web:3000'
const rutaFixture = process.env.HMR_PROBE_PATH
const fuenteV1 = '<template>\n  <main data-hmr-probe="v1">HMR empleado probe v1</main>\n</template>\n'
const fuenteV2 = '<template>\n  <main data-hmr-probe="v2">HMR empleado probe v2</main>\n</template>\n'

test('HMR actualiza la página de prueba sin navegación completa', async ({ page }) => {
  if (!rutaFixture) {
    test.skip(true, 'HMR requiere el fixture temporal montado y se omite en producción.')
    return
  }
  const fuenteActual = await readFile(rutaFixture, 'utf8')
  if (fuenteActual !== fuenteV1) await writeFile(rutaFixture, fuenteV1, 'utf8')
  try {
    await page.goto(`${baseURL}/__hmr_probe`)
    await expect(page.locator('main')).toHaveText('HMR empleado probe v1')
    await page.waitForTimeout(750)
    await page.evaluate(() => {
      ;(window as Window & { __hmrProbeMarker?: string }).__hmrProbeMarker = 'preservado'
    })

    let navegacionesDocumento = 0
    page.on('request', (request) => {
      if (request.isNavigationRequest()) navegacionesDocumento += 1
    })
    await writeFile(rutaFixture, fuenteV2, 'utf8')
    await expect(page.locator('main')).toHaveText('HMR empleado probe v2', {
      timeout: 20_000,
    })
    expect(
      await page.evaluate(() => (window as Window & { __hmrProbeMarker?: string }).__hmrProbeMarker),
    ).toBe('preservado')
    expect(navegacionesDocumento).toBe(0)
  } finally {
    await writeFile(rutaFixture, fuenteV1, 'utf8')
  }
})
