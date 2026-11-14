import { expect, test, type Page, type Route, type TestInfo } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'

const baseURL = process.env.TEST_WEB_BASE_URL ?? 'http://web:3000'
const correo = process.env.TEST_OWNER_EMAIL
const contrasena = process.env.TEST_OWNER_PASSWORD

function sanitizarMensajeCliente(mensaje: string): string {
  return mensaje
    .replace(/https?:\/\/[^\s"']+/g, '[url]')
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '[email]')
    .replace(/(correo|contrasena)=([^&\s]+)/gi, '$1=[redacted]')
}

async function guardarDiagnosticoNavegador(
  page: Page,
  testInfo: TestInfo,
  navegaciones: string[],
  respuestas: string[],
  erroresCliente: string[],
): Promise<void> {
  const dom = await page.evaluate(() => {
    const visible = (elemento: Element) => {
      const estilo = getComputedStyle(elemento)
      return estilo.visibility !== 'hidden' && estilo.display !== 'none' && elemento.getClientRects().length > 0
    }
    const textosVisibles = (selector: string) =>
      Array.from(document.querySelectorAll(selector))
        .filter(visible)
        .map((elemento) => (elemento.textContent ?? '').trim())
        .filter(Boolean)

    return {
      ruta: location.pathname,
      titulo: document.title,
      readyState: document.readyState,
      contextoSeguro: window.isSecureContext,
      randomUUID: typeof crypto.randomUUID,
      raizNuxtPresente: Boolean(document.querySelector('#__nuxt')),
      formularioAccesoPresente: Boolean(document.querySelector('form.formulario-acceso')),
      titulos: textosVisibles('h1, h2, h3'),
      etiquetas: Array.from(document.querySelectorAll('label'))
        .filter(visible)
        .map((etiqueta) => ({ texto: (etiqueta.textContent ?? '').trim(), for: etiqueta.htmlFor })),
      botones: Array.from(document.querySelectorAll('button'))
        .filter(visible)
        .map((boton) => (boton.getAttribute('aria-label') || boton.textContent || '').trim())
        .filter(Boolean),
      avisos: textosVisibles('[role="alert"], [role="status"]'),
      campos: Array.from(document.querySelectorAll('input'))
        .filter(visible)
        .map((campo) => ({
          id: campo.id,
          name: campo.getAttribute('name'),
          type: campo.getAttribute('type'),
          autocomplete: campo.getAttribute('autocomplete'),
          ariaLabel: campo.getAttribute('aria-label'),
          ariaLabelledby: campo.getAttribute('aria-labelledby'),
          etiquetasAsociadas: Array.from((campo as HTMLInputElement).labels ?? []).map((etiqueta) =>
            (etiqueta.textContent ?? '').trim(),
          ),
        })),
    }
  })
  const diagnostico = { ...dom, navegaciones, respuestasHttp: respuestas, erroresCliente }
  const ruta = testInfo.outputPath('diagnostico-navegador-sin-valores.json')
  await mkdir(dirname(ruta), { recursive: true })
  await writeFile(ruta, JSON.stringify(diagnostico, null, 2), 'utf8')
}

async function limpiarCamposYQuery(page: Page): Promise<void> {
  try {
    await page.evaluate(() => {
      for (const campo of document.querySelectorAll('input')) {
        ;(campo as HTMLInputElement).value = ''
        campo.dispatchEvent(new Event('input', { bubbles: true }))
      }
      history.replaceState(null, '', location.pathname)
    })
  } catch {
    // El frame puede haberse cerrado tras una navegación cancelada.
  }
}

async function esperarVueMontada(page: Page): Promise<void> {
  await page.waitForFunction(
    () => {
      const raiz = document.querySelector('#__nuxt') as (HTMLElement & { __vue_app__?: unknown }) | null
      return Boolean(raiz?.__vue_app__)
    },
    null,
    { timeout: 15_000 },
  )
}

async function diagnosticarFormularioRegistro(page: Page, testInfo: TestInfo, solicitudes: number) {
  const estado = await page.evaluate(() => {
    const formulario = document.querySelector('form.formulario-empleado') as HTMLFormElement | null
    const boton = Array.from(document.querySelectorAll('button')).find(
      (elemento) => elemento.textContent?.trim() === 'Registrar',
    ) as HTMLButtonElement | undefined
    return {
      ruta: location.pathname,
      formularioPresente: Boolean(formulario),
      metodo: formulario?.method ?? null,
      accion: formulario ? new URL(formulario.action).pathname : null,
      formularioValido: formulario?.checkValidity() ?? null,
      contextoSeguro: window.isSecureContext,
      randomUUID: typeof crypto.randomUUID,
      botonPresente: Boolean(boton),
      tipoBoton: boton?.type ?? null,
      botonDeshabilitado: boton?.disabled ?? null,
      campos: Array.from(formulario?.querySelectorAll('input') ?? []).map((campo) => ({
        id: campo.id,
        name: campo.getAttribute('name'),
        type: campo.getAttribute('type'),
        required: (campo as HTMLInputElement).required,
        valido: (campo as HTMLInputElement).checkValidity(),
      })),
      alertas: Array.from(document.querySelectorAll('[role="alert"]')).map((elemento) =>
        (elemento.textContent ?? '').trim(),
      ),
    }
  })
  const ruta = testInfo.outputPath('diagnostico-registro-sin-valores.json')
  await mkdir(dirname(ruta), { recursive: true })
  await writeFile(ruta, JSON.stringify({ ...estado, solicitudes }, null, 2), 'utf8')
}

async function abrirDirectorio(page: Page, testInfo: TestInfo): Promise<void> {
  if (!correo || !contrasena) {
    throw new Error('Faltan las credenciales sinteticas TEST_OWNER_EMAIL/PASSWORD.')
  }

  const navegaciones: string[] = []
  const respuestas: string[] = []
  const erroresCliente: string[] = []
  page.on('framenavigated', (frame) => {
    if (frame !== page.mainFrame()) return
    try {
      navegaciones.push(new URL(frame.url()).pathname)
    } catch {
      // Omite las URL transitorias que no se pueden analizar.
    }
  })
  page.on('response', (response) => {
    const url = new URL(response.url())
    if (
      url.pathname.startsWith('/api/v1/sesion') ||
      url.pathname === '/api/v1/empleados' ||
      url.pathname === '/api/v1/eventos/administracion'
    ) {
      respuestas.push(`${response.request().method()} ${url.pathname} ${response.status()}`)
    }
  })
  page.on('pageerror', (error) => {
    erroresCliente.push(`pageerror:${error.name}:${sanitizarMensajeCliente(error.message)}`)
  })
  page.on('console', (mensaje) => {
    if (mensaje.type() === 'error') {
      erroresCliente.push(`console:${sanitizarMensajeCliente(mensaje.text())}`)
    }
  })

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
  try {
    await page.waitForLoadState('networkidle')
    const entornoSeguro = await page.evaluate(() => ({
      contextoSeguro: window.isSecureContext,
      randomUUID: typeof crypto.randomUUID,
    }))
    if (!entornoSeguro.contextoSeguro || entornoSeguro.randomUUID !== 'function') {
      throw new Error('Chromium no expone randomUUID en contexto seguro.')
    }
    await expect(page.getByRole('button', { name: 'Mostrar contraseña', exact: true })).toBeVisible()
    const campoContrasena = page.getByRole('textbox', { name: 'Contraseña' })
    await page.getByRole('button', { name: 'Mostrar contraseña', exact: true }).click()
    await expect(campoContrasena).toHaveAttribute('type', 'text')
    await page.getByRole('button', { name: 'Ocultar contraseña', exact: true }).click()
    await expect(campoContrasena).toHaveAttribute('type', 'password')
    await expect(page.getByLabel('Correo electrónico')).toBeVisible()
  } catch (fallo) {
    await guardarDiagnosticoNavegador(page, testInfo, navegaciones, respuestas, erroresCliente)
    throw new Error('El formulario no se hidrató o no expuso la interacción esperada; valores omitidos.')
  }

  let estadoLogin: number | undefined
  page.on('response', (response) => {
    const url = new URL(response.url())
    if (url.pathname === '/api/v1/sesion' && response.request().method() === 'POST') {
      estadoLogin = response.status()
    }
  })
  try {
    await page.getByLabel('Correo electrónico').fill(correo)
    await page.getByRole('textbox', { name: 'Contraseña' }).fill(contrasena)
    await page.getByRole('button', { name: 'Iniciar sesión' }).click({ noWaitAfter: true })
    const limite = Date.now() + 15_000
    while (Date.now() < limite) {
      const ruta = new URL(page.url()).pathname
      if (intentoGetConCredenciales || ruta === '/admin' || ruta.startsWith('/admin/')) break
      await page.waitForTimeout(100)
    }
    if (intentoGetConCredenciales) {
      throw new Error('Se bloqueó un submit GET con credenciales antes del envío.')
    }
    if (new URL(page.url()).pathname !== '/admin') {
      throw new Error('El login de UI no llegó a la ruta administrativa.')
    }
    if (estadoLogin !== 200) throw new Error('El login de UI no confirmó HTTP 200 por BFF.')
  } catch (fallo) {
    await limpiarCamposYQuery(page)
    await guardarDiagnosticoNavegador(page, testInfo, navegaciones, respuestas, erroresCliente)
    const mensaje = intentoGetConCredenciales
      ? 'Se bloqueó un submit GET con credenciales antes del envío.'
      : 'El login de UI no se completó; valores omitidos.'
    throw new Error(mensaje)
  }

  await page.goto(`${baseURL}/admin/empleados`)
  await esperarVueMontada(page)
  await expect(page.getByRole('region', { name: 'Lista de empleados' })).toBeVisible()
  expect(new URL(page.url()).pathname).toBe('/admin/empleados')
}

function nombreSintetico(): string {
  return `Prueba-${crypto.randomUUID().slice(0, 8)}`
}

test('SSR e hidratacion no duplican la lectura del directorio en el navegador', async ({ page }, testInfo) => {
  let lecturasBff = 0
  const conteosBff: number[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (request.method() === 'GET' && url.pathname === '/api/v1/empleados') lecturasBff += 1
  })

  await abrirDirectorio(page, testInfo)
  await page.waitForTimeout(500)
  conteosBff.push(lecturasBff)
  lecturasBff = 0
  await page.goto(`${baseURL}/admin/empleados`)
  await expect(page.getByRole('region', { name: 'Lista de empleados' })).toBeVisible()
  await page.waitForTimeout(750)
  expect(lecturasBff, 'la hidratacion no debe duplicar la lectura SSR').toBeLessThanOrEqual(1)
  conteosBff.push(lecturasBff)

  lecturasBff = 0
  await page.reload()
  await expect(page.getByRole('region', { name: 'Lista de empleados' })).toBeVisible()
  await page.waitForTimeout(750)
  expect(lecturasBff, 'la recarga completa no debe duplicar la lectura SSR').toBeLessThanOrEqual(1)
  conteosBff.push(lecturasBff)
  console.log(`GET BFF /api/v1/empleados por carga de navegador: ${conteosBff.join(',')}`)
})

