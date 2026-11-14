import { expect, test, type Page, type Request } from '@playwright/test'
import { baseURL, iniciarSesion, type TarjetaPrueba } from './soporte'

test.use({ timezoneId: 'America/Mexico_City' })

type ModoDirectorio = 'normal' | 'vacio' | 'error'

function rutaRelevante(ruta: string) {
  return (
    ruta === '/api/v1/panel' ||
    ruta === '/api/v1/tarjetas-rfid' ||
    ruta.startsWith('/api/v1/tarjetas-rfid/') ||
    ruta.startsWith('/api/v1/rfid-1/')
  )
}

function rutaSinIdentificadores(ruta: string) {
  return ruta
    .replace(/^(\/api\/v1\/tarjetas-rfid)\/(?!personas(?:\/|$))[^/]+/, '$1/:id')
    .replace(/^(\/api\/v1\/rfid-1\/capturas)\/(?!activa(?:\/|$))[^/]+/, '$1/:id')
}

const tarjetas: TarjetaPrueba[] = Array.from({ length: 27 }, (_, indice) => {
  const numero = indice + 1
  const cliente = numero % 2 === 0
  const codigo = String(numero).padStart(4, '0')
  const cancelada = numero % 3 === 0
  return {
    asociacionId: numero,
    uid: `AB${numero.toString(16).toUpperCase().padStart(6, '0')}`,
    tipoEntidad: cliente ? 'CLIENTE' : 'EMPLEADO',
    codigoPersona: `${cliente ? 'CLI' : 'E'}-${codigo}`,
    nombreCompleto: numero === 12 ? 'Marta Herrera' : `Persona Prueba ${codigo}`,
    estado: cancelada ? 'CANCELADA' : 'ACTIVA',
    asociadaEn: '2026-11-05T09:02:38Z',
    canceladaEn: cancelada ? '2026-11-06T09:02:38Z' : null,
  }
})

function rutaPrueba(): string {
  const temporal = process.env.TEST_TARJETAS_HARNESS_PATH
  if (!temporal) return '/admin/tarjetas-rfid'
  if (!/^\/[a-z0-9/_-]+$/i.test(temporal)) throw new Error('La ruta de prueba debe ser local.')
  return temporal
}

function respuestaFiltrada(consulta: URL, modo: ModoDirectorio) {
  const tipoEntidad = consulta.searchParams.get('tipoEntidad') ?? 'MIXTO'
  const estado = consulta.searchParams.get('estado') ?? 'TODAS'
  const busqueda = (consulta.searchParams.get('busqueda') ?? '').trim().toLocaleLowerCase('es-MX')
  const pagina = Number(consulta.searchParams.get('pagina') ?? '1')
  const coincidencias =
    modo === 'vacio'
      ? []
      : tarjetas.filter((tarjeta) => {
          const tipoCoincide = tipoEntidad === 'MIXTO' || tarjeta.tipoEntidad === tipoEntidad
          const estadoCoincide = estado === 'TODAS' || tarjeta.estado === estado
          const textoCoincide = [tarjeta.nombreCompleto, tarjeta.codigoPersona, tarjeta.uid].some(
            (valor) => valor.toLocaleLowerCase('es-MX').includes(busqueda),
          )
          return tipoCoincide && estadoCoincide && textoCoincide
        })
  return {
    items: coincidencias.slice((pagina - 1) * 10, pagina * 10),
    pagina,
    tamano: 10,
    total: coincidencias.length,
    totalPaginas: Math.ceil(coincidencias.length / 10),
  }
}

