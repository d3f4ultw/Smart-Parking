import { expect, type Page, type Route } from '@playwright/test'
import { baseURL } from './sesion'
import {
  CORREO_SINTETICO,
  ID_ACTIVO,
  ID_EMPLEADO,
  ID_EXPIRADO,
  ID_INACTIVO,
  ID_PENDIENTE,
  ID_USADO,
  crearDetalleSintetico,
  empleadoSintetico as empleado,
  operadoresSinteticos as operadores,
} from './operadores-ux-data'

export {
  CORREO_SINTETICO,
  ID_ACTIVO,
  ID_EMPLEADO,
  ID_EXPIRADO,
  ID_INACTIVO,
  ID_PENDIENTE,
  ID_USADO,
}

type GuardiaApi = {
  bloqueadas: string[]
  erroresConsola: string[]
  erroresPagina: string[]
  erroresRed: string[]
  consultas: Array<{ pagina: string; busqueda: string; estado: string; respuestaHttp?: number }>
  busquedasEmpleado: string[]
  respuestasHttp: Array<{
    metodo: string
    ruta: string
    estado: number
    paso: string
    url: string
    host: string
    origin: string
    cuerpo?: string
  }>
  pasoActual: string
  fallosListadoAplicados: number
  detallesSolicitados: string[]
  detallesRespuestas: Array<{ id: string; estado: number }>
  detallesFallidosAplicados: number
  promociones: Array<{
    id: string
    correo: string
    csrf: boolean
    idempotencia: boolean
    etag: boolean
  }>
  controles: {
    fallosListado: number
    demorarSiguienteListadoMs: number
    fallosDetallePorId: Map<string, number>
    demorarSiguienteDetalleMs: number
    demorarPromocionMs: number
    respuestaPromocion: 'exito' | 'duplicado'
  }
}

export async function instalarFixtures(page: Page): Promise<GuardiaApi> {
  const guardia: GuardiaApi = {
    bloqueadas: [],
    erroresConsola: [],
    erroresPagina: [],
    erroresRed: [],
    consultas: [],
    busquedasEmpleado: [],
    respuestasHttp: [],
    pasoActual: 'antes de la navegación',
    fallosListadoAplicados: 0,
    detallesSolicitados: [],
    detallesRespuestas: [],
    detallesFallidosAplicados: 0,
    promociones: [],
    controles: {
      fallosListado: 0,
      demorarSiguienteListadoMs: 0,
      fallosDetallePorId: new Map(),
      demorarSiguienteDetalleMs: 0,
      demorarPromocionMs: 0,
      respuestaPromocion: 'exito',
    },
  }
  page.on('console', (mensaje) => {
    if (mensaje.type() === 'error' && !mensaje.text().startsWith('Failed to load resource:')) {
      guardia.erroresConsola.push(mensaje.text())
    }
  })
  page.on('pageerror', (error) => guardia.erroresPagina.push(error.message))
  page.on('response', async (respuesta) => {
    if (respuesta.status() >= 400) {
      const url = new URL(respuesta.url())
      const encabezados = respuesta.request().headers()
      const registro = {
        metodo: respuesta.request().method(),
        ruta: url.pathname,
        estado: respuesta.status(),
        paso: guardia.pasoActual,
        url: respuesta.url(),
        host: encabezados.host ?? '',
        origin: encabezados.origin ?? '',
        cuerpo: undefined as string | undefined,
      }
      guardia.respuestasHttp.push(registro)
      if (url.pathname === '/_nuxt/components/admin/operadores/ModalAgregarOperador.vue') {
        registro.cuerpo = (await respuesta.text().catch(() => '')).slice(0, 500)
      }
    }
  })
  page.on('requestfailed', (solicitud) => {
    const motivo = solicitud.failure()?.errorText ?? ''
    if (motivo.includes('ERR_ABORTED') || motivo.includes('BLOCKED_BY_CLIENT')) return
    guardia.erroresRed.push(`${solicitud.method()} ${new URL(solicitud.url()).pathname}: ${motivo}`)
  })
  await page.route('**/*', async (route) => {
    const solicitud = route.request()
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(solicitud.method())) {
      const ruta = new URL(solicitud.url()).pathname
      guardia.bloqueadas.push(`${solicitud.method()} ${ruta}`)
      return route.abort('blockedbyclient')
    }
    return route.fallback()
  })
  await page.route('**/api/v1/**', async (route) => responderApiSintetica(route, guardia))
  return guardia
}

