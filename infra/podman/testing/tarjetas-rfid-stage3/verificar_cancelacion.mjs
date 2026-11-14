import { chromium, expect } from '@playwright/test'

const baseURL = process.env.BASE_URL || process.env.TEST_WEB_BASE_URL || 'http://localhost:3000'
const tipoEntidad = process.argv[2] || 'CLIENTE'
const correo = process.env.TEST_OWNER_EMAIL
const contrasena = process.env.TEST_OWNER_PASSWORD

if (!['CLIENTE', 'EMPLEADO'].includes(tipoEntidad) || !correo || !contrasena) {
  console.error('Faltan credenciales sintéticas DUENO en el navegador de prueba.')
  process.exit(2)
}

const navegador = await chromium.launch({ headless: true })
let etapa = 'inicio'

try {
  const contexto = await navegador.newContext()
  const pagina = await contexto.newPage()
  etapa = 'acceso_sintetico'
  await pagina.goto(`${baseURL}/panel`)
  await pagina.getByLabel('Correo electrónico').fill(correo)
  await pagina.getByRole('textbox', { name: 'Contraseña' }).fill(contrasena)
  await pagina.getByRole('button', { name: 'Iniciar sesión' }).click()
  await pagina.waitForURL((url) => url.pathname === '/admin', { timeout: 15_000 })

  etapa = 'seleccion_cliente'
  await pagina.goto(`${baseURL}/admin/tarjetas-rfid`)
  await pagina.getByRole('button', { name: tipoEntidad, exact: true }).click()
  await pagina.getByLabel('Estado de tarjeta').selectOption('ACTIVA')
  const filaTarjeta = pagina.getByRole('row').filter({ hasText: tipoEntidad })
  await expect(filaTarjeta).toHaveCount(1)

  etapa = 'abrir_detalle'
  await filaTarjeta.getByRole('button', { name: 'Detalles', exact: true }).click()
  const detalle = pagina.getByRole('dialog', { name: 'Detalles de tarjeta' })
  const camposAntes = await detalle.locator('dl.campos-detalle-rfid > div').evaluateAll((filas) =>
    Object.fromEntries(filas.map((fila) => [
      fila.querySelector('dt')?.textContent?.trim() ?? '',
      fila.querySelector('dd')?.textContent?.trim() ?? '',
    ])),
  )
  await detalle.getByRole('button', { name: 'Cancelar tarjeta', exact: true }).click()
  await detalle.getByRole('heading', { name: 'Confirmar cancelación permanente' }).waitFor()

  etapa = 'confirmar_cancelacion'
  await detalle.getByRole('button', { name: 'Confirmar cancelación', exact: true }).click()
  await detalle.getByText('La tarjeta se canceló permanentemente.', { exact: true }).waitFor({
    state: 'visible',
    timeout: 15_000,
  })
  await expect(detalle.getByText('CANCELADA', { exact: true })).toBeVisible()
  const camposDespues = await detalle.locator('dl.campos-detalle-rfid > div').evaluateAll((filas) =>
    Object.fromEntries(filas.map((fila) => [
      fila.querySelector('dt')?.textContent?.trim() ?? '',
      fila.querySelector('dd')?.textContent?.trim() ?? '',
    ])),
  )
  for (const campo of ['UID', 'Persona', 'Tipo', 'Fecha de asociación']) {
    if (camposAntes[campo] !== camposDespues[campo]) throw new Error('DATOS_HISTORICOS_CAMBIARON')
  }

  etapa = 'verificar_historial'
  await detalle.getByRole('button', { name: 'Cerrar', exact: true }).click()
  await pagina.getByLabel('Estado de tarjeta').selectOption('CANCELADA')
  const filaCancelada = pagina.getByRole('row').filter({ hasText: 'CANCELADA' })
  await expect(filaCancelada).toHaveCount(1)

  console.log(
    `PASS_CANCELACION_${tipoEntidad}: historial CANCELADA visible; UID, persona y fecha conservados sin imprimir UID.`,
  )
} catch {
  console.error(`FAIL_CANCELACION_${tipoEntidad}: etapa ${etapa}; no se imprimieron UID ni credenciales.`)
  process.exitCode = 1
} finally {
  await navegador.close()
}