async function instalarFuenteSimulada(page: Page) {
  await page.addInitScript(() => {
    const fuentes: EventTarget[] = []
    class FuenteSimulada extends EventTarget {
      static readonly CONNECTING = 0
      static readonly OPEN = 1
      static readonly CLOSED = 2
      readonly url: string
      readonly withCredentials = false
      readyState = FuenteSimulada.OPEN
      onopen: ((evento: Event) => void) | null = null
      onerror: ((evento: Event) => void) | null = null
      onmessage: ((evento: MessageEvent) => void) | null = null

      constructor(url: string | URL) {
        super()
        this.url = String(url)
        fuentes.push(this)
        queueMicrotask(() => this.onopen?.(new Event('open')))
      }

      close() {
        this.readyState = FuenteSimulada.CLOSED
      }
    }

    const ventana = window as Window & {
      __tarjetasSsePrueba?: boolean
      __fuentesTarjetasPrueba?: EventTarget[]
      __emitirTarjetasPrueba?: () => void
    }
    ventana.__tarjetasSsePrueba = true
    ventana.__fuentesTarjetasPrueba = fuentes
    ventana.__emitirTarjetasPrueba = () => {
      for (const fuente of fuentes) {
        fuente.dispatchEvent(
          new MessageEvent('rfid1.tarjetas.actualizadas', { data: '{}', lastEventId: '1' }),
        )
      }
    }
    Object.defineProperty(window, 'EventSource', { configurable: true, value: FuenteSimulada })
  })
}

async function emitirActualizacionTarjetas(page: Page) {
  await page.evaluate(() => {
    const ventana = window as Window & { __emitirTarjetasPrueba?: () => void }
    if (!ventana.__emitirTarjetasPrueba) throw new Error('La fuente SSE de prueba no está lista.')
    ventana.__emitirTarjetasPrueba()
  })
}

