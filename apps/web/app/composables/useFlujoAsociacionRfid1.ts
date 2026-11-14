import { computed, onMounted, onScopeDispose, ref, watch, type Ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import type {
  CandidatoPersonaRfid1,
  CapturaRfid1,
  FiltroTipoEntidadRfid1,
  PersonaRfid1,
  VistaPreviaRfid1,
} from '~/types/rfid1'
import { ErrorRfid1Api, useClienteRfid1 } from '~/utils/rfid1-api'
import { useBusquedaPersonasRfid1 } from './useBusquedaPersonasRfid1'
import { useCancelacionCapturaRfid1 } from './useCancelacionCapturaRfid1'
import { useVigenciaCapturaRfid1 } from './useVigenciaCapturaRfid1'

type PasoAsociacion = 1 | 2 | 3
type FaseAsociacion = 'lista' | 'iniciando' | 'escaneando' | 'confirmando' | 'cancelando'

const ESTADOS_ACTIVOS = new Set(['PENDIENTE', 'ESCANEANDO', 'VISTA_PREVIA'])
/** Guía la asignación de una tarjeta: permite buscar y elegir a la persona,
 * leer la tarjeta, revisar el número leído y confirmar o cancelar la asociación.
 */
export function useFlujoAsociacionRfid1(tipoInicial: Ref<FiltroTipoEntidadRfid1>) {
  const api = useClienteRfid1()
  const csrf = useCsrf()
  const sesion = useSesion()
  const abierta = ref(false)
  const paso = ref<PasoAsociacion>(1)
  const seleccionada = ref<CandidatoPersonaRfid1 | null>(null)
  const personaCaptura = ref<PersonaRfid1 | null>(null)
  const captura = ref<CapturaRfid1 | null>(null)
  const vistaPrevia = ref<VistaPreviaRfid1 | null>(null)
  const fase = ref<FaseAsociacion>('lista')
  const mensajeError = ref('')
  const mensajeCaptura = ref('')
  const ocupado = computed(() => ['iniciando', 'confirmando', 'cancelando'].includes(fase.value))
  const habilitadaBusqueda = computed(() => abierta.value && paso.value === 1)

  let claveInicio: string | null = null
  let claveConfirmacion: string | null = null
  let controladorEstado: AbortController | null = null
  let consultaEstado: Promise<void> | null = null
  let descartado = false
  const busquedaPersonas = useBusquedaPersonasRfid1(habilitadaBusqueda, manejarSesionVencida)
  const {
    tipoEntidad,
    busqueda,
    candidatos,
    pendientes: candidatosPendientes,
    error: errorBusqueda,
    cambiarTipo: cambiarTipoBuscada,
    seleccionar: seleccionarBuscada,
    limpiar: limpiarBusqueda,
    limpiarSeleccion: limpiarBusquedaSeleccionada,
  } = busquedaPersonas
  const vigencia = useVigenciaCapturaRfid1(abierta, captura, vistaPrevia, reconciliar)
  function capturaActiva(valor = captura.value) {
    return Boolean(valor && ESTADOS_ACTIVOS.has(valor.estado))
  }
  function limpiarReconciliacion() {
    vigencia.detener()
    controladorEstado?.abort()
    controladorEstado = null
  }
  function limpiarDatosTemporales() {
    vistaPrevia.value = null
    captura.value = null
    personaCaptura.value = null
    claveInicio = null
    claveConfirmacion = null
    mensajeCaptura.value = ''
    limpiarReconciliacion()
  }
  function limpiarFlujo() {
    limpiarDatosTemporales()
    limpiarBusqueda()
    abierta.value = false
    paso.value = 1
    busquedaPersonas.cambiarTipo(tipoInicial.value)
    limpiarBusquedaSeleccionada()
    seleccionada.value = null
    fase.value = 'lista'
    mensajeError.value = ''
    errorBusqueda.value = ''
  }
  async function manejarSesionVencida(fallo: unknown) {
    if (!(fallo instanceof ErrorRfid1Api) || fallo.estado !== 401) return false
    limpiarFlujo()
    await sesion.limpiar()
    await navigateTo('/panel')
    return true
  }

  function cambiarTipo(valor: FiltroTipoEntidadRfid1) {
    if (tipoEntidad.value === valor) return
    cambiarTipoBuscada(valor)
    seleccionada.value = null
  }
  function seleccionar(candidato: CandidatoPersonaRfid1) {
    seleccionada.value = seleccionarBuscada(candidato)
  }

  function actualizarBusqueda(valor: string) {
    if (busqueda.value === valor) return
    seleccionada.value = null
    busqueda.value = valor
    mensajeError.value = ''
  }

  function cambiarPersona() {
    if (paso.value !== 1 || capturaActiva()) return false
    seleccionada.value = null
    limpiarBusquedaSeleccionada()
    mensajeError.value = ''
    return true
  }

  function abrir() {
    if (abierta.value) return
    limpiarFlujo()
    abierta.value = true
  }
  function guardarCaptura(valor: CapturaRfid1, persona?: PersonaRfid1) {
    captura.value = valor
    personaCaptura.value = persona ?? {
      tipoEntidad: valor.tipoEntidad,
      codigo: valor.codigoPersona,
      nombreCompleto: `${valor.tipoEntidad === 'CLIENTE' ? 'Cliente' : 'Empleado'} ${valor.codigoPersona}`,
    }
    abierta.value = true
    paso.value = valor.estado === 'VISTA_PREVIA' ? 3 : 2
    fase.value = valor.estado === 'VISTA_PREVIA' ? 'lista' : 'escaneando'
    vigencia.escuchar()
    vigencia.programar()
  }

  async function leerVistaPrevia(capturaId: string) {
    const respuesta = await api.consultarVistaPrevia(capturaId, controladorEstado?.signal)
    if (descartado || captura.value?.capturaId !== capturaId) return
    vistaPrevia.value = respuesta
    paso.value = 3
    fase.value = 'lista'
    mensajeCaptura.value = ''
  }
  async function aplicarEstado(valor: CapturaRfid1) {
    captura.value = valor
    if (valor.estado === 'VISTA_PREVIA') {
      if (!vistaPrevia.value) {
        try {
          await leerVistaPrevia(valor.capturaId)
        } catch (fallo) {
          if (await manejarSesionVencida(fallo)) return
          mensajeError.value =
            fallo instanceof ErrorRfid1Api
              ? fallo.message
              : 'No pudimos recuperar la vista previa. Consulta el estado e inténtalo de nuevo.'
        }
      }
      paso.value = 3
      return
    }

    vistaPrevia.value = null
    if (['COMPLETADA', 'EXPIRADA', 'CANCELADA', 'RECHAZADA'].includes(valor.estado)) paso.value = 2
    if (valor.estado === 'ESCANEANDO' && valor.codigoError === 'TARJETA_YA_REGISTRADA') {
      mensajeCaptura.value = 'Tarjeta usada. Presenta otra.'
    } else if (valor.estado === 'PENDIENTE') {
      mensajeCaptura.value = 'El lector está preparando la captura.'
    } else if (valor.estado === 'ESCANEANDO') {
      mensajeCaptura.value = 'Presenta la tarjeta al lector para continuar.'
    } else if (valor.estado === 'COMPLETADA') {
      mensajeCaptura.value = 'La asociación ya fue confirmada.'
    } else if (valor.estado === 'EXPIRADA') {
      mensajeCaptura.value = 'La captura venció. Inicia otra lectura para continuar.'
    } else if (valor.estado === 'CANCELADA') {
      mensajeCaptura.value = 'La captura se canceló.'
    } else if (valor.estado === 'RECHAZADA') {
      mensajeCaptura.value = 'La persona dejó de ser elegible. Selecciona otra persona.'
    }
    fase.value = 'lista'
    if (!capturaActiva(valor)) limpiarReconciliacion()
  }

/** Pregunta al servidor por la lectura activa tras un aviso o una respuesta fallida,
 * para mostrar el resultado que quedó guardado.
 */
  async function reconciliar() {
    const actual = captura.value
    if (!actual || !import.meta.client || descartado) return
    if (consultaEstado) return consultaEstado
    const controlador = new AbortController()
    controladorEstado?.abort()
    controladorEstado = controlador
    const tarea = (async () => {
      try {
        const estadoActual = await api.consultar(actual.capturaId, controlador.signal)
        if (controlador.signal.aborted || captura.value?.capturaId !== actual.capturaId) return
        await aplicarEstado(estadoActual)
        mensajeError.value = ''
      } catch (fallo) {
        if (controlador.signal.aborted || descartado) return
        if (await manejarSesionVencida(fallo)) return
        mensajeError.value =
          fallo instanceof ErrorRfid1Api
            ? fallo.message
            : 'No pudimos consultar la captura. Revisa la conexión e inténtalo de nuevo.'
      } finally {
        if (controladorEstado === controlador) controladorEstado = null
        consultaEstado = null
        vigencia.programar()
      }
    })()
    consultaEstado = tarea
    return tarea
  }

  async function iniciarLectura() {
    const destino = seleccionada.value
    if (!destino || ocupado.value || capturaActiva()) return false
    if (!import.meta.client) return false
    fase.value = 'iniciando'
    mensajeError.value = ''
    mensajeCaptura.value = ''
    claveInicio ??= crypto.randomUUID()
    try {
      const respuesta = await api.iniciar(
        { tipoEntidad: destino.tipoEntidad, codigoPersona: destino.codigoPersona },
        claveInicio,
        await csrf.obtener(),
      )
      claveInicio = null
      guardarCaptura(
        {
          ...respuesta,
          tipoEntidad: destino.tipoEntidad,
          codigoPersona: destino.codigoPersona,
          resultado: null,
          codigoError: null,
        },
        {
          tipoEntidad: destino.tipoEntidad,
          codigo: destino.codigoPersona,
          nombreCompleto: destino.nombreCompleto,
        },
      )
      void reconciliar()
      return true
    } catch (fallo) {
      if (await manejarSesionVencida(fallo)) return false
      if (
        fallo instanceof ErrorRfid1Api &&
        (fallo.codigo === 'CAPTURA_EN_CURSO' || fallo.estado === 0 || fallo.estado >= 500)
      ) {
        try {
          const activa = await api.consultarActiva()
          if (activa) {
            guardarCaptura(activa, {
              tipoEntidad: activa.tipoEntidad,
              codigo: activa.codigoPersona,
              nombreCompleto: destino.nombreCompleto,
            })
            claveInicio = null
            void reconciliar()
            return true
          }
        } catch (reconciliacion) {
          if (await manejarSesionVencida(reconciliacion)) return false
        }
      }
      mensajeError.value =
        fallo instanceof ErrorRfid1Api
          ? fallo.message
          : 'No pudimos iniciar el lector. Consulta su estado antes de volver a intentarlo.'
      fase.value = 'lista'
      return false
    }
  }

  async function recuperarActiva() {
    if (!import.meta.client || descartado || captura.value) return
    try {
      const activa = await api.consultarActiva()
      if (!activa || descartado) return
      guardarCaptura(activa)
      if (activa.estado === 'VISTA_PREVIA') await leerVistaPrevia(activa.capturaId)
    } catch (fallo) {
      if (await manejarSesionVencida(fallo)) return
      mensajeError.value =
        fallo instanceof ErrorRfid1Api ? fallo.message : 'No pudimos recuperar una captura activa.'
    }
  }
/** Confirma la asociación; si no llega una respuesta clara, consulta primero
 * qué ocurrió para evitar enviar la confirmación otra vez a ciegas.
 */
  async function confirmarAsociacion() {
    const actual = captura.value
    if (actual?.estado !== 'VISTA_PREVIA' || !vistaPrevia.value || ocupado.value) return false
    if ((vigencia.segundosRestantes.value ?? 0) <= 0) {
      await reconciliar()
      return false
    }
    fase.value = 'confirmando'
    mensajeError.value = ''
    claveConfirmacion ??= crypto.randomUUID()
    try {
      await api.confirmar(actual.capturaId, claveConfirmacion, await csrf.obtener())
      limpiarFlujo()
      return true
    } catch (fallo) {
      if (await manejarSesionVencida(fallo)) return false
      const respuestaIncierta =
        fallo instanceof ErrorRfid1Api && (fallo.estado === 0 || fallo.estado >= 500)
      if (!respuestaIncierta) {
        mensajeError.value =
          fallo instanceof ErrorRfid1Api
            ? fallo.message
            : 'No pudimos confirmar. Consulta el estado antes de volver a intentarlo.'
      }
      await reconciliar()
      if (captura.value?.estado === 'COMPLETADA') {
        limpiarFlujo()
        return true
      }
      if (respuestaIncierta) {
        mensajeError.value =
          'No recibimos la respuesta. Consultamos el estado de la captura; vuelve a confirmar con la misma clave si sigue pendiente.'
      }
      fase.value = 'lista'
      return false
    }
  }

  const cancelarCaptura = useCancelacionCapturaRfid1({
    captura,
    vistaPrevia,
    fase,
    mensajeError,
    mensajeCaptura,
    activa: capturaActiva,
    manejarSesionVencida,
    aplicarEstado,
  })

  async function volverASeleccion() {
    if (capturaActiva() && !(await cancelarCaptura())) return false
    limpiarDatosTemporales()
    paso.value = 1
    seleccionada.value = null
    busqueda.value = ''
    mensajeError.value = ''
    fase.value = 'lista'
    return true
  }

  async function escanearOtraTarjeta() {
    if (capturaActiva() && !(await cancelarCaptura())) return false
    limpiarDatosTemporales()
    paso.value = 2
    fase.value = 'lista'
    return iniciarLectura()
  }

  async function cerrar() {
    if (ocupado.value) {
      mensajeError.value = 'Espera a que termine la solicitud actual antes de cerrar.'
      return false
    }
    if (capturaActiva() && !(await cancelarCaptura())) return false
    limpiarFlujo()
    return true
  }

  async function manejarCambioRuta() {
    if (ocupado.value) {
      mensajeError.value = 'Espera a que termine la solicitud actual antes de salir.'
      return false
    }
    return !(capturaActiva() && !(await cancelarCaptura()))
  }

  watch(
    () => sesion.sesion.value.estado,
    (estado) => {
      if (estado !== 'autenticada') limpiarFlujo()
    },
  )

  onBeforeRouteLeave(manejarCambioRuta)
  onMounted(() => void recuperarActiva())
  onScopeDispose(() => {
    descartado = true
    limpiarBusqueda()
    limpiarReconciliacion()
    vistaPrevia.value = null
  })

  return {
    abierta,
    paso,
    tipoEntidad,
    busqueda,
    candidatos,
    candidatosPendientes,
    errorBusqueda,
    seleccionada,
    personaCaptura,
    captura,
    vistaPrevia,
    fase,
    mensajeError,
    mensajeCaptura,
    segundosRestantes: vigencia.segundosRestantes,
    ocupado,
    abrir,
    cambiarTipo,
    actualizarBusqueda,
    cambiarPersona,
    seleccionar,
    iniciarLectura,
    confirmarAsociacion,
    cancelarCaptura,
    volverASeleccion,
    escanearOtraTarjeta,
    cerrar,
    reconciliar,
  }
}
