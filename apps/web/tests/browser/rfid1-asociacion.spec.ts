import { createHash, randomBytes, randomUUID } from 'node:crypto'
import { expect, test, type Locator, type Page, type Route } from '@playwright/test'

const webBase = process.env.TEST_WEB_BASE_URL ?? process.env.BASE_URL ?? 'http://web:3000'
const apiBase = process.env.TEST_API_BASE_URL ?? 'http://api:8080'
const clienteSimulado = 'Cliente Stage 3 Sintetico'
const empleadoSimulado = 'Empleado Stage3 Sintetico'
const clienteFisico = 'Cliente Fisico Stage 3 Sintetico'
const empleadoFisico = 'Empleado Fisico Sintetico'
const rutaCapturas = '/api/v1/rfid-1/capturas'

type InicioCaptura = { capturaId: string; estado: string; expiraEn: string }
type ResultadoLectura = { capturaId: string; estado: string; resultado: string | null }

function webUrl(ruta: string): string {
  return new URL(ruta, webBase).toString()
}

async function iniciarSesionDueno(page: Page): Promise<void> {
  const correo = process.env.TEST_OWNER_EMAIL
  const contrasena = process.env.TEST_OWNER_PASSWORD
  if (!correo || !contrasena) throw new Error('Faltan credenciales sintéticas del DUENO.')
  await page.goto(webUrl('/panel'))
  await page.getByLabel('Correo electrónico').fill(correo)
  await page.getByRole('textbox', { name: 'Contraseña' }).fill(contrasena)
  await page.getByRole('button', { name: 'Iniciar sesión', exact: true }).click()
  await expect.poll(() => new URL(page.url()).pathname).toBe('/admin')
}
async function iniciarSesionCliente(page: Page): Promise<void> {
  const correo = process.env.TEST_CLIENT_EMAIL
  const contrasena = process.env.TEST_CLIENT_PASSWORD
  if (!correo || !contrasena) throw new Error('Faltan credenciales sintéticas de CLIENTE.')
  await page.goto(webUrl('/clientes/acceso'))
  await page.getByLabel('Correo electrónico').fill(correo)
  await page.getByRole('textbox', { name: 'Contraseña' }).fill(contrasena)
  await page.getByRole('button', { name: 'Iniciar sesión', exact: true }).click()
  await expect.poll(() => new URL(page.url()).pathname).toBe('/clientes/portal')
}
async function abrirModal(page: Page, nombre: string, ruta: '/admin/clientes' | '/admin/empleados') {
  if (new URL(page.url()).pathname !== ruta) await page.goto(webUrl(ruta))
  await expect(page.getByRole('region', { name: ruta.endsWith('clientes') ? 'Lista de clientes' : 'Lista de empleados' }).first()).toBeVisible()
  await page.getByRole('button', { name: `Asociar tarjeta a ${nombre}`, exact: true }).click()
  const dialogo = page.getByRole('dialog')
  await expect(dialogo).toBeVisible()
  await expect(dialogo).toContainText(nombre)
  await expect(dialogo.getByRole('status')).toBeVisible()
  return dialogo
}
async function jsonSeguro<T>(respuesta: { json(): Promise<unknown> }): Promise<T> {
  try {
    return (await respuesta.json()) as T
  } catch {
    throw new Error('La respuesta del servicio no contiene JSON válido.')
  }
}
async function esperarBotonInicio(dialogo: Locator) {
  const boton = dialogo.getByRole('button', { name: /^Iniciar(?: otra)? captura$/ })
  await expect(boton, 'la captura solo puede iniciarse cuando la consulta activa terminó').toBeVisible({ timeout: 15_000 })
  await expect(boton, 'el control de inicio debe estar habilitado').toBeEnabled({ timeout: 15_000 })
  return boton
}
async function iniciarCaptura(
  page: Page,
  dialogo: Locator,
  comprobarEspera = false,
  repetirInicio = false,
): Promise<InicioCaptura> {
  const boton = await esperarBotonInicio(dialogo)
  const respuestaInicio = page.waitForResponse((respuesta) => new URL(respuesta.url()).pathname === rutaCapturas && respuesta.request().method() === 'POST', { timeout: 20_000 }).catch(() => null)
  await boton.click()
  if (comprobarEspera) {
    await expect(dialogo.getByRole('status')).toHaveText('Preparando la captura…')
  }
  const respuesta = await respuestaInicio
  if (!respuesta) throw new Error('No se observó la respuesta POST de inicio de captura.')
  expect(respuesta.status(), 'el DUENO debe iniciar por el BFF real').toBe(201)
  const inicio = await jsonSeguro<InicioCaptura>(respuesta)
  if (repetirInicio) {
    const solicitud = respuesta.request()
    const encabezados = await solicitud.allHeaders()
    const clave = encabezados['idempotency-key']
    const csrf = encabezados['x-csrf-token']
    expect(Boolean(clave && csrf), 'el inicio conserva idempotencia y CSRF').toBe(true)
    const repeticion = await page.context().request.post(webUrl(rutaCapturas), {
      data: solicitud.postDataJSON(),
      headers: { 'Idempotency-Key': clave ?? '', 'X-CSRF-TOKEN': csrf ?? '' },
    })
    expect(repeticion.status(), 'el replay autorizado debe ser aceptado').toBe(201)
    const inicioRepetido = await jsonSeguro<InicioCaptura>(repeticion)
    expect(inicioRepetido.capturaId === inicio.capturaId, 'el replay conserva la captura').toBe(true)
  }
  return inicio
}
function claveLecturaV5(capturaId: string, requestId: string): string {
  const entrada = Buffer.concat([Buffer.from(capturaId, 'hex'), Buffer.from(requestId.toUpperCase(), 'ascii')])
  const hash = createHash('sha1').update(entrada).digest()
  hash[6] = (hash[6] & 0x0f) | 0x50
  hash[8] = (hash[8] & 0x3f) | 0x80
  const uuid = hash.subarray(0, 16).toString('hex')
  return `${uuid.slice(0, 8)}-${uuid.slice(8, 12)}-${uuid.slice(12, 16)}-${uuid.slice(16, 20)}-${uuid.slice(20)}`
}
// Las llamadas simuladas al dispositivo se originan solo en Node; el Bearer nunca pasa a page/window.
async function solicitarDispositivo(
  ruta: string,
  metodo: 'GET' | 'POST',
  cuerpo?: Record<string, string>,
  clave?: string,
): Promise<Response> {
  const token = process.env.TEST_DEVICE_TOKEN
  if (!token) throw new Error('Falta el token sintético de dispositivo en el runner.')
  const encabezados: Record<string, string> = { Authorization: `Bearer ${token}` }
  if (cuerpo) encabezados['Content-Type'] = 'application/json'
  if (clave) encabezados['Idempotency-Key'] = clave
  return fetch(new URL(ruta, apiBase), {
    method: metodo,
    headers: encabezados,
    body: cuerpo ? JSON.stringify(cuerpo) : undefined,
  })
}
async function marcarEscaneando(capturaId: string): Promise<void> {
  const respuesta = await solicitarDispositivo(
    `/api/v1/dispositivos/rfid-1/capturas/${capturaId}/estado`,
    'POST',
    { estado: 'ESCANEANDO' },
  )
  expect(respuesta.status, 'el estado físico se confirma en API').toBe(204)
}
async function leerSintetico(
  capturaId: string,
  requestId: string,
  uid: string,
): Promise<{ respuesta: Response; resultado: ResultadoLectura | null }> {
  const respuesta = await solicitarDispositivo(
    '/api/v1/dispositivos/rfid-1/lecturas',
    'POST',
    { capturaId, requestId, uid },
    claveLecturaV5(capturaId, requestId),
  )
  if (!respuesta.ok) return { respuesta, resultado: null }
  return { respuesta, resultado: await jsonSeguro<ResultadoLectura>(respuesta) }
}
function contieneDatoPrivado(texto: string, uid?: string): boolean {
  const token = process.env.TEST_DEVICE_TOKEN
  return Boolean(/\b[0-9a-f]{20}\b/i.test(texto) || (uid && texto.toUpperCase().includes(uid)) || (token && texto.includes(token)))
}

