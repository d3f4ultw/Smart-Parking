import { inject, provide, ref, type InjectionKey, type Ref } from 'vue'

export type EstadoEventosTiempoReal =
  | 'conectando'
  | 'conectado'
  | 'reconectando'
  | 'verificando-sesion'
  | 'sesion-perdida'
  | 'detenido'

type EstadoFisicoCajon = 'DESCONOCIDO' | 'LIBRE' | 'OCUPADO'
type EstadoOperativoCajon = 'DISPONIBLE' | 'MANTENIMIENTO' | 'FUERA_DE_SERVICIO'
type EstadoEfectivoCajon =
  | 'DESCONOCIDO'
  | 'LIBRE'
  | 'OCUPADO'
  | 'NO_DISPONIBLE'

export type InstantaneaEventoCajon = {
  cajon_id: number
  numero: number
  estado_fisico: EstadoFisicoCajon
  estado_operativo: EstadoOperativoCajon
  motivo_operativo: string | null
  estado_efectivo: EstadoEfectivoCajon
  estado_fisico_actualizado_en: string | null
  estado_operativo_actualizado_en: string
  actualizado_en: string
}

type TipoEvento =
  | 'operador.actualizado'
  | 'operador.creado'
  | 'cajon.actualizado'
  | 'resync'

type EventoTiempoReal = {
  id: string
  tipo: TipoEvento
  recursoId: number | null
  datosCajon?: InstantaneaEventoCajon
}

export type ManejadoresEventosTiempoReal = {
  alActualizarOperador: (id: number) => void
  alCrearOperador: (id: number, cursorEvento: string) => void
  alResync: () => void | Promise<void>
  alActualizarCajon?: (datos: InstantaneaEventoCajon) => void
}

type SuscripcionEventosTiempoReal = {
  actualizarCursor: (cursor: string) => void
  detener: () => void
}

export type ControladorEventosTiempoReal = {
  estado: Readonly<Ref<EstadoEventosTiempoReal>>
  suscribir: (
    cursorInicial: string,
    manejadores: ManejadoresEventosTiempoReal,
  ) => SuscripcionEventosTiempoReal
  iniciar: () => void
  detener: () => void
}

type OpcionesControladorEventos = {
  crearFuente?: (url: string) => EventSource
  comprobarSesion?: () => Promise<number>
  alPerderSesion: () => void | Promise<void>
  programar?: (callback: () => void, milisegundos: number) => ReturnType<typeof setTimeout>
  cancelar?: (temporizador: ReturnType<typeof setTimeout>) => void
  limiteBuffer?: number
}

type SuscriptorInterno = {
  cursor: string
  manejadores: ManejadoresEventosTiempoReal
}

const CLAVE_EVENTOS_TIEMPO_REAL: InjectionKey<ControladorEventosTiempoReal> =
  Symbol('eventos-tiempo-real')
const LIMITE_BUFFER = 256
const ESPERA_REINTENTO_MS = [1000, 2000, 4000, 8000, 16000, 30000]
const EVENT_SOURCE_CONNECTING = 0
const EVENT_SOURCE_CLOSED = 2
const EVENTOS_PERMITIDOS = new Set<TipoEvento>([
  'operador.actualizado',
  'operador.creado',
  'cajon.actualizado',
  'resync',
])

const ESTADOS_FISICOS_CAJON = new Set<EstadoFisicoCajon>([
  'DESCONOCIDO',
  'LIBRE',
  'OCUPADO',
])
const ESTADOS_OPERATIVOS_CAJON = new Set<EstadoOperativoCajon>([
  'DISPONIBLE',
  'MANTENIMIENTO',
  'FUERA_DE_SERVICIO',
])
const ESTADOS_EFECTIVOS_CAJON = new Set<EstadoEfectivoCajon>([
  'DESCONOCIDO',
  'LIBRE',
  'OCUPADO',
  'NO_DISPONIBLE',
])

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

function esFechaConZona(valor: unknown): valor is string {
  return typeof valor === 'string'
    && /(?:Z|[+-]\d{2}:\d{2})$/.test(valor)
    && !Number.isNaN(Date.parse(valor))
}