test('reintenta el registro ambiguo con la misma clave y crea otra clave al cambiar datos', async ({ page }, testInfo) => {
  await abrirDirectorio(page, testInfo)
  const nombres = nombreSintetico()
  const intentos: Array<{ clave: string | undefined; cuerpo: Record<string, unknown>; respuesta: string }> = []
  let solicitudes = 0
  let intercepciones = 0
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (request.method() === 'POST' && url.pathname === '/api/v1/empleados') solicitudes += 1
  })

  await page.route('**/api/v1/empleados', async (route: Route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const request = route.request()
    const cuerpo = request.postDataJSON() as Record<string, unknown>
    const respuesta = await route.fetch()
    const textoRespuesta = await respuesta.text()
    intentos.push({
      clave: request.headers()['idempotency-key'],
      cuerpo,
      respuesta: textoRespuesta,
    })

    if (intentos.length === 1) {
      expect(respuesta.status()).toBe(201)
      await route.abort('failed')
      return
    }
    await route.fulfill({ response: respuesta, body: textoRespuesta })
  })

  await page.getByRole('button', { name: 'Registrar empleado' }).first().click()
  await expect(page.getByRole('dialog', { name: 'Registrar empleado' })).toBeVisible()
  await page.getByLabel('Nombres').fill(` ${nombres} `)
  await page.getByLabel('Primer apellido').fill(' Prueba ')
  await page.getByLabel('Segundo apellido (opcional)').fill(' Segundo ')
  await page.getByRole('button', { name: 'Registrar', exact: true }).click()

  try {
    await expect.poll(() => solicitudes, { timeout: 4_000 }).toBe(1)
    await expect.poll(() => intentos.length, { timeout: 8_000 }).toBe(1)
  } catch {
    await diagnosticarFormularioRegistro(page, testInfo, solicitudes)
    throw new Error('El primer submit no completó una petición POST; consulta el diagnóstico sin valores.')
  }
  await expect(page.getByRole('alert')).toContainText('Conservamos los datos')
  await expect(page.getByLabel('Nombres')).toHaveValue(` ${nombres} `)
  await expect(page.getByLabel('Primer apellido')).toHaveValue(' Prueba ')
  await expect(page.getByLabel('Segundo apellido (opcional)')).toHaveValue(' Segundo ')
  await page.getByRole('button', { name: 'Registrar', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Registrar empleado' })).toBeHidden()

  expect(intentos).toHaveLength(2)
  expect(intentos[0].clave).toBeTruthy()
  expect(intentos[1].clave).toBe(intentos[0].clave)
  expect(intentos[1].cuerpo).toEqual(intentos[0].cuerpo)
  expect(intentos[0].cuerpo).toEqual({
    nombres,
    primerApellido: 'Prueba',
    segundoApellido: 'Segundo',
  })
  expect(intentos[1].respuesta).toBe(intentos[0].respuesta)

  await page.getByRole('button', { name: 'Registrar empleado' }).first().click()
  const nombreCambiado = `${nombres}-cambio`
  await page.getByLabel('Nombres').fill(nombreCambiado)
  await page.getByLabel('Primer apellido').fill('Prueba')
  await page.getByLabel('Segundo apellido (opcional)').fill('Segundo')
  await page.getByRole('button', { name: 'Registrar', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Registrar empleado' })).toBeHidden()

  expect(intentos).toHaveLength(3)
  expect(intentos[2].clave).toBeTruthy()
  expect(intentos[2].clave).not.toBe(intentos[1].clave)
  expect(intentos[2].cuerpo.nombres).toBe(nombreCambiado)
})

test('ignora un segundo submit mientras el primer alta sigue pendiente', async ({ page }, testInfo) => {
  await abrirDirectorio(page, testInfo)
  await page.getByRole('button', { name: 'Registrar empleado' }).first().click()
  await page.getByLabel('Nombres').fill(nombreSintetico())
  await page.getByLabel('Primer apellido').fill('Doble')
  await page.getByLabel('Segundo apellido (opcional)').fill('')

  let solicitudes = 0
  let intercepciones = 0
  let liberar!: () => void
  const barrera = new Promise<void>((resolve) => {
    liberar = resolve
  })
  await page.route('**/api/v1/empleados', async (route: Route) => {
    if (route.request().method() !== 'POST') return route.continue()
    intercepciones += 1
    await barrera
    return route.continue()
  })
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (request.method() === 'POST' && url.pathname === '/api/v1/empleados') solicitudes += 1
  })

  try {
    await page.getByRole('button', { name: 'Registrar', exact: true }).evaluate((boton) => {
      ;(boton as HTMLButtonElement).click()
      ;(boton as HTMLButtonElement).click()
    })
    await expect.poll(() => solicitudes).toBe(1)
    await expect.poll(() => intercepciones).toBe(1)
    await expect(page.getByRole('button', { name: 'Registrar', exact: true })).toBeDisabled()
    await page.waitForTimeout(400)
    expect(solicitudes).toBe(1)
  } finally {
    liberar()
  }

  await expect(page.getByRole('dialog', { name: 'Registrar empleado' })).toBeHidden()
  expect(solicitudes).toBe(1)
})
