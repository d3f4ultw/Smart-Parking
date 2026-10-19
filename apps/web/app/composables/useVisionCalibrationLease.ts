type EstadoLeaseCalibracion =
  | 'inactivo'
  | 'adquiriendo'
  | 'vigente'
  | 'ocupado'
  | 'perdido'
  | 'error'

type RespuestaLease = {
  acquired: boolean
  lease_duration_seconds: number
}

type SolicitudLease = {
  editor_instance_id: string
}

const INTERVALO_RENOVACION_MS = 10_000

function estadoHttp(error: unknown): number | null {
  if (error === null || typeof error !== 'object') return null
  const valor = error as { status?: unknown; statusCode?: unknown }
  return typeof valor.statusCode === 'number'
    ? valor.statusCode
    : typeof valor.status === 'number'
      ? valor.status
      : null
}

function detalleHttp(error: unknown): string | null {
  if (error === null || typeof error !== 'object') return null
  const valor = error as { data?: unknown }
  if (valor.data === null || typeof valor.data !== 'object') return null
  const datos = valor.data as { detail?: unknown }
  return typeof datos.detail === 'string' ? datos.detail : null
}

export function useVisionCalibrationLease(alPerderAcceso: (error: unknown) => void) {
  const estado = ref<EstadoLeaseCalibracion>('inactivo')
  const editorInstanceId = ref<string | null>(null)
  const fetchLease = $fetch.create({
    credentials: 'same-origin',
    cache: 'no-store',
    timeout: 10_000,
  })

  let temporizadorLatido: number | null = null
  let adquisicionEnCurso: Promise<boolean> | null = null
  let renovacionEnCurso: Promise<boolean> | null = null
  let liberacionEnCurso: Promise<boolean> | null = null
  let generacion = 0

  const vigente = computed(() => estado.value === 'vigente')

  function detenerLatido() {
    if (temporizadorLatido === null || !import.meta.client) return
    window.clearInterval(temporizadorLatido)
    temporizadorLatido = null
  }

  function iniciarLatido() {
    if (!import.meta.client || temporizadorLatido !== null) return
    temporizadorLatido = window.setInterval(() => {
      void renovar()
    }, INTERVALO_RENOVACION_MS)
  }

  function nuevaInstancia() {
    if (!import.meta.client) return null
    editorInstanceId.value = crypto.randomUUID()
    return editorInstanceId.value
  }

  async function enviarLiberacion(instancia: string, keepalive = false): Promise<boolean> {
    const cuerpo: SolicitudLease = { editor_instance_id: instancia }
    if (keepalive) {
      try {
        const respuesta = await fetch('/api/admin/vision/calibration-lease/release', {
          method: 'POST',
          credentials: 'same-origin',
          cache: 'no-store',
          keepalive: true,
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(cuerpo),
        })
        return respuesta.ok
      } catch {
        return false
      }
    }

    try {
      const respuesta = await fetchLease<{ released: boolean }>(
        '/api/admin/vision/calibration-lease/release',
        { method: 'POST', body: cuerpo },
      )
      return respuesta.released
    } catch {
      return false
    }
  }

  async function adquirir(opciones: {
    editorInstanceId?: string
    instanciaNueva?: boolean
  } = {}): Promise<boolean> {
    if (!import.meta.client) return false
    if (estado.value === 'vigente' && !opciones.instanciaNueva) return true
    if (adquisicionEnCurso !== null && !opciones.instanciaNueva) return adquisicionEnCurso
    if (adquisicionEnCurso !== null && opciones.instanciaNueva) await adquisicionEnCurso
    if (estado.value === 'perdido' && !opciones.instanciaNueva) return false

    detenerLatido()
    if (opciones.editorInstanceId !== undefined) {
      editorInstanceId.value = opciones.editorInstanceId
    } else if (opciones.instanciaNueva || editorInstanceId.value === null) {
      nuevaInstancia()
    }
    const instancia = editorInstanceId.value
    if (instancia === null) return false
    const solicitudActual = ++generacion
    estado.value = 'adquiriendo'

    adquisicionEnCurso = (async () => {
      try {
        const respuesta = await fetchLease<RespuestaLease>(
          '/api/admin/vision/calibration-lease/acquire',
          { method: 'POST', body: { editor_instance_id: instancia } satisfies SolicitudLease },
        )
        if (solicitudActual !== generacion || editorInstanceId.value !== instancia) {
          void enviarLiberacion(instancia, true)
          return false
        }
        if (!respuesta.acquired) {
          estado.value = 'ocupado'
          return false
        }
        estado.value = 'vigente'
        iniciarLatido()
        return true
      } catch (fallo: unknown) {
        if (solicitudActual !== generacion || editorInstanceId.value !== instancia) return false
        estado.value = estadoHttp(fallo) === 409
          ? detalleHttp(fallo) === 'Calibración en uso.' ? 'ocupado' : 'perdido'
          : 'error'
        if (estadoHttp(fallo) === 401 || estadoHttp(fallo) === 403) alPerderAcceso(fallo)
        return false
      } finally {
        adquisicionEnCurso = null
      }
    })()
    return adquisicionEnCurso
  }

  async function renovar(): Promise<boolean> {
    if (!import.meta.client || estado.value !== 'vigente' || editorInstanceId.value === null) {
      return false
    }
    if (renovacionEnCurso !== null) return renovacionEnCurso
    const instancia = editorInstanceId.value
    const solicitudActual = generacion

    renovacionEnCurso = (async () => {
      try {
        await fetchLease<RespuestaLease>(
          '/api/admin/vision/calibration-lease/renew',
          { method: 'POST', body: { editor_instance_id: instancia } satisfies SolicitudLease },
        )
        return solicitudActual === generacion && estado.value === 'vigente'
      } catch (fallo: unknown) {
        if (solicitudActual === generacion && editorInstanceId.value === instancia) {
          detenerLatido()
          estado.value = 'perdido'
          void enviarLiberacion(instancia)
          alPerderAcceso(fallo)
        }
        return false
      } finally {
        renovacionEnCurso = null
      }
    })()
    return renovacionEnCurso
  }

  async function liberar(): Promise<boolean> {
    detenerLatido()
    const instancia = editorInstanceId.value
    if (instancia === null) {
      estado.value = 'inactivo'
      return true
    }
    if (liberacionEnCurso !== null) return liberacionEnCurso

    generacion += 1
    estado.value = 'inactivo'
    liberacionEnCurso = enviarLiberacion(instancia).finally(() => {
      liberacionEnCurso = null
    })
    return liberacionEnCurso
  }

  function liberarAlSalir(): Promise<boolean> {
    detenerLatido()
    const instancia = editorInstanceId.value
    if (instancia === null) return Promise.resolve(true)
    generacion += 1
    estado.value = 'inactivo'
    return enviarLiberacion(instancia, true)
  }

  return {
    estado,
    editorInstanceId,
    vigente,
    adquirir,
    renovar,
    liberar,
    liberarAlSalir,
  }
}
