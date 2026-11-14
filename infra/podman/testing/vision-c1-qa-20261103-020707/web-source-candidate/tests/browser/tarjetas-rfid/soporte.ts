import { createHash, randomBytes } from 'node:crypto'
import { type APIRequestContext, type Page } from '@playwright/test'
import { baseURL, iniciarSesion } from '../sesion'

const apiBase = process.env.TEST_API_BASE_URL ?? 'http://api:8080'
const rutaCapturas = '/api/v1/rfid-1/capturas'

export { baseURL, iniciarSesion }

export interface InicioCaptura {
  capturaId: string
  estado: string
  expiraEn: string
}

export interface ResultadoLectura {
  capturaId: string
  estado: string
  resultado: string | null
}

export interface LecturaSintetica {
  uid: string
  estadoHttp: number
  resultado: ResultadoLectura | null
}

export interface TarjetaPrueba {
  asociacionId: number
  uid: string
  tipoEntidad: 'CLIENTE' | 'EMPLEADO'
  codigoPersona: string
  nombreCompleto: string
  estado: 'ACTIVA' | 'CANCELADA'
  asociadaEn: string
  canceladaEn: string | null
}

export interface PaginaTarjetasPrueba {
  items: TarjetaPrueba[]
  pagina: number
  tamano: number
  total: number
  totalPaginas: number
}

export interface EstadoEventosRfidPrueba {
  creaciones: number
  maximoActivos: number
  tipos: string[]
  tamanosPayload: number[]
}

export function webUrl(ruta: string): string {
  return new URL(ruta, baseURL).toString()
}

export async function instrumentarEventosRfid(page: Page): Promise<void> {
  await page.addInitScript(() => {
    type Monitor = {
      creaciones: number
      activos: number
      maximoActivos: number
      tipos: string[]
      tamanosPayload: number[]
    }
    type VentanaMonitor = Window & { __rfidStage2Sse?: Monitor }
    const ventana = window as VentanaMonitor
    ventana.__rfidStage2Sse = {
      creaciones: 0,
      activos: 0,
      maximoActivos: 0,
      tipos: [],
      tamanosPayload: [],
    }

    const agregar = EventSource.prototype.addEventListener
    EventSource.prototype.addEventListener = function (tipo, listener, opciones) {
      if (tipo !== 'rfid1.captura.actualizada' && tipo !== 'rfid1.tarjetas.actualizadas') {
        return agregar.call(this, tipo, listener, opciones)
      }
      const envoltura: EventListener = (evento) => {
        const dato = (evento as MessageEvent<string>).data
        ventana.__rfidStage2Sse?.tipos.push(tipo)
        ventana.__rfidStage2Sse?.tamanosPayload.push(typeof dato === 'string' ? dato.length : -1)
        if (typeof listener === 'function') listener.call(this, evento)
        else listener?.handleEvent(evento)
      }
      return agregar.call(this, tipo, envoltura, opciones)
    }

    const nativa = window.EventSource
    window.EventSource = new Proxy(nativa, {
      construct(objetivo, argumentos, destino) {
        const monitor = ventana.__rfidStage2Sse
        if (monitor) {
          monitor.creaciones += 1
          monitor.activos += 1
          monitor.maximoActivos = Math.max(monitor.maximoActivos, monitor.activos)
        }
        const flujo = Reflect.construct(objetivo, argumentos, destino) as EventSource
        const cerrar = flujo.close.bind(flujo)
        let abierto = true
        flujo.close = () => {
          if (abierto && monitor) {
            abierto = false
            monitor.activos -= 1
          }
          cerrar()
        }
        return flujo
      },
    })
  })
}

export async function estadoEventosRfid(page: Page): Promise<EstadoEventosRfidPrueba> {
  return page.evaluate(() => {
    type Monitor = EstadoEventosRfidPrueba & { activos?: number }
    const monitor = (window as Window & { __rfidStage2Sse?: Monitor }).__rfidStage2Sse
    return {
      creaciones: monitor?.creaciones ?? 0,
      maximoActivos: monitor?.maximoActivos ?? 0,
      tipos: monitor?.tipos ?? [],
      tamanosPayload: monitor?.tamanosPayload ?? [],
    }
  })
}