async function preparar(page: Page, retenerPrimera = false) {
  const ruta = rutaPrueba()
  if (ruta === '/admin/tarjetas-rfid') {
    if (!/^[^@]+@[^@]+\.invalid$/i.test(process.env.TEST_OWNER_EMAIL ?? '')) {
      throw new Error('Esta prueba requiere un propietario sintético con dominio .invalid.')
    }
    await iniciarSesion(page)
  }

  const control = {
    modo: 'normal' as ModoDirectorio,
    consultas: [] as URL[],
    mutaciones: [] as string[],
    erroresCliente: [] as string[],
    respuestasHttp: [] as string[],
    fallosRed: [] as string[],
    peticiones: [] as Request[],
    abortos: [] as Request[],
    respuestasEsperadas: new WeakSet<Request>(),
    consolas503Esperadas: 0,
    espera: null as Promise<void> | null,
    bloquearSiguiente() {
      let liberar!: () => void
      this.espera = new Promise<void>((resolve) => {
        liberar = resolve
      })
      return liberar
    },
  }

  page.on('pageerror', () => control.erroresCliente.push('Error de JavaScript'))
  page.on('console', (mensaje) => {
    if (mensaje.type() !== 'error') return
    if (/status of 503/i.test(mensaje.text()) && control.consolas503Esperadas > 0) {
      control.consolas503Esperadas -= 1
      return
    }
    control.erroresCliente.push('Error de consola')
  })
  page.on('request', (solicitud) => {
    const ruta = new URL(solicitud.url()).pathname
    if (rutaRelevante(ruta)) control.peticiones.push(solicitud)
  })
  page.on('response', (respuesta) => {
    const solicitud = respuesta.request()
    const ruta = new URL(respuesta.url()).pathname
    const estado = respuesta.status()
    if (!rutaRelevante(ruta) || estado < 400 || estado > 599) return
    if (estado === 503 && control.respuestasEsperadas.has(solicitud)) return
    control.respuestasHttp.push(`${solicitud.method()} ${rutaSinIdentificadores(ruta)} ${estado}`)
  })
  page.on('requestfailed', (solicitud) => {
    const ruta = new URL(solicitud.url()).pathname
    if (!rutaRelevante(ruta)) return
    const error = solicitud.failure()?.errorText ?? ''
    if (/ERR_ABORTED/i.test(error)) {
      control.abortos.push(solicitud)
    } else {
      control.fallosRed.push(`${solicitud.method()} ${rutaSinIdentificadores(ruta)} SIN_RESPUESTA`)
    }
  })

  await page.route('**/api/v1/panel', (intercepcion) =>
    intercepcion.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ estacionamiento: { tipo: 'MIXTO' } }),
    }),
  )
  await page.route(
    (destino) => destino.pathname.startsWith('/api/v1/rfid-1/'),
    async (intercepcion) => {
      const solicitud = intercepcion.request()
      const destino = new URL(solicitud.url())
      if (solicitud.method() !== 'GET') {
        control.mutaciones.push(`${solicitud.method()} ${rutaSinIdentificadores(destino.pathname)}`)
        return intercepcion.abort('blockedbyclient')
      }
      if (destino.pathname === '/api/v1/rfid-1/estado-conexion') {
        return intercepcion.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ estado: 'CONECTADO', actualizadoEn: '2026-11-05T09:02:38Z' }),
        })
      }
      if (destino.pathname === '/api/v1/rfid-1/capturas/activa') {
        return intercepcion.fulfill({ status: 200, contentType: 'application/json', body: 'null' })
      }
      return intercepcion.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
    },
  )
  await page.route(
    (destino) => destino.pathname.startsWith('/api/v1/tarjetas-rfid'),
    async (intercepcion) => {
      const solicitud = intercepcion.request()
      const destino = new URL(solicitud.url())
      if (solicitud.method() !== 'GET') {
        control.mutaciones.push(`${solicitud.method()} ${rutaSinIdentificadores(destino.pathname)}`)
        return intercepcion.abort('blockedbyclient')
      }
      if (destino.pathname === '/api/v1/tarjetas-rfid') {
        control.consultas.push(destino)
        const modo = control.modo
        const espera = control.espera
        control.espera = null
        if (espera) {
          await espera
          if (solicitud.failure()) return
        }
        const responder = async (estado: number, cuerpo: string) => {
          try {
            await intercepcion.fulfill({
              status: estado,
              contentType: 'application/json',
              body: cuerpo,
            })
          } catch (fallo) {
            if (!/ERR_ABORTED/i.test(solicitud.failure()?.errorText ?? '')) throw fallo
          }
        }
        if (modo === 'error') {
          control.respuestasEsperadas.add(solicitud)
          control.consolas503Esperadas += 1
          return responder(503, JSON.stringify({ codigo: 'SERVICIO_NO_DISPONIBLE' }))
        }
        return responder(200, JSON.stringify(respuestaFiltrada(destino, modo)))
      }
      const detalle = /^\/api\/v1\/tarjetas-rfid\/(\d+)$/.exec(destino.pathname)
      if (detalle) {
        const tarjeta = tarjetas.find((valor) => valor.asociacionId === Number(detalle[1]))
        return intercepcion.fulfill({
          status: tarjeta ? 200 : 404,
          contentType: 'application/json',
          body: JSON.stringify(tarjeta ?? {}),
        })
      }
      if (destino.pathname === '/api/v1/tarjetas-rfid/personas') {
        return intercepcion.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      }
      if (destino.pathname === '/api/v1/tarjetas-rfid/modalidad') {
        return intercepcion.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ tipoEstacionamiento: 'MIXTO' }),
        })
      }
      return intercepcion.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
    },
  )

  const liberarPrimera = retenerPrimera ? control.bloquearSiguiente() : undefined
  await page.goto(new URL(ruta, baseURL).toString(), { waitUntil: 'domcontentloaded' })
  return { control, liberarPrimera }
}

async function seleccionar(page: Page, etiqueta: string, opcion: string) {
  const campo = page.getByRole('combobox', { name: etiqueta, exact: true })
  if (await campo.evaluate((elemento) => elemento.tagName === 'SELECT')) {
    await campo.selectOption({ label: opcion })
  } else {
    await campo.click()
    await page.getByRole('option', { name: opcion, exact: true }).click()
  }
}

async function esperarConsulta(
  control: Awaited<ReturnType<typeof preparar>>['control'],
  esperado: Record<string, string>,
) {
  await expect
    .poll(() => {
      const ultima = control.consultas.at(-1)
      const consulta = {
        tipoEntidad: ultima?.searchParams.get('tipoEntidad') ?? '',
        estado: ultima?.searchParams.get('estado') ?? '',
        pagina: ultima?.searchParams.get('pagina') ?? '',
        busqueda: ultima?.searchParams.get('busqueda') ?? '',
      }
      return Object.entries(esperado).every(
        ([clave, valor]) => consulta[clave as keyof typeof consulta] === valor,
      )
    })
    .toBe(true)
}