function analizarInstantaneaCajon(valor: unknown): InstantaneaEventoCajon | null {
  if (valor === null || typeof valor !== 'object' || Array.isArray(valor)) {
    return null
  }
  const datos = valor as Record<string, unknown>
  const clavesEsperadas = [
    'cajon_id',
    'numero',
    'estado_fisico',
    'estado_operativo',
    'motivo_operativo',
    'estado_efectivo',
    'estado_fisico_actualizado_en',
    'estado_operativo_actualizado_en',
    'actualizado_en',
  ]
  if (
    Object.keys(datos).length !== clavesEsperadas.length
    || Object.keys(datos).some((clave) => !clavesEsperadas.includes(clave))
  ) {
    return null
  }

  const { cajon_id, numero } = datos
  const fisico = datos.estado_fisico
  const operativo = datos.estado_operativo
  const motivo = datos.motivo_operativo
  const efectivo = datos.estado_efectivo
  if (
    typeof cajon_id !== 'number'
    || !Number.isSafeInteger(cajon_id)
    || cajon_id <= 0
    || typeof numero !== 'number'
    || !Number.isSafeInteger(numero)
    || numero <= 0
    || typeof fisico !== 'string'
    || !ESTADOS_FISICOS_CAJON.has(fisico as EstadoFisicoCajon)
    || typeof operativo !== 'string'
    || !ESTADOS_OPERATIVOS_CAJON.has(operativo as EstadoOperativoCajon)
    || typeof efectivo !== 'string'
    || !ESTADOS_EFECTIVOS_CAJON.has(efectivo as EstadoEfectivoCajon)
    || (motivo !== null && typeof motivo !== 'string')
    || (typeof motivo === 'string' && (motivo.trim().length === 0 || motivo.length > 250))
    || (operativo === 'DISPONIBLE' && motivo !== null)
    || (
      datos.estado_fisico_actualizado_en !== null
      && !esFechaConZona(datos.estado_fisico_actualizado_en)
    )
    || !esFechaConZona(datos.estado_operativo_actualizado_en)
    || !esFechaConZona(datos.actualizado_en)
  ) {
    return null
  }

  const estadoEfectivoEsperado = operativo !== 'DISPONIBLE'
    ? 'NO_DISPONIBLE'
    : fisico === 'OCUPADO'
      ? 'OCUPADO'
      : fisico === 'LIBRE'
        ? 'LIBRE'
        : 'DESCONOCIDO'
  if (efectivo !== estadoEfectivoEsperado) {
    return null
  }

  return datos as InstantaneaEventoCajon
}

function analizarEvento(tipo: string, evento: Event): EventoTiempoReal | null {
  if (!EVENTOS_PERMITIDOS.has(tipo as TipoEvento)) {
    return null
  }
  const cursor = (evento as MessageEvent<string>).lastEventId
  if (!esCursorDecimal(cursor)) {
    return null
  }
  if (tipo === 'resync') {
    return { id: cursor, tipo: 'resync', recursoId: null }
  }

  try {
    const datos: unknown = JSON.parse((evento as MessageEvent<string>).data)
    if (datos === null || typeof datos !== 'object' || Array.isArray(datos)) {
      return null
    }
    const recurso = datos as Record<string, unknown>
    const recursoId = recurso.recurso_id
    if (typeof recursoId !== 'number' || !Number.isSafeInteger(recursoId) || recursoId <= 0) {
      return null
    }
    if (tipo === 'cajon.actualizado') {
      if (recurso.recurso_tipo !== 'cajon') {
        return null
      }
      const datosCajon = analizarInstantaneaCajon(recurso.datos)
      if (datosCajon === null || datosCajon.cajon_id !== recursoId) {
        return null
      }
      return {
        id: cursor,
        tipo: 'cajon.actualizado',
        recursoId,
        datosCajon,
      }
    }
    if (recurso.recurso_tipo !== 'operador') {
      return null
    }
    return { id: cursor, tipo: tipo as TipoEvento, recursoId }
  } catch {
    return null
  }
}