async function revisarSinDatosPrivados(page: Page, uid?: string, mensajes: string[] = []): Promise<void> {
  const html = await page.content()
  const datosHidratacion = await page.locator('#__NUXT_DATA__').allTextContents().catch(() => [])
  expect(contieneDatoPrivado(`${html}\n${datosHidratacion.join('\n')}\n${mensajes.join('\n')}`, uid), 'HTML, hydration y logs del navegador no deben contener UID ni Bearer').toBe(false)
}

test('SSR, sesión, hidratación y navegación CSR conservan el límite DUENO', async ({ browser, page }) => {
  const anonima = await page.context().request.get(webUrl(`${rutaCapturas}/activa`))
  expect(anonima.status(), 'la consulta anónima requiere sesión').toBe(401)
  const contextoInvalido = await browser.newContext()
  const cookieInvalida = await contextoInvalido.request.get(webUrl(`${rutaCapturas}/activa`), {
    headers: { Cookie: `JSESSIONID=${randomUUID()}` },
  })
  expect(cookieInvalida.status(), 'un JSESSIONID inválido no autentica').toBe(401)
  await contextoInvalido.close()
  await page.context().addCookies([
    {
      name: 'JSESSIONID',
      value: randomUUID(),
      url: webBase,
      expires: Math.floor(Date.now() / 1_000) + 1,
      httpOnly: true,
      sameSite: 'Strict',
    },
  ])
  await page.waitForTimeout(1_200)
  await page.goto(webUrl('/admin/clientes'))
  await expect(page).toHaveURL(/\/panel$/)
  await iniciarSesionDueno(page)
  let iniciosBff = 0
  let documentos = 0
  page.on('request', (solicitud) => {
    const url = new URL(solicitud.url())
    if (url.pathname === rutaCapturas && solicitud.method() === 'POST') iniciosBff += 1
    if (solicitud.resourceType() === 'document') documentos += 1
  })
  const respuestaSsr = await page.goto(webUrl('/admin/clientes'))
  expect(respuestaSsr?.status(), 'la ruta protegida se renderiza por SSR con sesión DUENO').toBe(200)
  const htmlSsr = (await respuestaSsr?.text()) ?? ''
  expect(contieneDatoPrivado(htmlSsr), 'SSR no filtra UID ni Bearer').toBe(false)
  await expect(page.getByRole('region', { name: 'Lista de clientes' }).first()).toBeVisible()
  await page.reload()
  await expect(page.getByRole('region', { name: 'Lista de clientes' }).first()).toBeVisible()
  expect(iniciosBff, 'SSR e hidratación no crean capturas').toBe(0)
  const documentosAntesCsr = documentos
  await page.getByRole('link', { name: 'Empleados', exact: true }).click()
  await expect(page).toHaveURL(/\/admin\/empleados$/)
  expect(documentos, 'la navegación Nuxt no recarga el documento').toBe(documentosAntesCsr)
  await page.goBack()
  await expect(page).toHaveURL(/\/admin\/clientes$/)
  await page.goForward()
  await expect(page).toHaveURL(/\/admin\/empleados$/)
  expect(iniciosBff, 'back/forward tampoco inicia capturas').toBe(0)
  const csrfRechazado = await page.context().request.post(webUrl(rutaCapturas), {
    data: { tipoEntidad: 'CLIENTE', codigoPersona: 'PRUEBA-CSRF' },
    headers: { 'X-CSRF-TOKEN': 'csrf-sintetico-incorrecto', 'Idempotency-Key': randomUUID() },
  })
  expect(csrfRechazado.status(), 'un CSRF incorrecto se rechaza').toBe(403)
  await revisarSinDatosPrivados(page)
})