function directorio(page: Page) {
  return page.locator('section[aria-labelledby="titulo-directorio-rfid"]')
}

async function posicionesFiltros(page: Page) {
  const [busqueda, persona, estado] = await Promise.all([
    page.getByRole('searchbox', { name: 'Buscar por nombre, código o UID' }).boundingBox(),
    page.getByRole('combobox', { name: 'Persona', exact: true }).boundingBox(),
    page.getByRole('combobox', { name: 'Estado', exact: true }).boundingBox(),
  ])
  if (!busqueda || !persona || !estado) throw new Error('No se pudieron medir los filtros.')
  return { busqueda, persona, estado }
}

function comprobarSinErrores(control: Awaited<ReturnType<typeof preparar>>['control']) {
  const abortosSinReemplazo = control.abortos
    .filter((abortada) => {
      const indice = control.peticiones.indexOf(abortada)
      const ruta = new URL(abortada.url()).pathname
      return !control.peticiones
        .slice(indice + 1)
        .some(
          (posterior) =>
            posterior.method() === abortada.method() && new URL(posterior.url()).pathname === ruta,
        )
    })
    .map((solicitud) => {
      const ruta = new URL(solicitud.url()).pathname
      return `${solicitud.method()} ${rutaSinIdentificadores(ruta)} ABORTADA`
    })
  expect(control.mutaciones).toEqual([])
  expect(control.erroresCliente).toEqual([])
  expect(control.respuestasHttp).toEqual([])
  expect(control.fallosRed).toEqual([])
  expect(abortosSinReemplazo).toEqual([])
}

