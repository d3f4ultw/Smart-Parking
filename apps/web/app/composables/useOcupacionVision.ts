import type { CajonVision } from '~/types/vision'
import { ErrorVisionApi, useClienteVision, type LecturaVision } from '~/utils/vision-api'

type EstadoOcupacion = 'cargando' | 'actual' | 'historico' | 'error' | 'sin-sesion'
type VigenciaLectura = 'valida' | 'ttl-invalido' | 'plazo-consumido'

interface ResultadoOcupacion {
  estado: EstadoOcupacion
  datos: CajonVision[] | null
  ultimaConsulta: string | null
  mensaje: string
  cursor?: string | null
  vigenciaRestanteMs?: number | null
  inicioClienteMs?: number | null
  acceso?: 401 | 403
}

const INTERVALO_RECONCILIACION = 30_000
const INTERVALO_SIN_STREAM = 5_000
const COALESCENCIA_EVENTOS = 100
const LIMITE_CONSULTA = 8_000
const RETRASOS_REINTENTO = [5_000, 10_000, 20_000, 30_000] as const

function resultadoInicial(): ResultadoOcupacion {
  return { estado: 'cargando', datos: null, ultimaConsulta: null, mensaje: '' }
}

/** Actualiza la ocupación cuando el área está abierta y la sesión permite verla;
 * al vencer los datos, deja de mostrarlos como actuales y vuelve a consultar.
 */