export async function consultarTarjetas(
  request: APIRequestContext,
  tipoEntidad: 'CLIENTE' | 'EMPLEADO',
  estado: 'TODAS' | 'ACTIVA' | 'CANCELADA' = 'TODAS',
): Promise<PaginaTarjetasPrueba> {
  const respuesta = await request.get(
    webUrl(`/api/v1/tarjetas-rfid?tipoEntidad=${tipoEntidad}&estado=${estado}&pagina=1`),
  )
  if (respuesta.status() !== 200)
    throw new Error('No se pudo consultar el directorio RFID de prueba.')
  return (await respuesta.json()) as PaginaTarjetasPrueba
}

function claveLectura(capturaId: string, requestId: string): string {
  const entrada = Buffer.concat([
    Buffer.from(capturaId.replaceAll('-', ''), 'hex'),
    Buffer.from(requestId.toUpperCase(), 'ascii'),
  ])
  const hash = createHash('sha1').update(entrada).digest()
  hash[6] = (hash[6] & 0x0f) | 0x50
  hash[8] = (hash[8] & 0x3f) | 0x80
  const uuid = hash.subarray(0, 16).toString('hex')
  return `${uuid.slice(0, 8)}-${uuid.slice(8, 12)}-${uuid.slice(12, 16)}-${uuid.slice(16, 20)}-${uuid.slice(20)}`
}

async function solicitarDispositivo(
  ruta: string,
  cuerpo?: Record<string, string>,
  clave?: string,
): Promise<Response> {
  const token = process.env.TEST_DEVICE_TOKEN
  if (!token) throw new Error('Falta la credencial sintética del dispositivo en el runner.')
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
  if (cuerpo) headers['Content-Type'] = 'application/json'
  if (clave) headers['Idempotency-Key'] = clave
  return fetch(new URL(ruta, apiBase), {
    method: 'POST',
    headers,
    body: cuerpo ? JSON.stringify(cuerpo) : undefined,
  })
}

/** Envía una lectura técnica desde Node; la credencial no entra en la página ni en el BFF. */
export async function enviarLecturaSintetica(
  capturaId: string,
  uidSolicitada?: string,
  prepararEstado = true,
): Promise<LecturaSintetica> {
  const uid = uidSolicitada ?? crearUidSintetico()
  const requestId = randomBytes(2).toString('hex')
  if (prepararEstado) await prepararCapturaSintetica(capturaId)

  const respuesta = await solicitarDispositivo(
    '/api/v1/dispositivos/rfid-1/lecturas',
    { capturaId, requestId, uid },
    claveLectura(capturaId, requestId),
  )
  let resultado: ResultadoLectura | null = null
  if (respuesta.ok) {
    try {
      resultado = (await respuesta.json()) as ResultadoLectura
    } catch {
      throw new Error('La API no devolvió un resultado de lectura válido.')
    }
  }
  return { uid, estadoHttp: respuesta.status, resultado }
}

export async function prepararCapturaSintetica(capturaId: string): Promise<void> {
  const respuesta = await solicitarDispositivo(
    `/api/v1/dispositivos/rfid-1/capturas/${capturaId}/estado`,
    { estado: 'ESCANEANDO' },
  )
  if (respuesta.status !== 204) throw new Error('No se pudo preparar la lectura sintética.')
}

/** Retira una captura propia que haya quedado activa si una aserción anterior falla. */
export async function cancelarCapturaActiva(request: APIRequestContext): Promise<void> {
  const activa = await request.get(webUrl(`${rutaCapturas}/activa`)).catch(() => null)
  if (activa?.status() !== 200) return

  let captura: { capturaId?: string }
  try {
    captura = (await activa.json()) as { capturaId?: string }
  } catch {
    return
  }
  if (!captura.capturaId) return

  const csrfRespuesta = await request.get(webUrl('/api/v1/csrf')).catch(() => null)
  if (csrfRespuesta?.status() !== 200) return
  let csrf: { token?: string }
  try {
    csrf = (await csrfRespuesta.json()) as { token?: string }
  } catch {
    return
  }
  if (!csrf.token) return

  await request.delete(webUrl(`${rutaCapturas}/${captura.capturaId}`), {
    headers: { 'X-CSRF-TOKEN': csrf.token },
  })
}

export function crearUidSintetico(): string {
  return randomBytes(4).toString('hex').toUpperCase()
}
