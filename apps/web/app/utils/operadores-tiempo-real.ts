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

export type TipoEventoOperador = 'operador.actualizado' | 'operador.creado' | 'resync'
export type EstadoSseOperadores =
  | 'conectando'
  | 'conectado'
  | 'reconectando'
  | 'verificando-sesion'
  | 'sesion-perdida'
  | 'detenido'

export type RegistroCreacionesOperador = {
  aceptar: (id: number) => boolean
}

type OpcionesStreamOperadores = {
  cursorInicial: string
  crearFuente?: (url: string) => EventSource
  comprobarSesion: () => Promise<number>
  alRecibirActualizacion: (id: number) => void
  alRecibirCreacion: (id: number, cursorEvento: string) => void
  alRecibirResync: () => void | Promise<void>
  alCambiarEstado: (estado: EstadoSseOperadores) => void
  alPerderSesion: () => void | Promise<void>
  programar?: (callback: () => void, milisegundos: number) => ReturnType<typeof setTimeout>
  cancelar?: (temporizador: ReturnType<typeof setTimeout>) => void
}

const ESPERA_REINTENTO_MS = [1000, 2000, 4000, 8000, 16000, 30000, 45000]
const RUTA_EVENTOS_OPERADORES = '/api/admin/operadores/eventos'
const EVENT_SOURCE_CLOSED = 2

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

function obtenerIdOperadorEvento(evento: Event): number | null {
  try {
    const datos: unknown = JSON.parse((evento as MessageEvent<string>).data)
    if (datos === null || typeof datos !== 'object' || Array.isArray(datos)) {
      return null
    }
    const id = (datos as Record<string, unknown>).operador_id
    return typeof id === 'number' && Number.isSafeInteger(id) && id > 0
      ? id
      : null
  } catch {
    return null
  }
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

export function crearStreamOperadores(opciones: OpcionesStreamOperadores) {
  const crearFuente = opciones.crearFuente
    ?? ((url: string) => new EventSource(url, { withCredentials: true }))
  const programar = opciones.programar
    ?? ((callback, milisegundos) => setTimeout(callback, milisegundos))
  const cancelar = opciones.cancelar
    ?? ((temporizador) => clearTimeout(temporizador))
  let cursorUltimoEvento = esCursorDecimal(opciones.cursorInicial)
    ? opciones.cursorInicial
    : '0'
  let fuente: EventSource | null = null
  let temporizador: ReturnType<typeof setTimeout> | null = null
  let reintentos = 0
  let detenido = false
  let verificandoSesion = false

  function urlStream(): string {
    return `${RUTA_EVENTOS_OPERADORES}?cursor_eventos=${encodeURIComponent(cursorUltimoEvento)}`
  }

  function limpiarTemporizador(): void {
    if (temporizador !== null) {
      cancelar(temporizador)
      temporizador = null
    }
  }

  function programarReintento(): void {
    if (detenido || temporizador !== null || fuente !== null) {
      return
    }
    const indice = Math.min(reintentos, ESPERA_REINTENTO_MS.length - 1)
    const espera = ESPERA_REINTENTO_MS[indice]!
    reintentos += 1
    opciones.alCambiarEstado('reconectando')
    temporizador = programar(() => {
      temporizador = null
      abrirFuente()
    }, espera)
  }

  function procesarEvento(
    fuenteEvento: EventSource,
    tipo: TipoEventoOperador,
    evento: Event,
  ): void {
    if (detenido || fuente !== fuenteEvento) {
      return
    }
    const idEvento = (evento as MessageEvent<string>).lastEventId
    if (!esCursorDecimal(idEvento) || compararCursores(idEvento, cursorUltimoEvento) <= 0) {
      return
    }
    cursorUltimoEvento = idEvento

    if (tipo === 'resync') {
      void opciones.alRecibirResync()
      return
    }

    const idOperador = obtenerIdOperadorEvento(evento)
    if (idOperador === null) {
      return
    }
    if (tipo === 'operador.creado') {
      opciones.alRecibirCreacion(idOperador, idEvento)
    } else {
      opciones.alRecibirActualizacion(idOperador)
    }
  }

  function abrirFuente(): void {
    if (detenido || fuente !== null || temporizador !== null) {
      return
    }
    opciones.alCambiarEstado('conectando')
    const fuenteNueva = crearFuente(urlStream())
    fuente = fuenteNueva
    fuenteNueva.onopen = () => {
      if (detenido || fuente !== fuenteNueva) {
        return
      }
      reintentos = 0
      opciones.alCambiarEstado('conectado')
    }
    fuenteNueva.onerror = () => {
      if (detenido || fuente !== fuenteNueva) {
        return
      }
      if (fuenteNueva.readyState !== EVENT_SOURCE_CLOSED) {
        opciones.alCambiarEstado('reconectando')
        return
      }

      fuenteNueva.close()
      fuente = null
      if (verificandoSesion) {
        return
      }
      verificandoSesion = true
      opciones.alCambiarEstado('verificando-sesion')
      void opciones.comprobarSesion()
        .then((status) => {
          if (detenido) {
            return
          }
          if (status === 401) {
            detenido = true
            limpiarTemporizador()
            opciones.alCambiarEstado('sesion-perdida')
            void opciones.alPerderSesion()
            return
          }
          programarReintento()
        })
        .catch(() => {
          if (!detenido) {
            programarReintento()
          }
        })
        .finally(() => {
          verificandoSesion = false
        })
    }
    fuenteNueva.addEventListener('operador.actualizado', (evento) => {
      procesarEvento(fuenteNueva, 'operador.actualizado', evento)
    })
    fuenteNueva.addEventListener('operador.creado', (evento) => {
      procesarEvento(fuenteNueva, 'operador.creado', evento)
    })
    fuenteNueva.addEventListener('resync', (evento) => {
      procesarEvento(fuenteNueva, 'resync', evento)
    })
  }

  function iniciar(): void {
    abrirFuente()
  }

  function detener(): void {
    if (detenido) {
      return
    }
    detenido = true
    limpiarTemporizador()
    fuente?.close()
    fuente = null
    opciones.alCambiarEstado('detenido')
  }

  return { iniciar, detener }
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