export async function useOcupacionVision() {
  const alcance = getCurrentScope()
  const ruta = useRoute()
  const api = useClienteVision()
  const csrf = useCsrf()
  const { sesion, limpiar: limpiarSesion, actualizar: actualizarSesion } = useSesion()
  const identidadModulo = computed(() => {
    const actual = sesion.value
    if (actual.estado !== 'autenticada') return null
    const { rol, correo } = actual.identidad
    const rutaPropietario = ruta.path === '/admin' || ruta.path === '/admin/vision'
    const rutaOperador = ruta.path === '/operador/monitoreo'
    return (rol === 'DUENO' && rutaPropietario) || (rol === 'OPERADOR' && rutaOperador)
      ? `${rol}:${correo}`
      : null
  })

  function enRutaConOcupacion() {
    return (
      ruta.path === '/admin' || ruta.path === '/admin/vision' || ruta.path === '/operador/monitoreo'
    )
  }

  // Antes de esperar la consulta, registra qué hacer cuando la vista se abre o se cierra;
  // así esas acciones quedan asociadas a esta pantalla.
  let montar = () => {}
  let desmontar = () => {}
  onMounted(() => montar())
  onScopeDispose(() => desmontar())

  /** Cancela la consulta si tarda más de ocho segundos o si la vista deja de necesitarla. */
  async function consultarConLimite(signal: AbortSignal): Promise<LecturaVision> {
    const controlador = new AbortController()
    const cancelar = () => controlador.abort()
    if (signal.aborted) cancelar()
    else signal.addEventListener('abort', cancelar, { once: true })
    const limite = setTimeout(cancelar, LIMITE_CONSULTA)
    try {
      return await api.listar(controlador.signal)
    } finally {
      clearTimeout(limite)
      signal.removeEventListener('abort', cancelar)
    }
  }

  const resultado = await useAsyncData<ResultadoOcupacion>(
    'ocupacion-vision-propietario',
    async (_nuxtApp, { signal }) => {
      const identidad = identidadModulo.value
      if (!identidad) {
        return { estado: 'sin-sesion', datos: null, ultimaConsulta: null, mensaje: '' }
      }
      const inicioClienteMs = import.meta.client ? performance.now() : null
      try {
        const lectura = await consultarConLimite(signal)
        if (signal.aborted || identidadModulo.value !== identidad) {
          throw new DOMException('La sesión cambió', 'AbortError')
        }
        return {
          estado: 'actual',
          datos: lectura.cajones,
          cursor: lectura.cursor,
          vigenciaRestanteMs: lectura.vigenciaRestanteMs,
          inicioClienteMs,
          ultimaConsulta: new Date().toISOString(),
          mensaje: '',
        }
      } catch (fallo) {
        if (signal.aborted || identidadModulo.value !== identidad) throw fallo
        if (fallo instanceof ErrorVisionApi && (fallo.estado === 401 || fallo.estado === 403)) {
          return {
            estado: 'sin-sesion',
            datos: null,
            ultimaConsulta: null,
            mensaje:
              fallo.estado === 401
                ? 'Tu acceso venció. Inicia sesión de nuevo.'
                : 'No tienes acceso para consultar la ocupación.',
            acceso: fallo.estado,
          }
        }
        return {
          estado: 'error',
          datos: null,
          ultimaConsulta: null,
          mensaje: 'No pudimos actualizar la ocupación. Revisa tu conexión e inténtalo de nuevo.',
        }
      }
    },
    { default: resultadoInicial, dedupe: 'defer' },
  )

  const consultaActiva = ref(false)
  const datos = computed(() => resultado.data.value as ResultadoOcupacion)
  const cajones = computed(() => datos.value.datos ?? [])
  const hayDatos = computed(() => datos.value.datos !== null)
  const estado = computed(() => datos.value.estado)
  const desactualizado = computed(() => hayDatos.value && estado.value !== 'actual')
  const mensajeError = computed(() => datos.value.mensaje)
  const ultimaConsulta = computed(() => datos.value.ultimaConsulta)
  const pendiente = computed(() => resultado.pending.value || consultaActiva.value)

  let activo = false
  let identidadDatos = hayDatos.value ? identidadModulo.value : null
  let montado = false
  let requiereRevalidacion = false
  let generacion = 0
  let fallos = datos.value.estado === 'error' ? 1 : 0
  let temporizador: ReturnType<typeof setTimeout> | undefined
  let controladorActual: AbortController | undefined
  let solicitudActual: Promise<void> | undefined
  let cancelarSuscripcion: (() => void) | undefined
  let escuchando = false
  let invalidacionPendiente = false
  let proximaConsulta: number | null = null
  let venceVigencia: number | null = null
  let noAntes = 0
  let streamInterrumpido = false

  function cancelarTemporizador() {
    if (temporizador !== undefined) clearTimeout(temporizador)
    temporizador = undefined
  }

  function puedeConsultar() {
    return (
      activo &&
      (identidadModulo.value !== null || requiereRevalidacion) &&
      enRutaConOcupacion() &&
      document.visibilityState === 'visible' &&
      navigator.onLine
    )
  }

  function guardarHistorico(mensaje: string) {
    const anterior = datos.value
    resultado.data.value = {
      ...anterior,
      estado: anterior.datos === null ? 'error' : 'historico',
      mensaje,
    }
  }

  function fijarVigencia(inicio: number, lectura: ResultadoOcupacion): VigenciaLectura {
    venceVigencia = null
    const hayEstadoVigente = lectura.datos?.some((cajon) => cajon.estado !== 'NO_VERIFICABLE')
    if (!hayEstadoVigente) return 'valida'
    const ttl = lectura.vigenciaRestanteMs
    if (typeof ttl !== 'number' || !Number.isSafeInteger(ttl) || ttl <= 0) {
      guardarHistorico(
        'No pudimos confirmar la vigencia de la ocupación. Se actualizará automáticamente.',
      )
      return 'ttl-invalido'
    }
    const limite = inicio + ttl
    if (
      !Number.isFinite(inicio) ||
      inicio < 0 ||
      !Number.isFinite(limite) ||
      limite <= performance.now()
    ) {
      guardarHistorico('La ocupación anterior venció. Se actualizará automáticamente.')
      return 'plazo-consumido'
    }
    venceVigencia = limite
    return 'valida'
  }

  function programar() {
    cancelarTemporizador()
    // La vigencia del último estado confirmado también vence si la página
    // está en segundo plano o perdió conexión; las consultas sí se pausan.
    const puedeActualizar = puedeConsultar()
    const candidatoConsulta = puedeActualizar && !solicitudActual ? proximaConsulta : null
    const fechas = [venceVigencia, candidatoConsulta].filter(
      (valor): valor is number => valor !== null,
    )
    if (!fechas.length) return
    temporizador = setTimeout(
      () => {
        temporizador = undefined
        const ahora = performance.now()
        if (venceVigencia !== null && venceVigencia <= ahora) {
          venceVigencia = null
          guardarHistorico('La ocupación anterior venció. Se actualizará automáticamente.')
          invalidacionPendiente = true
          if (puedeConsultar()) {
            const fecha = Math.max(ahora, noAntes)
            proximaConsulta = proximaConsulta === null ? fecha : Math.min(proximaConsulta, fecha)
          }
        }
        if (!puedeConsultar()) return
        if (!solicitudActual && proximaConsulta !== null && proximaConsulta <= ahora) {
          void ejecutarConsulta()
        } else programar()
      },
      Math.max(0, Math.ceil(Math.min(...fechas) - performance.now())),
    )
  }

  function solicitarRefresco(retraso = COALESCENCIA_EVENTOS) {
    if (!puedeConsultar()) return
    invalidacionPendiente = true
    const fecha = Math.max(performance.now() + retraso, noAntes)
    proximaConsulta = proximaConsulta === null ? fecha : Math.min(proximaConsulta, fecha)
    programar()
  }

  function detenerSuscripcion() {
    cancelarSuscripcion?.()
    cancelarSuscripcion = undefined
    streamInterrumpido = false
  }

  function iniciarSuscripcion() {
    if (!puedeConsultar() || requiereRevalidacion || cancelarSuscripcion) return
    cancelarSuscripcion = useNuxtApp().$eventosAdministracion.suscribir(
      () => solicitarRefresco(),
      datos.value.cursor ?? undefined,
      'vision.ocupacion.actualizada',
      (reconciliar) => {
        if (reconciliar) solicitarRefresco()
      },
      {
        interrumpida: () => {
          streamInterrumpido = true
          // El SSE acelera las actualizaciones, pero el TTL del servidor
          // determina cuánto tiempo sigue vigente el último estado.
          solicitarRefresco()
        },
        recuperada: () => {
          streamInterrumpido = false
          solicitarRefresco()
        },
      },
    )
  }

  function pausar() {
    if (!activo) return
    detenerSuscripcion()
    streamInterrumpido = false
    cancelarTemporizador()
    generacion += 1
    controladorActual?.abort()
    invalidacionPendiente = false
    proximaConsulta = null
    // Conserva el último estado mientras siga dentro de su vigencia conocida.
    // programar() mantiene solo el vencimiento hasta que la vista se reanude.
    programar()
  }

  function detener(borrar: boolean) {
    activo = false
    generacion += 1
    detenerSuscripcion()
    cancelarTemporizador()
    controladorActual?.abort()
    invalidacionPendiente = false
    proximaConsulta = null
    venceVigencia = null
    if (escuchando && import.meta.client) {
      document.removeEventListener('visibilitychange', cambiarVisibilidad)
      window.removeEventListener('offline', cambiarConexion)
      window.removeEventListener('online', cambiarConexion)
      escuchando = false
    }
    if (borrar) {
      identidadDatos = null
      resultado.clear()
    }
  }

  async function perderSesion(limpiarCsrf = false) {
    detener(true)
    limpiarSesion()
    if (limpiarCsrf) csrf.limpiar()
    await navigateTo('/panel')
  }

  function mostrarErrorAcceso(conservarDatos = false) {
    const mensaje = 'No pudimos confirmar tu acceso a la ocupación. Reintentaremos automáticamente.'
    if (conservarDatos && identidadDatos && hayDatos.value) {
      guardarHistorico(mensaje)
      return
    }
    identidadDatos = null
    resultado.data.value = {
      estado: 'error',
      datos: null,
      ultimaConsulta: null,
      mensaje,
    }
  }

  function activar() {
    if (!montado || !enRutaConOcupacion()) return
    activo = true
    if (!escuchando) {
      document.addEventListener('visibilitychange', cambiarVisibilidad)
      window.addEventListener('offline', cambiarConexion)
      window.addEventListener('online', cambiarConexion)
      escuchando = true
    }
  }

  async function revalidarSesion(): Promise<boolean> {
    let falloComprobacion = false
    try {
      await actualizarSesion()
    } catch {
      falloComprobacion = true
    }
    if (!montado || !enRutaConOcupacion()) return false
    if (sesion.value.estado === 'anonima') {
      await perderSesion(true)
      return false
    }
    if (sesion.value.estado === 'autenticada' && identidadModulo.value === null) {
      denegarAcceso()
      return false
    }
    requiereRevalidacion = falloComprobacion || sesion.value.estado !== 'autenticada'
    if (requiereRevalidacion) mostrarErrorAcceso(true)
    activar()
    return !requiereRevalidacion
  }

  function denegarAcceso() {
    detener(false)
    identidadDatos = null
    resultado.data.value = {
      estado: 'sin-sesion',
      datos: null,
      ultimaConsulta: null,
      mensaje: 'No tienes acceso para consultar la ocupación.',
      acceso: 403,
    }
  }

  function puedeConservarLecturaFallida(): boolean {
    const lectura = datos.value
    if (lectura.estado !== 'actual' || !lectura.datos) return false
    const vigenciaConfirmada = venceVigencia !== null && venceVigencia > performance.now()
    const sinEstadosFisicosConfirmados =
      lectura.datos.length > 0 && lectura.datos.every((cajon) => cajon.estado === 'NO_VERIFICABLE')
    return vigenciaConfirmada || sinEstadosFisicosConfirmados
  }

  async function ejecutarConsulta(): Promise<void> {
    cancelarTemporizador()
    if (!puedeConsultar()) return
    if (solicitudActual) {
      invalidacionPendiente = true
      programar()
      return solicitudActual
    }
    proximaConsulta = null
    invalidacionPendiente = false
    const identidad = identidadModulo.value
    const turno = generacion
    const controlador = new AbortController()
    controladorActual = controlador
    consultaActiva.value = true
    const vigente = () =>
      activo && turno === generacion && identidadModulo.value === identidad && enRutaConOcupacion()

    solicitudActual = (async () => {
      try {
        if (requiereRevalidacion) {
          const recuperada = await revalidarSesion()
          if (!recuperada) {
            fallos += 1
            return
          }
          fallos = 0
          invalidacionPendiente = true
          iniciarSuscripcion()
          return
        }
        const inicio = performance.now()
        const lectura = await consultarConLimite(controlador.signal)
        if (!vigente()) return
        identidadDatos = identidad
        resultado.data.value = {
          estado: 'actual',
          datos: lectura.cajones,
          cursor: lectura.cursor,
          vigenciaRestanteMs: lectura.vigenciaRestanteMs,
          inicioClienteMs: inicio,
          ultimaConsulta: new Date().toISOString(),
          mensaje: '',
        }
        const vigencia = fijarVigencia(inicio, datos.value)
        fallos = vigencia === 'valida' ? 0 : fallos + 1
        noAntes = 0
      } catch (fallo) {
        if (!vigente() || controlador.signal.aborted) return
        if (fallo instanceof ErrorVisionApi) {
          if (fallo.estado === 401) {
            mostrarErrorAcceso()
            detenerSuscripcion()
            venceVigencia = null
            fallos += 1
            requiereRevalidacion = true
            await revalidarSesion()
            if (!requiereRevalidacion && activo) {
              invalidacionPendiente = true
              iniciarSuscripcion()
            }
            return
          }
          if (fallo.estado === 403) {
            denegarAcceso()
            return
          }
        }
        fallos += 1
        if (!puedeConservarLecturaFallida()) {
          venceVigencia = null
          guardarHistorico('No pudimos actualizar la ocupación. Reintentaremos automáticamente.')
        }
      } finally {
        if (controladorActual === controlador) controladorActual = undefined
        consultaActiva.value = false
        solicitudActual = undefined
        if (activo && puedeConsultar()) {
          const ahora = performance.now()
          noAntes =
            fallos > 0
              ? ahora + RETRASOS_REINTENTO[Math.min(fallos - 1, RETRASOS_REINTENTO.length - 1)]!
              : 0
          if (invalidacionPendiente) {
            proximaConsulta = Math.max(proximaConsulta ?? ahora + COALESCENCIA_EVENTOS, noAntes)
          } else {
            proximaConsulta = fallos
              ? noAntes
              : ahora + (streamInterrumpido ? INTERVALO_SIN_STREAM : INTERVALO_RECONCILIACION)
          }
          programar()
        }
      }
    })()
    // La espera de una consulta nueva no prolonga el tiempo durante el que
    // se puede mostrar como actual la última ocupación confirmada.
    programar()
    return solicitudActual
  }

  function actualizar(): Promise<void> {
    if (solicitudActual) {
      solicitarRefresco()
      return solicitudActual
    }
    noAntes = 0
    return ejecutarConsulta()
  }

  function reanudar() {
    if (!puedeConsultar()) return
    iniciarSuscripcion()
    solicitarRefresco(0)
  }

  function cambiarVisibilidad() {
    if (document.visibilityState !== 'visible' || !navigator.onLine) pausar()
    else reanudar()
  }

  function cambiarConexion() {
    if (!navigator.onLine || document.visibilityState !== 'visible') pausar()
    else reanudar()
  }

  montar = () => {
    montado = true
    if (!identidadModulo.value) {
      void perderSesion(sesion.value.estado === 'anonima')
      return
    }
    if (datos.value.acceso === 403) return
    activar()
    if (datos.value.acceso === 401) {
      mostrarErrorAcceso()
      requiereRevalidacion = true
      fallos = 1
      solicitarRefresco(0)
      return
    }
    if (!puedeConsultar()) {
      pausar()
      return
    }
    const vigenciaInicial =
      datos.value.estado === 'actual'
        ? fijarVigencia(datos.value.inicioClienteMs ?? 0, datos.value)
        : 'valida'
    if (vigenciaInicial === 'ttl-invalido') fallos = Math.max(1, fallos)
    noAntes = fallos ? performance.now() + RETRASOS_REINTENTO[0] : 0
    proximaConsulta = fallos ? noAntes : performance.now() + INTERVALO_RECONCILIACION
    iniciarSuscripcion()
    if (vigenciaInicial === 'plazo-consumido') solicitarRefresco()
    else programar()
  }

  desmontar = () => {
    montado = false
    if (import.meta.client) detener(!enRutaConOcupacion())
  }

  alcance?.run(() => {
    watch(
      identidadModulo,
      (actual, anterior) => {
        if (!actual || actual !== anterior) {
          const falloTemporal =
            !actual && sesion.value.estado === 'error' && montado && enRutaConOcupacion()
          const mismaIdentidad = actual !== null && actual === identidadDatos && hayDatos.value
          detener(!(falloTemporal || mismaIdentidad))
          if (actual && montado && enRutaConOcupacion()) {
            requiereRevalidacion = false
            fallos = 0
            noAntes = 0
            activar()
            iniciarSuscripcion()
            solicitarRefresco(0)
          } else if (falloTemporal) {
            requiereRevalidacion = true
            mostrarErrorAcceso(true)
            activar()
            fallos = Math.max(1, fallos)
            noAntes = performance.now() + RETRASOS_REINTENTO[0]
            proximaConsulta = noAntes
            programar()
          }
        }
      },
      { flush: 'sync' },
    )
    watch(
      () => ruta.path,
      () => {
        if (!enRutaConOcupacion()) {
          montado = false
          detener(true)
        }
      },
      { flush: 'sync' },
    )
  })

  return {
    cajones,
    pendiente,
    desactualizado,
    mensajeError,
    ultimaConsulta,
    hayDatos,
    estado,
    actualizar,
  }
}
