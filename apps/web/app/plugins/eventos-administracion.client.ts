import { watch } from 'vue'
import { esRutaModuloOperador } from '~/utils/rutas-modulos-operador'

type ReaccionEvento = () => void
/** Tipos de avisos que indican qué directorio o panel debe volver a consultar sus datos. */
type NombreEventoDirectorio =
  | 'empleado.directorio.actualizado'
  | 'operador.directorio.actualizado'
  | 'cliente.registrado'
  | 'membresia.actualizada'
  | 'rfid1.captura.actualizada'
  | 'rfid1.tarjetas.actualizadas'
  | 'acceso.historial.actualizado'
  | 'vision.ocupacion.actualizada'
type NombreEventoSse = NombreEventoDirectorio | 'administracion.directorio.resincronizar'
type AvisoCoberturaCursor = (requiereReconciliacion: boolean) => void
interface AvisosConexion {
  interrumpida?: () => void
  recuperada?: () => void
}
interface ConfirmacionHeartbeat {
  suscripcionId: string
  secuencia: number
}

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const RUTA_HEARTBEAT = '/api/v1/eventos/administracion/heartbeat'
const EVENTO_EMPLEADOS = 'empleado.directorio.actualizado'
const EVENTO_OPERADORES = 'operador.directorio.actualizado'
const EVENTO_CLIENTES = 'cliente.registrado'
const EVENTO_MEMBRESIA = 'membresia.actualizada'
const EVENTO_RFID1 = 'rfid1.captura.actualizada'
const EVENTO_TARJETAS_RFID1 = 'rfid1.tarjetas.actualizadas'
const EVENTO_ACCESO = 'acceso.historial.actualizado'
const EVENTO_VISION = 'vision.ocupacion.actualizada'
const EVENTO_RESINCRONIZACION = 'administracion.directorio.resincronizar'
const EVENTOS_OPERADOR = new Set<NombreEventoDirectorio>([
  EVENTO_CLIENTES,
  EVENTO_MEMBRESIA,
  EVENTO_RFID1,
  EVENTO_TARJETAS_RFID1,
  EVENTO_ACCESO,
  EVENTO_VISION,
])

function leerConfirmacionHeartbeat(datos: string): ConfirmacionHeartbeat | undefined {
  try {
    const valor: unknown = JSON.parse(datos)
    if (typeof valor !== 'object' || valor === null || Array.isArray(valor)) return
    const acuse = valor as Record<string, unknown>
    if (
      typeof acuse.suscripcionId !== 'string' ||
      !UUID_V4.test(acuse.suscripcionId) ||
      typeof acuse.secuencia !== 'number' ||
      !Number.isSafeInteger(acuse.secuencia) ||
      acuse.secuencia <= 0
    ) {
      return
    }
    return { suscripcionId: acuse.suscripcionId, secuencia: acuse.secuencia }
  } catch {
    return
  }
}

/** Funciones que permiten a una pantalla recibir avisos, saber si debe actualizar
 * sus datos y dejar de escucharlos cuando ya no los necesita.
 */
interface EventosAdministracionCliente {
  suscribir: (
    reaccion: ReaccionEvento,
    cursorInicial?: string,
    nombreEvento?: NombreEventoDirectorio,
    avisarCobertura?: AvisoCoberturaCursor,
    avisosConexion?: AvisosConexion,
  ) => () => void
}

declare module '#app' {
  interface NuxtApp {
    $eventosAdministracion: EventosAdministracionCliente
  }
}

declare module 'vue' {
  interface ComponentCustomProperties {
    $eventosAdministracion: EventosAdministracionCliente
  }
}

/** Mantiene una sola conexión para los avisos de cambios y la comparte entre pantallas;
 * al cambiar de usuario, rol o área, vuelve a abrir solo las novedades que puede ver.
 */
