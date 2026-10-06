import type { Operador } from '~/utils/gestion-operadores'

type EstadoReconciliacion = {
  sucio: boolean
  permiteInsertar: boolean
  controlador: AbortController | null
  promesa: Promise<void>
}

type OpcionesReconciliador = {
  obtenerOperador: (id: number, signal: AbortSignal) => Promise<Operador>
  alCambiarCarga: (id: number, cargando: boolean) => void
  alRecibirOperador: (operador: Operador, permiteInsertar: boolean) => void
  alFallar: (id: number, error: unknown) => void
}

export type RegistroCreacionesOperador = {
  aceptar: (id: number) => boolean
}

export function crearRegistroCreacionesOperador(
  limite = 256,
): RegistroCreacionesOperador {
  const idsProcesados = new Set<number>()
  return {
    aceptar(id) {
      if (idsProcesados.has(id)) {
        return false
      }
      idsProcesados.add(id)
      if (idsProcesados.size > limite) {
        const primerId = idsProcesados.values().next().value as number | undefined
        if (primerId !== undefined) {
          idsProcesados.delete(primerId)
        }
      }
      return true
    },
  }
}

function esCursorDecimal(valor: string): boolean {
  return /^\d+$/.test(valor)
}

function compararCursores(a: string, b: string): number {
  const cursorA = a.replace(/^0+(?=\d)/, '')
  const cursorB = b.replace(/^0+(?=\d)/, '')
  if (cursorA.length !== cursorB.length) {
    return cursorA.length > cursorB.length ? 1 : -1
  }
  return cursorA === cursorB ? 0 : cursorA > cursorB ? 1 : -1
}

export function crearReconciliadorOperadores(opciones: OpcionesReconciliador) {
  const solicitudes = new Map<number, EstadoReconciliacion>()
  const pendientes = new Map<number, boolean>()
  let generacion = 0
  let suspendido = false
  let detenido = false

  function reconciliar(id: number, permiteInsertar = false): Promise<void> {
    if (detenido || !Number.isSafeInteger(id) || id <= 0) {
      return Promise.resolve()
    }
    if (suspendido) {
      pendientes.set(id, (pendientes.get(id) ?? false) || permiteInsertar)
      return Promise.resolve()
    }

    const solicitudExistente = solicitudes.get(id)
    if (solicitudExistente) {
      solicitudExistente.sucio = true
      solicitudExistente.permiteInsertar ||= permiteInsertar
      return solicitudExistente.promesa
    }

    const solicitud: EstadoReconciliacion = {
      sucio: false,
      permiteInsertar,
      controlador: null,
      promesa: Promise.resolve(),
    }
    solicitudes.set(id, solicitud)
    opciones.alCambiarCarga(id, true)
    solicitud.promesa = ejecutar(id, solicitud)
    return solicitud.promesa
  }

  async function ejecutar(
    id: number,
    solicitud: EstadoReconciliacion,
  ): Promise<void> {
    while (!detenido) {
      solicitud.sucio = false
      const generacionSolicitud = generacion
      const controlador = new AbortController()
      solicitud.controlador = controlador

      try {
        const operador = await opciones.obtenerOperador(id, controlador.signal)
        if (!detenido && generacionSolicitud === generacion) {
          opciones.alRecibirOperador(operador, solicitud.permiteInsertar)
        }
      } catch (error: unknown) {
        if (
          !detenido
          && !controlador.signal.aborted
          && generacionSolicitud === generacion
        ) {
          opciones.alFallar(id, error)
        }
      } finally {
        if (solicitud.controlador === controlador) {
          solicitud.controlador = null
        }
      }

      if (!solicitud.sucio || detenido) {
        break
      }
    }

    if (solicitudes.get(id) === solicitud) {
      solicitudes.delete(id)
      opciones.alCambiarCarga(id, false)
    }
  }

  function suspenderYDescartar(): void {
    suspendido = true
    generacion += 1
    pendientes.clear()
    for (const solicitud of solicitudes.values()) {
      solicitud.sucio = false
      solicitud.controlador?.abort()
    }
  }

  function reanudar(): void {
    suspendido = false
    for (const [id, permiteInsertar] of pendientes) {
      void reconciliar(id, permiteInsertar)
    }
    pendientes.clear()
  }

  function detener(): void {
    detenido = true
    suspendido = true
    generacion += 1
    pendientes.clear()
    for (const solicitud of solicitudes.values()) {
      solicitud.sucio = false
      solicitud.controlador?.abort()
    }
  }

  return { reconciliar, suspenderYDescartar, reanudar, detener }
}

export function compararCursoresEventos(a: string, b: string): number {
  if (!esCursorDecimal(a) || !esCursorDecimal(b)) {
    return 0
  }
  return compararCursores(a, b)
}

export function puedeInsertarCreacionEnPagina(
  operadorId: number,
  pagina: number,
  totalPaginas: number,
  tamanoPagina: number,
  operadores: readonly Pick<Operador, 'id'>[],
): boolean {
  if (operadores.some((operador) => operador.id === operadorId)) {
    return false
  }
  const ultimaPagina = Math.max(1, totalPaginas)
  if (pagina !== ultimaPagina || operadores.length >= tamanoPagina) {
    return false
  }
  const primerId = operadores[0]?.id ?? 0
  return operadorId >= primerId
}