test('el directorio combina búsqueda, filtros y paginación con totales filtrados', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  const { control } = await preparar(page)
  const lista = directorio(page)
  await expect(lista.getByRole('heading', { name: 'Tarjetas registradas' })).toBeVisible()
  await expect(lista).toContainText(/27\s+tarjetas/i)
  await expect(lista.locator('tbody tr')).toHaveCount(10)
  const anchos = await lista.evaluate((elemento) => {
    const contenedor =
      elemento.closest('.contenido-admin') ??
      elemento.closest('.pagina-tarjetas-rfid')?.parentElement
    if (!contenedor) return null
    const estilo = getComputedStyle(contenedor)
    return {
      disponible:
        contenedor.getBoundingClientRect().width -
        Number.parseFloat(estilo.paddingLeft) -
        Number.parseFloat(estilo.paddingRight),
      directorio: elemento.getBoundingClientRect().width,
    }
  })
  expect(anchos).not.toBeNull()
  expect(anchos!.directorio).toBeGreaterThanOrEqual(anchos!.disponible - 2)
  const filtros = Object.values(await posicionesFiltros(page))
  const inicios = filtros.map((control) => control.y)
  const finales = filtros.map((control) => control.y + control.height)
  expect(Math.max(...inicios) - Math.min(...inicios)).toBeLessThanOrEqual(2)
  expect(Math.max(...finales) - Math.min(...finales)).toBeLessThanOrEqual(2)
  await expect(page.getByRole('status', { name: /Estado de conexión.*Conectado/i })).toBeVisible()
  await expect(page.getByText('Modalidad: Mixto', { exact: true })).toBeVisible()
  await esperarConsulta(control, { tipoEntidad: 'MIXTO', estado: 'TODAS', pagina: '1' })

  const paginas = page.getByRole('navigation', { name: 'Páginas de tarjetas' })
  await paginas.getByRole('button', { name: 'Página 2', exact: true }).click()
  await esperarConsulta(control, { pagina: '2' })
  await expect(lista.locator('tbody tr')).toHaveCount(10)
  await expect(lista.getByText('AB00000B', { exact: true })).toBeVisible()
  await paginas.getByRole('button', { name: 'Página siguiente', exact: true }).click()
  await esperarConsulta(control, { pagina: '3' })
  await expect(lista.locator('tbody tr')).toHaveCount(7)

  const busqueda = page.getByRole('searchbox', { name: 'Buscar por nombre, código o UID' })
  const busquedas = [
    { termino: 'mArTa', nombre: 'Marta Herrera', codigo: 'CLI-0012' },
    { termino: 'e-0015', nombre: 'Persona Prueba 0015', codigo: 'E-0015' },
    { termino: 'ab000016', nombre: 'Persona Prueba 0022', codigo: 'CLI-0022' },
  ]
  for (const { termino, nombre, codigo } of busquedas) {
    await busqueda.fill(termino)
    await esperarConsulta(control, { pagina: '1', busqueda: termino })
    await expect(lista.locator('tbody tr')).toHaveCount(1)
    await expect(lista.getByText(nombre, { exact: true })).toBeVisible()
    await expect(lista.locator('tbody tr').first()).toContainText(codigo)
    await expect(lista).toContainText(/1\s+resultado/i)
    await expect(paginas).toBeHidden()
  }

  await busqueda.fill('')
  await esperarConsulta(control, { busqueda: '', pagina: '1' })
  await paginas.getByRole('button', { name: 'Página 3', exact: true }).click()
  await esperarConsulta(control, { pagina: '3' })
  await seleccionar(page, 'Persona', 'Clientes')
  await esperarConsulta(control, { tipoEntidad: 'CLIENTE', pagina: '1' })
  await seleccionar(page, 'Estado', 'Inactivas')
  await esperarConsulta(control, { tipoEntidad: 'CLIENTE', estado: 'CANCELADA', pagina: '1' })
  await expect(lista.locator('tbody tr')).toHaveCount(4)
  await expect(lista).toContainText(/4\s+resultados/i)
  await busqueda.fill('Marta')
  await esperarConsulta(control, {
    tipoEntidad: 'CLIENTE',
    estado: 'CANCELADA',
    pagina: '1',
    busqueda: 'Marta',
  })
  await expect(lista.locator('tbody tr')).toHaveCount(1)
  await expect(lista.locator('tbody tr').first()).toContainText('CLI-0012')
  comprobarSinErrores(control)
})

test('muestra carga, vacíos y error; actualizar evita solicitudes duplicadas', async ({ page }) => {
  const { control, liberarPrimera } = await preparar(page, true)
  const lista = directorio(page)
  await expect(lista.getByText(/Cargando tarjetas/i)).toBeVisible()
  liberarPrimera?.()
  await expect(lista.locator('tbody tr')).toHaveCount(10)

  const actualizar = page.getByRole('button', { name: 'Actualizar', exact: true })
  const antes = control.consultas.length
  const liberar = control.bloquearSiguiente()
  await actualizar.click()
  await expect(actualizar).toBeDisabled()
  await expect.poll(() => control.consultas.length).toBe(antes + 1)
  await page.waitForTimeout(200)
  expect(control.consultas).toHaveLength(antes + 1)
  liberar()
  await expect(actualizar).toBeEnabled()

  control.modo = 'vacio'
  await actualizar.click()
  await expect(lista.getByText('Aún no hay tarjetas registradas.', { exact: true })).toBeVisible()
  control.modo = 'normal'
  await actualizar.click()
  await expect(lista.locator('tbody tr')).toHaveCount(10)

  const busqueda = page.getByRole('searchbox', { name: 'Buscar por nombre, código o UID' })
  await busqueda.fill('no-existe')
  await expect(
    lista.getByText('No encontramos tarjetas con esos filtros.', { exact: true }),
  ).toBeVisible()
  await busqueda.fill('')
  await expect(lista.locator('tbody tr')).toHaveCount(10)

  control.modo = 'error'
  await actualizar.click()
  await expect(lista.getByText(/No pudimos/i).first()).toBeVisible()
  const reintentar = lista.getByRole('button', { name: 'Reintentar', exact: true })
  await expect(reintentar).toBeVisible()
  control.modo = 'normal'
  await reintentar.click()
  await expect(lista.locator('tbody tr')).toHaveCount(10)
  comprobarSinErrores(control)
})