export default defineNuxtPlugin(() => {
  const { sesion, actualizar } = useSesion()
  const ruta = useRoute()
  const csrf = useCsrf()
  const reacciones = new Map<
    ReaccionEvento,
    { nombre: NombreEventoDirectorio; avisos?: AvisosConexion }
  >()
  const esperas = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000]
  let origen: EventSource | undefined
  let controladorHeartbeat: AbortController | undefined
  let cursor = ''
  let cursorPendiente = ''
  let cursorSolicitado = ''
  let flujoConHueco = false
  let temporizador: ReturnType<typeof setTimeout> | undefined
  let fallos = 0
  let validando = false
  let confirmacionPendiente:
    | { confirmacion: ConfirmacionHeartbeat; origen: EventSource; signal: AbortSignal }
    | undefined
  let procesandoConfirmaciones = false
  let generacion = 0
  let reconectando = false

  function esDueno() {
    return sesion.value?.estado === 'autenticada' && sesion.value.identidad.rol === 'DUENO'
  }

  function esOperadorEnModulo() {
    return (
      sesion.value?.estado === 'autenticada' &&
      sesion.value.identidad.rol === 'OPERADOR' &&
      esRutaModuloOperador(ruta.path)
    )
  }

  function puedeConectar() {
    return esDueno() || esOperadorEnModulo()
  }

  /** Decide si se procesa el aviso; para el operador, solo acepta los tipos previstos
   * mientras esté en una página de su área.
   */
  function puedeProcesarEvento(nombreEvento: NombreEventoSse) {
    return (
      esDueno() ||
      (esOperadorEnModulo() &&
        (nombreEvento === EVENTO_RESINCRONIZACION || EVENTOS_OPERADOR.has(nombreEvento)))
    )
  }

  function cerrarOrigen() {
    generacion += 1
    controladorHeartbeat?.abort()
    controladorHeartbeat = undefined
    origen?.close()
    origen = undefined
    confirmacionPendiente = undefined
  }

  function cancelarTemporizador() {
    if (temporizador) clearTimeout(temporizador)
    temporizador = undefined
  }

  function procesarEventoDirectorio(evento: Event, nombreEvento: NombreEventoSse) {
    const mensaje = evento as MessageEvent<string>
    if (mensaje.lastEventId) cursor = mensaje.lastEventId
    if (nombreEvento === EVENTO_RESINCRONIZACION) flujoConHueco = true
    fallos = 0
    for (const [reaccion, suscripcion] of reacciones) {
      if (nombreEvento === EVENTO_RESINCRONIZACION || suscripcion.nombre === nombreEvento)
        reaccion()
    }
  }

  /** Al reconectarse, pide los cambios posteriores al último aviso recibido
   * y escucha solo las novedades que puede ver el rol actual.
   */
  function conectar() {
    if (!reacciones.size || !puedeConectar() || origen) return
    const despues = cursor || cursorPendiente
    cursorSolicitado = despues
    flujoConHueco = false
    const consulta = despues ? `?despues=${encodeURIComponent(despues)}` : ''
    const nueva = new EventSource(`/api/v1/eventos/administracion${consulta}`)
    origen = nueva
    const controlador = new AbortController()
    controladorHeartbeat = controlador
    generacion += 1

    nueva.onopen = () => {
      if (origen !== nueva || !puedeConectar()) return
      fallos = 0
      if (reconectando) {
        reconectando = false
        for (const suscripcion of reacciones.values()) suscripcion.avisos?.recuperada?.()
      }
    }
    const nombresEventos: NombreEventoSse[] = esDueno()
      ? [
          EVENTO_EMPLEADOS,
          EVENTO_OPERADORES,
          EVENTO_CLIENTES,
          EVENTO_MEMBRESIA,
          EVENTO_RFID1,
          EVENTO_TARJETAS_RFID1,
          EVENTO_ACCESO,
          EVENTO_VISION,
          EVENTO_RESINCRONIZACION,
        ]
      : [...EVENTOS_OPERADOR, EVENTO_RESINCRONIZACION]
    for (const nombre of nombresEventos) {
      nueva.addEventListener(nombre, (evento) => {
        if (origen === nueva && puedeProcesarEvento(nombre))
          procesarEventoDirectorio(evento, nombre)
      })
    }
    nueva.addEventListener('empleado.heartbeat', (evento) => {
      if (origen !== nueva || !puedeConectar()) return
      const mensaje = evento as MessageEvent<string>
      const confirmacion = leerConfirmacionHeartbeat(mensaje.data)
      if (!confirmacion) return
      confirmacionPendiente = { confirmacion, origen: nueva, signal: controlador.signal }
      void enviarConfirmacionesHeartbeat()
    })
    nueva.onerror = () => {
      if (origen !== nueva) return
      reconectando = true
      for (const suscripcion of reacciones.values()) suscripcion.avisos?.interrumpida?.()
      cerrarOrigen()
      void validarSesionYReintentar(generacion)
    }
  }

  async function enviarConfirmacionesHeartbeat() {
    if (procesandoConfirmaciones) return
    procesandoConfirmaciones = true
    try {
      while (confirmacionPendiente) {
        const pendiente = confirmacionPendiente
        confirmacionPendiente = undefined
        try {
          const token = await csrf.obtener()
          if (
            origen !== pendiente.origen ||
            pendiente.signal.aborted ||
            !puedeConectar() ||
            !reacciones.size
          )
            continue
          await fetch(RUTA_HEARTBEAT, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'content-type': 'application/json', 'x-csrf-token': token },
            body: JSON.stringify(pendiente.confirmacion),
            signal: pendiente.signal,
          })
        } catch {
          // Si este envío falla, se conserva la confirmación más nueva que llegó mientras se esperaba.
        }
      }
    } finally {
      procesandoConfirmaciones = false
    }
  }

  function programarReconexion() {
    if (!reacciones.size || temporizador) return
    const demora = esperas[Math.min(fallos, esperas.length - 1)]
    fallos += 1
    temporizador = setTimeout(() => {
      temporizador = undefined
      if (puedeConectar()) conectar()
      else void validarSesionYReintentar()
    }, demora)
  }

  async function validarSesionYReintentar(turno = generacion) {
    if (validando || !reacciones.size) return
    validando = true
    try {
      await actualizar()
      if (sesion.value?.estado === 'anonima') {
        cerrarOrigen()
        cancelarTemporizador()
        if (
          ruta.path === '/admin' ||
          ruta.path.startsWith('/admin/') ||
          esRutaModuloOperador(ruta.path)
        ) {
          await navigateTo('/panel')
        }
      } else if (turno !== generacion || !reacciones.size) {
        return
      } else if (puedeConectar()) {
        programarReconexion()
      } else if (sesion.value?.estado === 'error') {
        programarReconexion()
      } else {
        cerrarOrigen()
        cancelarTemporizador()
        await navigateTo(
          sesion.value?.estado === 'autenticada' && sesion.value.identidad.rol === 'OPERADOR'
            ? '/operador/monitoreo'
            : '/admin',
        )
      }
    } finally {
      validando = false
    }
  }

  /** Permite a una pantalla recibir un tipo de aviso, le indica si debe actualizar
   * primero sus datos y devuelve una función para dejar de escucharlo.
   */
  function suscribir(
    reaccion: ReaccionEvento,
    cursorInicial?: string,
    nombreEvento: NombreEventoDirectorio = EVENTO_EMPLEADOS,
    avisarCobertura?: AvisoCoberturaCursor,
    avisosConexion?: AvisosConexion,
  ) {
    if (!(esDueno() || (esOperadorEnModulo() && EVENTOS_OPERADOR.has(nombreEvento)))) {
      avisarCobertura?.(true)
      return () => {}
    }

    const cursorConservado = cursor || cursorPendiente
    const cursorDeCobertura = cursor || cursorSolicitado
    const cubiertoPorStreamActivo = origen && !flujoConHueco && cursorDeCobertura === cursorInicial
    const requiereReconciliacion =
      !cursorInicial ||
      (origen
        ? !cubiertoPorStreamActivo
        : Boolean(cursorConservado && cursorConservado !== cursorInicial))
    reacciones.set(reaccion, { nombre: nombreEvento, avisos: avisosConexion })
    if (!cursor && !origen && cursorInicial) cursorPendiente = cursorInicial
    avisarCobertura?.(requiereReconciliacion)
    conectar()
    return () => {
      reacciones.delete(reaccion)
      if (!reacciones.size) {
        cancelarTemporizador()
        cerrarOrigen()
        reconectando = false
      }
    }
  }

  watch(
    puedeConectar,
    (permitido) => {
      if (permitido) {
        conectar()
        return
      }
      cerrarOrigen()
      cancelarTemporizador()
      cursor = ''
      cursorPendiente = ''
      cursorSolicitado = ''
      reconectando = false
      if (
        sesion.value?.estado === 'autenticada' &&
        sesion.value.identidad.rol === 'OPERADOR' &&
        (ruta.path === '/admin' || ruta.path.startsWith('/admin/'))
      ) {
        void navigateTo('/operador/monitoreo')
      }
    },
    { immediate: true },
  )

  return { provide: { eventosAdministracion: { suscribir } } }
})
