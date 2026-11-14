import { computed, onMounted, onScopeDispose, ref } from 'vue'
import { ErrorRfid1Api, useClienteRfid1 } from '~/utils/rfid1-api'
import type { CapturaRfid1, PersonaRfid1, SolicitudCapturaRfid1 } from '~/types/rfid1'

type FaseCaptura = 'lista' | 'revisando' | 'iniciando' | 'activa' | 'cancelando' | 'error'

const INTERVALO_RECONCILIACION_MS = 8_000
const ESTADOS_ACTIVOS = new Set(['PENDIENTE', 'ESCANEANDO'])

/** Mantiene a la vista la lectura actual del lector; escucha avisos y consulta
 * periódicamente para mostrar cambios aunque algún aviso no llegue.
 */
export function useCapturaRfid1(resolverPersona?: (captura: CapturaRfid1) => PersonaRfid1 | null) {
  const api = useClienteRfid1()
  const csrf = useCsrf()
  const sesion = useSesion()
  const abierta = ref(false)
  const persona = ref<PersonaRfid1 | null>(null)
  const captura = ref<CapturaRfid1 | null>(null)
  const fase = ref<FaseCaptura>('lista')
  const mensajeError = ref('')
  const ahora = ref(0)
  const segundosRestantes = computed(() => {
    const vence = captura.value ? Date.parse(captura.value.expiraEn) : NaN
    if (!Number.isFinite(vence) || !ahora.value) return null
    return Math.max(0, Math.ceil((vence - ahora.value) / 1_000))
  })
  const trabajando = computed(() => ['revisando', 'iniciando', 'cancelando'].includes(fase.value))

  let claveInicio: string | null = null
  let inicioEnCurso = false
  let cancelacionEnCurso = false
  let cierreSolicitado = false
  let consultaActivaEnCurso: Promise<CapturaRfid1 | null> | null = null
  let consultaEstadoEnCurso: Promise<void> | null = null
  let controladorEstado: AbortController | null = null
  let suscripcionSse: (() => void) | null = null
  let temporizadorReconciliacion: ReturnType<typeof setTimeout> | null = null
  let temporizadorReloj: ReturnType<typeof setInterval> | null = null
  let descartado = false

  function esActiva(valor: CapturaRfid1 | null) {
    return Boolean(valor && ESTADOS_ACTIVOS.has(valor.estado))
  }

  function personaDeCaptura(valor: CapturaRfid1): PersonaRfid1 {
    return (
      resolverPersona?.(valor) ?? {
        tipoEntidad: valor.tipoEntidad,
        codigo: valor.codigoPersona,
        nombreCompleto: `${valor.tipoEntidad === 'CLIENTE' ? 'Cliente' : 'Empleado'} ${valor.codigoPersona}`,
      }
    )
  }

  function limpiarTemporizadores() {
    if (temporizadorReconciliacion) clearTimeout(temporizadorReconciliacion)
    if (temporizadorReloj) clearInterval(temporizadorReloj)
    temporizadorReconciliacion = null
    temporizadorReloj = null
  }

  function dejarDeEscuchar() {
    suscripcionSse?.()
    suscripcionSse = null
  }

  function escucharCambios() {
    if (suscripcionSse || !import.meta.client) return
    suscripcionSse = useNuxtApp().$eventosAdministracion.suscribir(
      () => void reconciliar(),
      undefined,
      'rfid1.captura.actualizada',
    )
  }

  function programarReconciliacion() {
    if (temporizadorReconciliacion) clearTimeout(temporizadorReconciliacion)
    temporizadorReconciliacion = null
    if (!abierta.value || !esActiva(captura.value)) return
    const vence = captura.value ? Date.parse(captura.value.expiraEn) : NaN
    const hastaVencer =
      Number.isFinite(vence) && vence > Date.now()
        ? vence - Date.now()
        : INTERVALO_RECONCILIACION_MS
    const espera = Math.min(INTERVALO_RECONCILIACION_MS, hastaVencer)
    temporizadorReconciliacion = setTimeout(() => {
      temporizadorReconciliacion = null
      void reconciliar()
    }, espera)
  }

  function iniciarReloj() {
    if (temporizadorReloj || !import.meta.client) return
    ahora.value = Date.now()
    temporizadorReloj = setInterval(() => {
      ahora.value = Date.now()
    }, 1_000)
  }

  function guardarCaptura(valor: CapturaRfid1, seleccionada?: PersonaRfid1) {
    abierta.value = true
    mensajeError.value = ''
    captura.value = valor
    persona.value = seleccionada ?? personaDeCaptura(valor)
    if (esActiva(valor)) {
      fase.value = 'activa'
      escucharCambios()
      iniciarReloj()
      programarReconciliacion()
    } else {
      fase.value = 'lista'
      limpiarTemporizadores()
      dejarDeEscuchar()
    }
  }

  async function manejarSesionVencida(error: unknown) {
    if (!(error instanceof ErrorRfid1Api) || error.estado !== 401) return false
    captura.value = null
    persona.value = null
    abierta.value = false
    limpiarTemporizadores()
    dejarDeEscuchar()
    await sesion.limpiar()
    await navigateTo('/panel')
    return true
  }

  async function consultarActiva(): Promise<CapturaRfid1 | null> {
    if (consultaActivaEnCurso) return consultaActivaEnCurso
    const solicitud = api.consultarActiva()
    consultaActivaEnCurso = solicitud
    try {
      return await solicitud
    } finally {
      if (consultaActivaEnCurso === solicitud) consultaActivaEnCurso = null
    }
  }

  /** Al abrir la pantalla, busca si ya había una lectura en curso y la recupera
   * antes de permitir iniciar otra.
   */
  async function recuperarActiva(abrirSiExiste: boolean) {
    if (descartado || !import.meta.client) return null
    fase.value = 'revisando'
    try {
      const actual = await consultarActiva()
      if (descartado) return null
      if (actual) {
        guardarCaptura(actual)
        if (cierreSolicitado && !inicioEnCurso) await cancelarInterno()
        return actual
      }
      if (cierreSolicitado) {
        cierreSolicitado = false
        abierta.value = false
        persona.value = null
        captura.value = null
        fase.value = 'lista'
        limpiarTemporizadores()
        dejarDeEscuchar()
      } else if (abrirSiExiste) {
        fase.value = 'lista'
      }
      return null
    } catch (fallo) {
      if (await manejarSesionVencida(fallo)) return null
      if (descartado) return null
      fase.value = 'error'
      mensajeError.value =
        fallo instanceof ErrorRfid1Api
          ? fallo.message
          : 'No pudimos confirmar el estado de la captura. Revisa tu conexión e inténtalo de nuevo.'
      return null
    }
  }

/** Consulta el estado actual y descarta una respuesta si ya pertenece a una lectura anterior. */
  async function reconciliar() {
    if (descartado) return
    const identificador = captura.value?.capturaId
    if (!identificador) {
      await recuperarActiva(true)
      return
    }
    if (consultaEstadoEnCurso) return consultaEstadoEnCurso

    const controlador = new AbortController()
    controladorEstado = controlador
    const tarea = (async () => {
      try {
        const actual = await api.consultar(identificador, controlador.signal)
        if (controlador.signal.aborted || descartado || captura.value?.capturaId !== identificador)
          return
        guardarCaptura(actual, persona.value ?? undefined)
        mensajeError.value = ''
        if (cierreSolicitado && esActiva(actual)) await cancelarInterno()
      } catch (fallo) {
        if (controlador.signal.aborted || descartado) return
        if (await manejarSesionVencida(fallo)) return
        mensajeError.value =
          fallo instanceof ErrorRfid1Api
            ? fallo.message
            : 'No pudimos confirmar el estado de la captura. Revisa tu conexión e inténtalo de nuevo.'
        fase.value = 'error'
      } finally {
        if (controladorEstado === controlador) controladorEstado = null
        consultaEstadoEnCurso = null
        programarReconciliacion()
      }
    })()
    consultaEstadoEnCurso = tarea
    return tarea
  }

  function abrir(destino: PersonaRfid1) {
    if (inicioEnCurso || cancelacionEnCurso) return
    persona.value = destino
    captura.value = null
    claveInicio = null
    cierreSolicitado = false
    mensajeError.value = ''
    fase.value = 'revisando'
    abierta.value = true
    escucharCambios()
    void recuperarActiva(true).then((actual) => {
      if (!actual && !descartado && abierta.value && fase.value !== 'error') fase.value = 'lista'
    })
  }

  async function iniciar() {
    const destino = persona.value
    if (!destino || inicioEnCurso || cancelacionEnCurso || esActiva(captura.value)) return
    if (!import.meta.client) return
    inicioEnCurso = true
    cierreSolicitado = false
    fase.value = 'iniciando'
    mensajeError.value = ''
    claveInicio ??= crypto.randomUUID()
    escucharCambios()
    try {
      const token = await csrf.obtener()
      const solicitud: SolicitudCapturaRfid1 = {
        tipoEntidad: destino.tipoEntidad,
        codigoPersona: destino.codigo,
      }
      const respuesta = await api.iniciar(solicitud, claveInicio, token)
      if (descartado) return
      guardarCaptura(
        {
          ...respuesta,
          tipoEntidad: destino.tipoEntidad,
          codigoPersona: destino.codigo,
          resultado: null,
          codigoError: null,
        },
        destino,
      )
      claveInicio = null
      if (cierreSolicitado || !abierta.value) {
        cierreSolicitado = true
        await cancelarInterno()
        return
      }
      await reconciliar()
    } catch (fallo) {
      if (descartado) return
      if (await manejarSesionVencida(fallo)) return
      const errorApi = fallo instanceof ErrorRfid1Api ? fallo : null
      if (errorApi?.codigo === 'CSRF_RECHAZADO') csrf.limpiar()
      if (
        errorApi?.codigo === 'CAPTURA_EN_CURSO' ||
        errorApi?.estado === 0 ||
        (errorApi?.estado ?? 0) >= 500
      ) {
        const actual = await recuperarActiva(true)
        if (actual) {
          claveInicio = null
          if (cierreSolicitado) await cancelarInterno()
          return
        }
      }
      if (cierreSolicitado) {
        abierta.value = false
        persona.value = null
        fase.value = 'lista'
        cierreSolicitado = false
        return
      }
      if (!abierta.value && !captura.value) return
      mensajeError.value =
        fallo instanceof ErrorRfid1Api
          ? fallo.message
          : 'No pudimos iniciar la captura. Revisa tu conexión e inténtalo de nuevo.'
      fase.value = 'error'
    } finally {
      inicioEnCurso = false
    }
  }

  /** Cancela la lectura y, si no se confirma el cierre, consulta su estado
   * antes de cerrar la pantalla.
   */
  async function cancelarInterno() {
    const actual = captura.value
    if (!actual || !esActiva(actual) || cancelacionEnCurso) return
    controladorEstado?.abort()
    controladorEstado = null
    consultaEstadoEnCurso = null
    cancelacionEnCurso = true
    fase.value = 'cancelando'
    mensajeError.value = ''
    try {
      const token = await csrf.obtener()
      await api.cancelar(actual.capturaId, token)
      if (descartado) return
      guardarCaptura({ ...actual, estado: 'CANCELADA' }, persona.value ?? undefined)
      cierreSolicitado = false
      abierta.value = false
      fase.value = 'lista'
    } catch (fallo) {
      if (descartado) return
      if (await manejarSesionVencida(fallo)) return
      if (fallo instanceof ErrorRfid1Api && fallo.codigo === 'CSRF_RECHAZADO') csrf.limpiar()
      mensajeError.value = 'Comprobando el estado antes de cerrar la captura…'
      await reconciliar()
      const confirmado = captura.value
      if (confirmado?.estado === 'CANCELADA') {
        abierta.value = false
        fase.value = 'lista'
        cierreSolicitado = false
      } else if (confirmado?.estado === 'COMPLETADA') {
        cierreSolicitado = false
        abierta.value = true
        mensajeError.value = ''
      } else if (confirmado?.estado === 'EXPIRADA' || confirmado?.estado === 'RECHAZADA') {
        cierreSolicitado = false
        abierta.value = true
        mensajeError.value = ''
      } else {
        fase.value = 'error'
        mensajeError.value =
          'No pudimos confirmar la cancelación. La captura sigue abierta; vuelve a intentarlo.'
      }
    } finally {
      cancelacionEnCurso = false
    }
  }

  async function actualizarApertura(valor: boolean) {
    if (valor) {
      abierta.value = true
      return
    }
    if (inicioEnCurso || fase.value === 'revisando') {
      cierreSolicitado = true
      mensajeError.value = 'Confirmando el estado antes de cerrar…'
      return
    }
    const actual = captura.value
    if (esActiva(actual)) {
      cierreSolicitado = true
      await cancelarInterno()
      return
    }
    abierta.value = false
    mensajeError.value = ''
    fase.value = 'lista'
    limpiarTemporizadores()
    dejarDeEscuchar()
  }

  async function reintentar() {
    mensajeError.value = ''
    if (captura.value) await reconciliar()
    else await recuperarActiva(true)
  }

  onMounted(() => {
    void recuperarActiva(true)
  })
  onScopeDispose(() => {
    descartado = true
    limpiarTemporizadores()
    dejarDeEscuchar()
    controladorEstado?.abort()
  })

  return {
    abierta,
    persona,
    captura,
    fase,
    mensajeError,
    trabajando,
    segundosRestantes,
    abrir,
    iniciar,
    cancelar: cancelarInterno,
    actualizarApertura,
    reintentar,
  }
}