test('absorbe SSE anterior al filtro y conserva el SSE posterior a la petición nueva', async ({
  page,
}) => {
  await instalarFuenteSimulada(page)
  const { control } = await preparar(page)
  const lista = directorio(page)
  await expect(lista.locator('tbody tr')).toHaveCount(10)
  await expect
    .poll(() =>
      page.evaluate(() => {
        const ventana = window as Window & { __fuentesTarjetasPrueba?: EventTarget[] }
        return ventana.__fuentesTarjetasPrueba?.length ?? 0
      }),
    )
    .toBeGreaterThan(0)

  const actualizar = page.getByRole('button', { name: 'Actualizar', exact: true })
  const primeraBase = control.consultas.length
  const liberarA = control.bloquearSiguiente()
  await actualizar.click()
  await expect.poll(() => control.consultas.length).toBe(primeraBase + 1)
  await emitirActualizacionTarjetas(page)
  await page.waitForTimeout(250)
  const liberarB = control.bloquearSiguiente()
  await seleccionar(page, 'Persona', 'Clientes')
  await expect.poll(() => control.consultas.length).toBe(primeraBase + 2)
  liberarA()
  liberarB()
  await expect(actualizar).toBeEnabled()
  await expect(lista.locator('tbody tr')).toHaveCount(10)
  await page.waitForTimeout(200)
  expect(control.consultas).toHaveLength(primeraBase + 2)

  const segundaBase = control.consultas.length
  const liberarA2 = control.bloquearSiguiente()
  await actualizar.click()
  await expect.poll(() => control.consultas.length).toBe(segundaBase + 1)
  const liberarB2 = control.bloquearSiguiente()
  await seleccionar(page, 'Estado', 'Activas')
  await expect.poll(() => control.consultas.length).toBe(segundaBase + 2)
  await emitirActualizacionTarjetas(page)
  await page.waitForTimeout(250)
  liberarA2()
  liberarB2()
  await expect.poll(() => control.consultas.length).toBe(segundaBase + 3)
  await expect(lista.locator('tbody tr')).toHaveCount(9)
  await expect(actualizar).toBeEnabled()
  await page.waitForTimeout(200)
  expect(control.consultas).toHaveLength(segundaBase + 3)
  comprobarSinErrores(control)
})

test('abre los dos modales en móvil sin iniciar capturas ni cambiar tarjetas', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const { control } = await preparar(page)
  const lista = directorio(page)
  await expect(lista.locator('tbody tr')).toHaveCount(10)
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    ),
  ).toBe(false)
  const filtros = await posicionesFiltros(page)
  expect(filtros.persona.y).toBeGreaterThanOrEqual(filtros.busqueda.y + filtros.busqueda.height)
  expect(filtros.estado.y).toBeGreaterThanOrEqual(filtros.persona.y + filtros.persona.height)
  const ancho = await page.evaluate(() => document.documentElement.clientWidth)
  for (const filtro of Object.values(filtros)) {
    expect(filtro.x).toBeGreaterThanOrEqual(0)
    expect(filtro.x + filtro.width).toBeLessThanOrEqual(ancho + 1)
  }

  const detalle = lista.getByRole('button', { name: /Ver detalles/i }).first()
  await detalle.click()
  const dialogoDetalle = page.getByRole('dialog', { name: 'Detalles de tarjeta' })
  await expect(dialogoDetalle).toBeVisible()
  await expect(dialogoDetalle.getByText('AB000001', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialogoDetalle).toBeHidden()
  await expect(detalle).toBeFocused()

  const asociar = page.getByRole('button', { name: 'Asociar tarjeta', exact: true })
  await asociar.click()
  const dialogoAsociacion = page.getByRole('dialog', { name: 'Asociar tarjeta' })
  await expect(dialogoAsociacion).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialogoAsociacion).toBeHidden()
  await expect(asociar).toBeFocused()
  comprobarSinErrores(control)
})
