import { appendResponseHeader, getRequestHeader, setResponseHeader } from 'h3'
import type { EntradaActiva, PaginaEntradasActivas, ResumenCapacidadRfid } from '~/types/acceso'
import { leerSalidaManual } from '~/utils/salida-manual-api'

type FetchAccesos = <T>(ruta: string, opciones: Record<string, unknown>) => Promise<T>

export class ErrorAccesosApi extends Error {
  constructor(
    public readonly estado: number,
    mensaje: string,
  ) {
    super(mensaje)
  }
}

function objeto(valor: unknown): Record<string, unknown> | null {
  return valor !== null && typeof valor === 'object' && !Array.isArray(valor)
    ? (valor as Record<string, unknown>)
    : null
}

function enteroNoNegativo(valor: unknown): valor is number {
  return typeof valor === 'number' && Number.isSafeInteger(valor) && valor >= 0
}

function cursor(valor: unknown): string | null {
  return typeof valor === 'string' && valor.length <= 256 ? valor : null
}

function leerCapacidad(valor: unknown): ResumenCapacidadRfid {
  const dato = objeto(valor)
  if (
    !dato ||
    !enteroNoNegativo(dato.capacidadTotal) ||
    !enteroNoNegativo(dato.vehiculosDentro) ||
    !enteroNoNegativo(dato.capacidadDisponible) ||
    dato.capacidadDisponible !== Math.max(0, dato.capacidadTotal - dato.vehiculosDentro)
  ) {
    throw new ErrorAccesosApi(503, 'No pudimos confirmar la capacidad del estacionamiento.')
  }
  return {
    capacidadTotal: dato.capacidadTotal,
    vehiculosDentro: dato.vehiculosDentro,
    capacidadDisponible: dato.capacidadDisponible,
    cursorEventos: cursor(dato.cursorEventos),
  }
}

function leerEntrada(valor: unknown): EntradaActiva | null {
  const entrada = objeto(valor)
  const persona = objeto(entrada?.persona)
  if (
    !entrada ||
    !persona ||
    typeof entrada.movimientoId !== 'string' ||
    !/^[1-9]\d*$/.test(entrada.movimientoId) ||
    (persona.tipo !== 'CLIENTE' && persona.tipo !== 'EMPLEADO') ||
    typeof persona.nombre !== 'string' ||
    typeof persona.codigo !== 'string' ||
    (entrada.estadoTarjeta !== 'ACTIVA' && entrada.estadoTarjeta !== 'CANCELADA') ||
    !('salidaManual' in entrada) ||
    (entrada.salidaManual !== null && !leerSalidaManual(entrada.salidaManual)) ||
    typeof entrada.entradaEn !== 'string' ||
    typeof entrada.entradaEnLocal !== 'string'
  ) {
    return null
  }
  return {
    movimientoId: entrada.movimientoId,
    persona: { tipo: persona.tipo, nombre: persona.nombre, codigo: persona.codigo },
    estadoTarjeta: entrada.estadoTarjeta,
    entradaEn: entrada.entradaEn,
    entradaEnLocal: entrada.entradaEnLocal,
    salidaManual: entrada.salidaManual === null ? null : leerSalidaManual(entrada.salidaManual),
  }
}

function leerEntradas(valor: unknown): PaginaEntradasActivas {
  const dato = objeto(valor)
  if (
    !dato ||
    !Array.isArray(dato.items) ||
    !enteroNoNegativo(dato.pagina) ||
    dato.pagina < 1 ||
    !enteroNoNegativo(dato.tamano) ||
    dato.tamano < 1 ||
    !enteroNoNegativo(dato.totalRegistros) ||
    typeof dato.haySiguiente !== 'boolean' ||
    typeof dato.zonaHoraria !== 'string'
  ) {
    throw new ErrorAccesosApi(503, 'No pudimos confirmar los vehículos dentro del estacionamiento.')
  }
  const items = dato.items.map(leerEntrada)
  if (items.some((entrada) => entrada === null)) {
    throw new ErrorAccesosApi(503, 'No pudimos confirmar los vehículos dentro del estacionamiento.')
  }
  return {
    items: items as EntradaActiva[],
    pagina: dato.pagina,
    tamano: dato.tamano,
    totalRegistros: dato.totalRegistros,
    haySiguiente: dato.haySiguiente,
    zonaHoraria: dato.zonaHoraria,
    cursorEventos: cursor(dato.cursorEventos),
  }
}

function mensajeSeguro(estado: number) {
  if (estado === 401) return 'Tu acceso venció. Inicia sesión de nuevo.'
  if (estado === 403) return 'No tienes acceso para consultar esta información.'
  return 'No pudimos actualizar la información. Revisa tu conexión e inténtalo de nuevo.'
}

/** Obtiene los espacios disponibles y los movimientos que siguen abiertos;
 * comprueba que los números recibidos sean coherentes antes de mostrarlos.
 */
export function useClienteAccesos() {
  const fetchApi = useRequestFetch() as unknown as FetchAccesos
  const evento = import.meta.server ? useRequestEvent() : undefined
  const cookie = evento ? getRequestHeader(evento, 'cookie') : undefined

  if (evento) {
    setResponseHeader(evento, 'cache-control', 'no-store, private')
    setResponseHeader(evento, 'vary', 'Cookie')
  }

  async function consultar(ruta: string, signal: AbortSignal, query?: Record<string, string>) {
    try {
      return await fetchApi<unknown>(ruta, {
        method: 'GET',
        retry: 0,
        headers: { accept: 'application/json', ...(cookie ? { cookie } : {}) },
        query,
        signal,
        onResponse({ response }: { response: Response }) {
          if (!evento) return
          for (const valor of response.headers.getSetCookie()) {
            appendResponseHeader(evento, 'set-cookie', valor)
          }
        },
      })
    } catch (fallo) {
      if (signal.aborted) throw fallo
      const error = fallo as {
        statusCode?: number
        status?: number
        response?: { status?: number }
      }
      const estado = error.response?.status ?? error.statusCode ?? error.status ?? 503
      throw new ErrorAccesosApi(estado, mensajeSeguro(estado))
    }
  }

  return {
    async capacidad(signal: AbortSignal) {
      return leerCapacidad(await consultar('/api/v1/accesos/capacidad', signal))
    },
    async dentro(pagina: number, busqueda: string, signal: AbortSignal) {
      return leerEntradas(
        await consultar('/api/v1/accesos/dentro', signal, {
          pagina: String(pagina),
          ...(busqueda ? { busqueda } : {}),
        }),
      )
    },
  }
}