async function responderApiSintetica(route: Route, guardia: GuardiaApi) {
  const solicitud = route.request()
  const metodo = solicitud.method()
  const url = new URL(solicitud.url())
  const ruta = url.pathname
  if (metodo === 'GET' && ruta === '/api/v1/sesion') {
    return route.fulfill({
      json: { autenticada: true, correo: 'propietario@example.test', rol: 'DUENO' },
    })
  }
  if (metodo === 'GET' && ruta === '/api/v1/panel')
    return route.fulfill({
      json: {
        propietario: {
          nombres: 'Propietario',
          primerApellido: 'QA',
          correo: 'propietario@example.test',
        },
        estacionamiento: {
          nombre: 'Estacionamiento QA',
          tipo: 'PRIVADO',
          horario: {
            modo: 'CONTINUO_24_7',
            zonaHoraria: 'America/Mexico_City',
            horaApertura: null,
            horaCierre: null,
          },
        },
      },
    })
  if (metodo === 'GET' && ruta === '/api/v1/csrf')
    return route.fulfill({ json: { token: 'csrf-sintetico-no-valido' } })
  if (metodo === 'GET' && ruta === '/api/v1/eventos/administracion') {
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: 'retry: 60000\n\n',
    })
  }
  if (metodo === 'POST' && ruta === '/api/v1/eventos/administracion/heartbeat')
    return route.fulfill({ status: 204 })
  if (metodo === 'GET' && ruta === '/api/v1/operadores') {
    const parametros: { pagina: string; busqueda: string; estado: string; respuestaHttp?: number } =
      {
        pagina: url.searchParams.get('pagina') ?? '1',
        busqueda: url.searchParams.get('busqueda') ?? '',
        estado: url.searchParams.get('estado') ?? 'TODOS',
      }
    guardia.consultas.push(parametros)
    if (guardia.controles.demorarSiguienteListadoMs > 0) {
      const demora = guardia.controles.demorarSiguienteListadoMs
      guardia.controles.demorarSiguienteListadoMs = 0
      await esperar(demora)
    }
    if (guardia.controles.fallosListado > 0) {
      guardia.controles.fallosListado -= 1
      guardia.fallosListadoAplicados += 1
      parametros.respuestaHttp = 503
      return route.fulfill({ status: 503, json: { codigo: 'SERVICIO_NO_DISPONIBLE' } })
    }
    const texto = parametros.busqueda.trim().toLocaleLowerCase('es-MX')
    const filtrados = operadores.filter((item) => {
      const nombre =
        `${item.nombres} ${item.primerApellido} ${item.segundoApellido ?? ''}`.toLocaleLowerCase(
          'es-MX',
        )
      return (
        (!texto || nombre.includes(texto)) &&
        (parametros.estado === 'TODOS' || item.estado === parametros.estado)
      )
    })
    const pagina = Math.max(1, Number(parametros.pagina) || 1)
    parametros.respuestaHttp = 200
    return route.fulfill({
      json: {
        items: filtrados.slice((pagina - 1) * 10, pagina * 10),
        pagina,
        tamanoPagina: 10,
        totalRegistros: filtrados.length,
        totalPaginas: Math.ceil(filtrados.length / 10),
        cursorEventos: 'cursor-sintetico',
      },
    })
  }
  if (metodo === 'GET' && ruta === '/api/v1/empleados') {
    const busqueda = url.searchParams.get('busqueda') ?? ''
    guardia.busquedasEmpleado.push(busqueda)
    const coincide =
      !busqueda ||
      `${empleado.nombres} ${empleado.primerApellido}`
        .toLowerCase()
        .includes(busqueda.toLowerCase())
    const resultados = coincide ? [empleado] : []
    return route.fulfill({
      json: {
        items: resultados,
        pagina: 1,
        tamanoPagina: 10,
        totalRegistros: resultados.length,
        totalPaginas: resultados.length ? 1 : 0,
        cursorEventos: 'cursor-empleado-sintetico',
      },
    })
  }
  if (metodo === 'GET' && ruta.startsWith('/api/v1/operadores/')) {
    const id = ruta.slice('/api/v1/operadores/'.length)
    if (!/^[0-9a-f-]{36}$/i.test(id)) return bloquear(route, guardia, metodo, ruta)
    guardia.detallesSolicitados.push(id)
    if (guardia.controles.demorarSiguienteDetalleMs > 0) {
      const demora = guardia.controles.demorarSiguienteDetalleMs
      guardia.controles.demorarSiguienteDetalleMs = 0
      await esperar(demora)
    }
    const fallosDetalleRestantes = guardia.controles.fallosDetallePorId.get(id) ?? 0
    if (fallosDetalleRestantes > 0) {
      guardia.controles.fallosDetallePorId.set(id, fallosDetalleRestantes - 1)
      guardia.detallesFallidosAplicados += 1
      guardia.detallesRespuestas.push({ id, estado: 503 })
      return route.fulfill({ status: 503, json: { codigo: 'SERVICIO_NO_DISPONIBLE' } })
    }
    const operador = operadores.find((item) => item.id === id)
    if (!operador) {
      guardia.detallesRespuestas.push({ id, estado: 404 })
      return route.fulfill({ status: 404, json: { codigo: 'NO_ENCONTRADO' } })
    }
    guardia.detallesRespuestas.push({ id, estado: 200 })
    return route.fulfill({
      status: 200,
      headers: { etag: '"1"' },
      json: crearDetalleSintetico(operador),
    })
  }
  if (metodo === 'POST' && ruta === `/api/v1/empleados/${ID_EMPLEADO}/operador/promocion`) {
    const cuerpo = solicitud.postDataJSON() as { correo?: string }
    guardia.promociones.push({
      id: ID_EMPLEADO,
      correo: cuerpo.correo ?? '',
      csrf: Boolean(solicitud.headers()['x-csrf-token']),
      idempotencia: Boolean(solicitud.headers()['idempotency-key']),
      etag: Boolean(solicitud.headers()['if-match']),
    })
    if (guardia.controles.demorarPromocionMs > 0)
      await esperar(guardia.controles.demorarPromocionMs)
    if (guardia.controles.respuestaPromocion === 'duplicado') {
      return route.fulfill({ status: 409, json: { codigo: 'OPERADOR_YA_VINCULADO' } })
    }
    return route.fulfill({
      status: 201,
      json: { estadoInvitacion: 'ENVIADO', estadoCuenta: 'PENDIENTE', id: ID_PENDIENTE },
    })
  }
  return bloquear(route, guardia, metodo, ruta)
}