test('CLIENTE autenticado no puede consultar ni iniciar capturas de administración', async ({ page }) => {
  await iniciarSesionCliente(page)
  const respuesta = await page.context().request.get(webUrl(`${rutaCapturas}/activa`))
  expect(respuesta.status(), 'la ruta administrativa no reenvía sesión CLIENTE').toBe(401)
  await page.goto(webUrl('/admin/clientes'))
  await expect(page).toHaveURL(/\/panel$/)
  await expect(page.getByRole('region', { name: 'Lista de clientes' })).toHaveCount(0)
})
test('DUENO opera ambas entidades con recuperación, reconciliación y lecturas sintéticas', async ({ page }) => {
  test.setTimeout(240_000)
  const mensajesNavegador: string[] = []
  page.on('console', (mensaje) => mensajesNavegador.push(mensaje.text()))
  await iniciarSesionDueno(page)
  await page.goto(webUrl('/admin/clientes'))
  let solicitudesInicio = 0
  page.on('request', (solicitud) => {
    if (new URL(solicitud.url()).pathname === rutaCapturas && solicitud.method() === 'POST') solicitudesInicio += 1
  })
  const modalCliente = await abrirModal(page, clienteSimulado, '/admin/clientes')
  const uidCliente = randomBytes(10).toString('hex').toUpperCase()
  const demoraInicio: (route: Route) => Promise<void> = async (route) => {
    await page.waitForTimeout(700)
    await route.continue()
  }
  await page.route('**/api/v1/rfid-1/capturas', demoraInicio)
  const inicioCliente = await iniciarCaptura(page, modalCliente, true, true)
  await page.unroute('**/api/v1/rfid-1/capturas', demoraInicio)
  expect(solicitudesInicio, 'un click inicia una sola solicitud del navegador').toBe(1)
  const activa = await solicitarDispositivo('/api/v1/dispositivos/rfid-1/capturas/activa', 'GET')
  expect(activa.status, 'el dispositivo consulta el estado autoritativo').toBe(200)
  const estadoActivo = await jsonSeguro<InicioCaptura>(activa)
  expect(estadoActivo.capturaId === inicioCliente.capturaId, 'API conserva la captura iniciada').toBe(true)
  await marcarEscaneando(inicioCliente.capturaId)
  await expect(modalCliente.getByRole('status')).toHaveText('Acerque la tarjeta al lector.', {
    timeout: 12_000,
  })
  const lectura = await leerSintetico(inicioCliente.capturaId, 'A101', uidCliente)
  expect(lectura.respuesta.status, 'la lectura simulada llega desde Node al API').toBe(200)
  expect(lectura.resultado?.estado).toBe('COMPLETADA')
  expect(lectura.resultado?.resultado).toBeTruthy()
  const repetida = await leerSintetico(inicioCliente.capturaId, 'A101', uidCliente)
  expect(repetida.respuesta.status, 'el replay UUIDv5 devuelve el resultado existente').toBe(200)
  expect(
    repetida.resultado?.capturaId === lectura.resultado?.capturaId &&
      repetida.resultado?.estado === lectura.resultado?.estado &&
      repetida.resultado?.resultado === lectura.resultado?.resultado,
    'una lectura repetida no cambia el resultado público',
  ).toBe(true)
  await expect(modalCliente.getByRole('status')).toHaveText('La tarjeta quedó asociada.', {
    timeout: 12_000,
  })
  await revisarSinDatosPrivados(page, uidCliente, mensajesNavegador)
  await page.keyboard.press('Escape')
  await expect(modalCliente).toBeHidden()

  const asociarOtraVez = await abrirModal(page, clienteSimulado, '/admin/clientes')
  await (await esperarBotonInicio(asociarOtraVez)).click()
  await expect(asociarOtraVez.getByRole('alert')).toHaveText(
    'Esta persona ya tiene una tarjeta asociada.',
  )
  await page.keyboard.press('Escape')
  await page.getByRole('link', { name: 'Empleados', exact: true }).click()
  await expect(page).toHaveURL(/\/admin\/empleados$/)
  const fallarActiva: (route: Route) => Promise<void> = async (route) => route.abort('failed')
  await page.route('**/api/v1/rfid-1/capturas/activa', fallarActiva)
  const modalEmpleado = await abrirModal(page, empleadoSimulado, '/admin/empleados')
  await expect(modalEmpleado.getByRole('alert')).toBeVisible()
  await expect(modalEmpleado.getByRole('button', { name: 'Consultar estado' })).toBeVisible()
  await page.unroute('**/api/v1/rfid-1/capturas/activa', fallarActiva)
  await modalEmpleado.getByRole('button', { name: 'Consultar estado' }).click()
  await expect(modalEmpleado.getByRole('button', { name: 'Iniciar captura' })).toBeVisible()

  const inicioRecuperable = await iniciarCaptura(page, modalEmpleado)
  await expect(modalEmpleado.getByText(/\d+:\d{2} restantes/)).toBeVisible()
  const perderSse: (route: Route) => Promise<void> = async (route) => route.abort('failed')
  await page.route('**/api/v1/eventos/administracion', perderSse)
  await page.reload()
  const modalRecuperado = page.getByRole('dialog')
  await expect(modalRecuperado).toBeVisible()
  await expect(modalRecuperado).toContainText(empleadoSimulado)
  await marcarEscaneando(inicioRecuperable.capturaId)
  await expect(modalRecuperado.getByRole('status')).toHaveText('Acerque la tarjeta al lector.', {
    timeout: 15_000,
  })
  const perderRespuestaCancelacion: (route: Route) => Promise<void> = async (route) => {
    if (route.request().method() !== 'DELETE') return route.continue()
    await route.fetch()
    await route.abort('failed')
  }
  await page.route(
    `**${rutaCapturas}/${inicioRecuperable.capturaId}`,
    perderRespuestaCancelacion,
  )
  await modalRecuperado.getByRole('button', { name: 'Cancelar captura' }).click()
  await expect(modalRecuperado).toBeHidden({ timeout: 12_000 })
  await page.unroute(`**${rutaCapturas}/${inicioRecuperable.capturaId}`, perderRespuestaCancelacion)
  await page.unroute('**/api/v1/eventos/administracion', perderSse)
  const uidDuplicado = uidCliente
  const segundaCaptura = await abrirModal(page, empleadoSimulado, '/admin/empleados')
  const inicioDuplicado = await iniciarCaptura(page, segundaCaptura)
  await marcarEscaneando(inicioDuplicado.capturaId)
  await expect(segundaCaptura.getByRole('status')).toHaveText('Acerque la tarjeta al lector.', {
    timeout: 12_000,
  })
  const duplicada = await leerSintetico(inicioDuplicado.capturaId, 'B201', uidDuplicado)
  expect(duplicada.respuesta.status, 'el backend rechaza UID ya asociado').toBe(409)
  await expect(segundaCaptura.getByRole('status')).toHaveText(
    'Esta tarjeta ya está asociada a otra persona.',
    { timeout: 12_000 },
  )
  const capturaParaExpirar = await iniciarCaptura(page, segundaCaptura)
  const hastaExpirar = Math.max(125_000, Date.parse(capturaParaExpirar.expiraEn) - Date.now() + 15_000)
  await expect(segundaCaptura.getByRole('status')).toHaveText(
    'El tiempo para asociar la tarjeta terminó.',
    { timeout: hastaExpirar },
  )
  const ultimaCaptura = await iniciarCaptura(page, segundaCaptura)
  const uidEmpleado = randomBytes(10).toString('hex').toUpperCase()
  await marcarEscaneando(ultimaCaptura.capturaId)
  await expect(segundaCaptura.getByRole('status')).toHaveText('Acerque la tarjeta al lector.', {
    timeout: 12_000,
  })
  const lecturaEmpleado = await leerSintetico(ultimaCaptura.capturaId, 'C301', uidEmpleado)
  expect(lecturaEmpleado.respuesta.status, 'el empleado recibe una lectura autorizada').toBe(200)
  expect(lecturaEmpleado.resultado?.estado).toBe('COMPLETADA')
  await expect(segundaCaptura.getByRole('status')).toHaveText('La tarjeta quedó asociada.', {
    timeout: 12_000,
  })
  await revisarSinDatosPrivados(page, uidEmpleado, mensajesNavegador)
})
