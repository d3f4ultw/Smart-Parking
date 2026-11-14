import { expect, test } from '@playwright/test'
import { abrirDirectorio } from './sesion'

const ventanas = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1440, height: 900 },
]

test('panel y modal respetan viewport, teclado y movimiento reducido', async ({ page }) => {
  await abrirDirectorio(page)

  for (const ventana of ventanas) {
    await page.setViewportSize(ventana)
    await expect(page.getByRole('region', { name: 'Lista de empleados' }).first()).toBeVisible()
    const medidas = await page.evaluate(() => ({
      anchoVentana: window.innerWidth,
      anchoDocumento: document.documentElement.scrollWidth,
      anchoCuerpo: document.body.scrollWidth,
    }))
    expect(Math.max(medidas.anchoDocumento, medidas.anchoCuerpo)).toBeLessThanOrEqual(
      medidas.anchoVentana + 1,
    )

    const botonRegistro = page.getByRole('button', { name: 'Agregar empleado' }).first()
    await botonRegistro.focus()
    await page.keyboard.press('Enter')
    const dialogo = page.getByRole('dialog', { name: 'Agregar empleado' })
    await expect(dialogo).toBeVisible()
    const cuadro = await dialogo.boundingBox()
    expect(cuadro).not.toBeNull()
    expect(cuadro!.x).toBeGreaterThanOrEqual(0)
    expect(cuadro!.y).toBeGreaterThanOrEqual(0)
    expect(cuadro!.x + cuadro!.width).toBeLessThanOrEqual(ventana.width + 1)
    expect(cuadro!.y + cuadro!.height).toBeLessThanOrEqual(ventana.height + 1)
    expect(await dialogo.evaluate((elemento) => elemento.contains(document.activeElement))).toBe(
      true,
    )

    await page.keyboard.press('Shift+Tab')
    expect(await dialogo.evaluate((elemento) => elemento.contains(document.activeElement))).toBe(
      true,
    )
    await page.keyboard.press('Escape')
    await expect(dialogo).toBeHidden()
    await expect(botonRegistro).toBeFocused()
  }

  await page.emulateMedia({ reducedMotion: 'reduce' })
  expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(
    true,
  )
  await page.getByRole('button', { name: 'Agregar empleado' }).first().click()
  await expect(page.getByRole('dialog', { name: 'Agregar empleado' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Agregar empleado' })).toBeHidden()
})