export function crearControladorEventosTiempoReal(
  opciones: OpcionesControladorEventos,
): ControladorEventosTiempoReal {
  const estado = ref<EstadoEventosTiempoReal>('detenido')
  const crearFuente = opciones.crearFuente
    ?? ((url: string) => new EventSource(url, { withCredentials: true }))
  const comprobarSesion = opciones.comprobarSesion ?? (async () => {
    try {
      const respuesta = await fetch('/api/autenticacion/me', {
        credentials: 'same-origin',
        cache: 'no-store',
      })
      return respuesta.status
    } catch {
      return 0
    }
  })
  const programar = opciones.programar
    ?? ((callback, milisegundos) => setTimeout(callback, milisegundos))
  const cancelar = opciones.cancelar
    ?? ((temporizador) => clearTimeout(temporizador))
  const limiteBuffer = Math.max(1, opciones.limiteBuffer ?? LIMITE_BUFFER)
  const buffer: EventoTiempoReal[] = []
  const suscriptores = new Set<SuscriptorInterno>()
  let cursorDescartado: string | null = null
  let cursorUltimoEvento = '0'
  let cursorInicialFijado = false
  let fuente: EventSource | null = null
  let temporizadorReintento: ReturnType<typeof setTimeout> | null = null
  let temporizadorEstado: ReturnType<typeof setTimeout> | null = null
  let reintentos = 0
  let iniciado = false
  let detenido = false
  let verificandoSesion = false

  function avanzarCursor(actual: string, candidato: string): string {
    return compararCursores(candidato, actual) > 0 ? candidato : actual
  }

  function invocar(suscriptor: SuscriptorInterno, evento: EventoTiempoReal): void {
    if (compararCursores(evento.id, suscriptor.cursor) <= 0) {
      return
    }
    suscriptor.cursor = evento.id
    if (evento.tipo === 'resync') {
      void suscriptor.manejadores.alResync()
    } else if (evento.tipo === 'cajon.actualizado') {
      if (evento.datosCajon !== undefined) {
        suscriptor.manejadores.alActualizarCajon?.(evento.datosCajon)
      }
    } else if (evento.recursoId !== null && evento.tipo === 'operador.creado') {
      suscriptor.manejadores.alCrearOperador(evento.recursoId, evento.id)
    } else if (evento.recursoId !== null) {
      suscriptor.manejadores.alActualizarOperador(evento.recursoId)
    }
  }

  function reproducir(suscriptor: SuscriptorInterno): void {
    if (
      cursorDescartado !== null
      && compararCursores(suscriptor.cursor, cursorDescartado) < 0
    ) {
      void suscriptor.manejadores.alResync()
      suscriptor.cursor = cursorUltimoEvento
      return
    }
    for (const evento of buffer) {
      invocar(suscriptor, evento)
    }
  }

  function recibir(tipo: string, eventoNativo: Event, fuenteEvento: EventSource): void {
    if (detenido || fuente !== fuenteEvento) {
      return
    }
    const evento = analizarEvento(tipo, eventoNativo)
    if (evento === null || compararCursores(evento.id, cursorUltimoEvento) <= 0) {
      return
    }
    cursorUltimoEvento = evento.id
    cursorInicialFijado = true
    buffer.push(evento)
    if (buffer.length > limiteBuffer) {
      const descartado = buffer.shift()
      if (descartado !== undefined) {
        cursorDescartado = avanzarCursor(cursorDescartado ?? '0', descartado.id)
      }
    }
    for (const suscriptor of suscriptores) {
      invocar(suscriptor, evento)
    }
  }

  function limpiarTemporizadores(): void {
    if (temporizadorReintento !== null) {
      cancelar(temporizadorReintento)
      temporizadorReintento = null
    }
    if (temporizadorEstado !== null) {
      cancelar(temporizadorEstado)
      temporizadorEstado = null
    }
  }

  function programarReintento(): void {
    if (detenido || fuente !== null || temporizadorReintento !== null) {
      return
    }
    const indice = Math.min(reintentos, ESPERA_REINTENTO_MS.length - 1)
    const espera = ESPERA_REINTENTO_MS[indice]!
    reintentos += 1
    estado.value = 'reconectando'
    temporizadorReintento = programar(() => {
      temporizadorReintento = null
      abrirFuente()
    }, espera)
  }

  function verificarSesionYReintentar(): void {
    if (detenido || verificandoSesion) {
      return
    }
    verificandoSesion = true
    estado.value = 'verificando-sesion'
    void comprobarSesion()
      .then(async (status) => {
        if (detenido) {
          return
        }
        if (status === 401) {
          detenido = true
          limpiarTemporizadores()
          estado.value = 'sesion-perdida'
          await opciones.alPerderSesion()
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

  function abrirFuente(): void {
    if (!iniciado || detenido || fuente !== null || temporizadorReintento !== null) {
      return
    }
    estado.value = 'conectando'
    const url = cursorInicialFijado
      ? `/api/eventos?cursor_eventos=${encodeURIComponent(cursorUltimoEvento)}`
      : '/api/eventos'
    let fuenteNueva: EventSource
    try {
      fuenteNueva = crearFuente(url)
    } catch {
      programarReintento()
      return
    }
    fuente = fuenteNueva
    fuenteNueva.onopen = () => {
      if (detenido || fuente !== fuenteNueva) {
        return
      }
      if (temporizadorEstado !== null) {
        cancelar(temporizadorEstado)
        temporizadorEstado = null
      }
      reintentos = 0
      estado.value = 'conectado'
    }
    fuenteNueva.onerror = () => {
      if (detenido || fuente !== fuenteNueva) {
        return
      }
      if (fuenteNueva.readyState !== EVENT_SOURCE_CLOSED) {
        if (temporizadorEstado === null) {
          temporizadorEstado = programar(() => {
            temporizadorEstado = null
            if (
              !detenido
              && fuente === fuenteNueva
              && fuenteNueva.readyState === EVENT_SOURCE_CONNECTING
            ) {
              estado.value = 'reconectando'
            }
          }, 500)
        }
        return
      }
      if (temporizadorEstado !== null) {
        cancelar(temporizadorEstado)
        temporizadorEstado = null
      }
      fuenteNueva.close()
      fuente = null
      verificarSesionYReintentar()
    }
    for (const tipo of EVENTOS_PERMITIDOS) {
      fuenteNueva.addEventListener(tipo, (evento) => recibir(tipo, evento, fuenteNueva))
    }
  }

  function iniciar(): void {
    if (detenido || iniciado) {
      return
    }
    iniciado = true
    abrirFuente()
  }

  function suscribir(
    cursorInicial: string,
    manejadores: ManejadoresEventosTiempoReal,
  ): SuscripcionEventosTiempoReal {
    const suscriptor: SuscriptorInterno = {
      cursor: esCursorDecimal(cursorInicial) ? cursorInicial : '0',
      manejadores,
    }
    cursorUltimoEvento = avanzarCursor(cursorUltimoEvento, suscriptor.cursor)
    cursorInicialFijado = true
    suscriptores.add(suscriptor)
    reproducir(suscriptor)
    return {
      actualizarCursor(cursor) {
        if (esCursorDecimal(cursor)) {
          suscriptor.cursor = avanzarCursor(suscriptor.cursor, cursor)
          cursorUltimoEvento = avanzarCursor(cursorUltimoEvento, cursor)
          cursorInicialFijado = true
          reproducir(suscriptor)
        }
      },
      detener() {
        suscriptores.delete(suscriptor)
      },
    }
  }

  function detener(): void {
    if (detenido) {
      return
    }
    detenido = true
    limpiarTemporizadores()
    fuente?.close()
    fuente = null
    suscriptores.clear()
    estado.value = 'detenido'
  }

  return { estado, suscribir, iniciar, detener }
}

export function proveerEventosTiempoReal(
  controlador: ControladorEventosTiempoReal,
): void {
  provide(CLAVE_EVENTOS_TIEMPO_REAL, controlador)
}

export function usarEventosTiempoReal(): ControladorEventosTiempoReal {
  const controlador = inject(CLAVE_EVENTOS_TIEMPO_REAL)
  if (controlador === undefined) {
    throw new Error('El layout protegido debe proveer el controlador de eventos.')
  }
  return controlador
}