function bloquear(route: Route, guardia: GuardiaApi, metodo: string, ruta: string) {
  guardia.bloqueadas.push(`${metodo} ${ruta}`)
  return route.abort('blockedbyclient')
}
function esperar(ms: number) {
  return new Promise((resolver) => setTimeout(resolver, ms))
}

export async function abrirDirectorioSintetico(page: Page) {
  await page.goto(new URL('/', baseURL).toString())
  await page.waitForFunction(() => {
    const raiz = document.querySelector('#__nuxt') as HTMLElement & {
      __vue_app__?: { config?: { globalProperties?: Record<string, unknown> } }
    }
    return Boolean(raiz?.__vue_app__?.config?.globalProperties?.$router)
  })
  await page.evaluate(async () => {
    const raiz = document.querySelector('#__nuxt') as HTMLElement & {
      __vue_app__?: { config?: { globalProperties?: Record<string, unknown> } }
    }
    const router = raiz.__vue_app__?.config?.globalProperties?.$router as
      | { push: (ruta: string) => Promise<void> }
      | undefined
    if (!router) throw new Error('No se encontró el router hidratado de Nuxt.')
    await router.push('/admin/operadores')
  })
  await expect(page.getByRole('region', { name: 'Directorio de operadores' })).toBeVisible()
}

export async function verificarSinErrores(guardia: GuardiaApi) {
  const erroresHttpInesperados = guardia.respuestasHttp.filter((respuesta) => {
    if (
      respuesta.estado === 409 &&
      respuesta.ruta.endsWith('/operador/promocion') &&
      guardia.controles.respuestaPromocion === 'duplicado'
    )
      return false
    if (
      respuesta.estado === 503 &&
      respuesta.ruta === '/api/v1/operadores' &&
      guardia.fallosListadoAplicados > 0
    )
      return false
    if (
      respuesta.estado === 503 &&
      respuesta.ruta.startsWith('/api/v1/operadores/') &&
      guardia.detallesFallidosAplicados > 0
    )
      return false
    return true
  })
  expect(guardia.bloqueadas).toEqual([])
  expect(guardia.erroresPagina).toEqual([])
  expect(guardia.erroresConsola).toEqual([])
  expect(guardia.erroresRed).toEqual([])
  expect(erroresHttpInesperados, JSON.stringify(erroresHttpInesperados)).toEqual([])
}

export async function seleccionarEmpleado(page: Page, guardia: GuardiaApi) {
  const dialogo = page.getByRole('dialog')
  await dialogo.getByLabel('Buscar empleado').fill('Ana')
  await expect.poll(() => guardia.busquedasEmpleado.at(-1)).toBe('Ana')
  await dialogo.getByRole('button', { name: /Ana Disponible/ }).click()
  await expect(dialogo.getByRole('region', { name: 'Empleado seleccionado' })).toBeVisible()
  return dialogo
}
