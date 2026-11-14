import { chromium } from '@playwright/test'
import { createInterface } from 'node:readline/promises'
import { stdin, stdout } from 'node:process'

const tipoEntidad = process.argv[2]
const modo = process.argv[3] || 'ASOCIAR'
const baseURL = process.env.BASE_URL || process.env.TEST_WEB_BASE_URL || 'http://localhost:3000'
const correo = process.env.TEST_OWNER_EMAIL
const contrasena = process.env.TEST_OWNER_PASSWORD

if (
  !['CLIENTE', 'EMPLEADO'].includes(tipoEntidad) ||
  !['ASOCIAR', 'RECHAZO_HISTORICO', 'CANCELAR_PREVIA'].includes(modo) ||
  !correo ||
  !contrasena
) {
  console.error('Falta el tipo de flujo o la sesión sintética DUENO.')
  process.exit(2)
}

const entrada = createInterface({ input: stdin, output: stdout })
const navegador = await chromium.launch({ headless: true })

try {
  const contexto = await navegador.newContext()
  const pagina = await contexto.newPage()
  await pagina.goto(`${baseURL}/panel`)
  await pagina.getByLabel('Correo electrónico').fill(correo)
  await pagina.getByRole('textbox', { name: 'Contraseña' }).fill(contrasena)
  await pagina.getByRole('button', { name: 'Iniciar sesión' }).click()
  await pagina.waitForURL((url) => url.pathname === '/admin', { timeout: 15_000 })
  await pagina.goto(`${baseURL}/admin/tarjetas-rfid`)

  await pagina.getByRole('button', { name: 'Asociar tarjeta', exact: true }).click()
  const dialogo = pagina.getByRole('dialog', { name: 'Asociar tarjeta' })
  if (tipoEntidad === 'EMPLEADO') {
    await dialogo.getByRole('button', { name: 'EMPLEADO', exact: true }).click()
  }
  await dialogo.getByRole('combobox', { name: 'Buscar persona' }).fill('Stage 2')
  const candidata = tipoEntidad === 'CLIENTE'
    ? dialogo.getByRole('option', { name: /^CLI-\d{4,} · / }).first()
    : dialogo.getByRole('option', { name: /Empleado Stage 2 Sintetico/ }).first()
  await candidata.waitFor({ state: 'visible', timeout: 10_000 })
  await candidata.click()
  await dialogo.getByRole('button', { name: 'Siguiente', exact: true }).click()

  const inicio = pagina.waitForResponse((respuesta) =>
    new URL(respuesta.url()).pathname === '/api/v1/rfid-1/capturas' &&
    respuesta.request().method() === 'POST',
  )
  await dialogo.getByRole('button', { name: 'Iniciar lectura', exact: true }).click()
  if ((await (await inicio).status()) !== 201) throw new Error('CAPTURA_NO_INICIADA')

  console.log(`LISTO_${tipoEntidad}: presenta ahora la tarjeta física asignada a este flujo.`)
  await dialogo.getByText('3. Revisar y confirmar', { exact: true }).waitFor({
    state: 'visible',
    timeout: 110_000,
  })
  console.log('VISTA_PREVIA_LISTA: retira ahora la tarjeta y déjala lejos del lector.')

  const retirada = (await entrada.question('Cuando la tarjeta esté retirada, escribe RETIRADA: '))
    .trim()
    .toUpperCase()
  if (retirada !== 'RETIRADA') throw new Error('CONFIRMACION_DE_RETIRO_INVALIDA')

  if (modo === 'CANCELAR_PREVIA') {
    const cancelacion = pagina.waitForResponse((respuesta) =>
      new URL(respuesta.url()).pathname.startsWith('/api/v1/rfid-1/capturas/') &&
      respuesta.request().method() === 'DELETE',
    )
    await dialogo.getByRole('button', { name: 'Cancelar captura', exact: true }).click()
    if (!(await cancelacion).ok()) throw new Error('CAPTURA_PREVIA_NO_CANCELADA')
    await dialogo.getByRole('button', { name: 'Cerrar', exact: true }).click()
    await dialogo.waitFor({ state: 'hidden', timeout: 10_000 })
    console.log('PASS_CANCELAR_PREVIA: captura cancelada después de retirar la tarjeta; sin UID impreso.')
  } else {
    const confirmacion = pagina.waitForResponse((respuesta) =>
      new URL(respuesta.url()).pathname.endsWith('/confirmacion') &&
      respuesta.request().method() === 'POST',
    )
    await dialogo.getByRole('button', { name: 'Confirmar asociación', exact: true }).click()
    const respuestaConfirmacion = await confirmacion

    if (modo === 'RECHAZO_HISTORICO') {
    if (respuestaConfirmacion.status() !== 409) throw new Error('UID_HISTORICO_NO_RECHAZADO')

    const cancelacion = pagina.waitForResponse((respuesta) =>
      new URL(respuesta.url()).pathname.startsWith('/api/v1/rfid-1/capturas/') &&
      respuesta.request().method() === 'DELETE',
    )
    await dialogo.getByRole('button', { name: 'Cancelar captura', exact: true }).click()
    if (!(await cancelacion).ok()) throw new Error('CAPTURA_DUPLICADA_NO_CANCELADA')
    await dialogo.getByRole('button', { name: 'Cerrar', exact: true }).click()

    await pagina.getByRole('button', { name: 'Asociar tarjeta', exact: true }).click()
    const nuevaAsociacion = pagina.getByRole('dialog', { name: 'Asociar tarjeta' })
    await nuevaAsociacion.getByRole('button', { name: 'CLIENTE', exact: true }).click()
    await nuevaAsociacion.getByRole('combobox', { name: 'Buscar persona' }).fill('Stage 2')
    const clienteElegible = nuevaAsociacion.getByRole('option', { name: /^CLI-\d{4,} · / }).first()
    await clienteElegible.waitFor({ state: 'visible', timeout: 10_000 })
    await clienteElegible.click()
    await expect(nuevaAsociacion.getByRole('button', { name: 'Siguiente', exact: true })).toBeEnabled()
    console.log('PASS_RECHAZO_HISTORICO: UID cancelado rechazado; captura cancelada y CLIENTE elegible; sin UID impreso.')
    } else {
      if (respuestaConfirmacion.status() !== 200) throw new Error('CONFIRMACION_API_FALLIDA')
      await dialogo.waitFor({ state: 'hidden', timeout: 10_000 })

      const directorio = await contexto.request.get(
        new URL(`/api/v1/tarjetas-rfid?tipoEntidad=${tipoEntidad}&estado=ACTIVA&pagina=1`, baseURL),
      )
      if (directorio.status() !== 200) throw new Error('DIRECTORIO_NO_DISPONIBLE')
      const cuerpo = await directorio.json()
      if (!Number.isInteger(cuerpo.total) || cuerpo.total < 1) throw new Error('ASOCIACION_NO_VISIBLE')
      console.log(`PASS_${tipoEntidad}: preview recibida, retiro indicado y confirmación explícita completada.`)
    }
  }
} catch (error) {
  console.error(`FAIL_${tipoEntidad}: el flujo físico no terminó; no se muestran datos RFID ni credenciales.`)
  process.exitCode = 1
} finally {
  entrada.close()
  await navegador.close()
}
