import { onScopeDispose, ref, watch } from 'vue'
import type {
  AccionAdministracionOperador,
  DetalleOperador,
  EstadoCuentaOperador,
  RespuestaReemisionInvitacion,
  RespuestaSolicitudRecuperacion,
} from '~/types/operador'
import { ErrorOperadoresApi, useClienteOperadores } from '~/utils/operadores-api'

function textoInvitacion(estado: RespuestaReemisionInvitacion['estadoInvitacion']) {
  return {
    ENVIANDO: 'Enviando',
    ENVIADO: 'Enviado',
    FALLIDO: 'No se pudo enviar',
    DESCONOCIDO: 'No sabemos si se envió',
    DESHABILITADO: 'No se enviará',
    EXPIRADA: 'Venció',
    CONSUMIDA: 'Usada',
  }[estado]
}

function mensajeFallo(fallo: unknown) {
  if (!(fallo instanceof ErrorOperadoresApi)) {
    return 'No pudimos completar el cambio. Inténtalo de nuevo.'
  }
  return fallo.message
}

export function useAdministracionOperadores(actualizarDirectorio: () => void) {
  const cliente = useClienteOperadores()
  const csrf = useCsrf()
  const toast = useToast()
  const sesion = useSesion()
  const abierto = ref(false)
  const operadorId = ref<string | null>(null)
  const detalle = ref<DetalleOperador | null>(null)
  const etag = ref<string | null>(null)
  const accion = ref<AccionAdministracionOperador | null>(null)
  const cargando = ref(false)
  const ocupado = ref(false)
  const error = ref('')
  const puedeReintentar = ref(false)
  const clavesIdempotencia = new Map<string, string>()
  let controladorDetalle: AbortController | undefined
  let temporizadorDetalle: ReturnType<typeof setTimeout> | undefined
  let generacionDetalle = 0

  function cancelarDetalle() {
    generacionDetalle += 1
    controladorDetalle?.abort()
    controladorDetalle = undefined
    cargando.value = false
  }

/** Ignora respuestas de consultas anteriores y guarda el número de revisión leído;
 * así un cambio se rechaza si alguien modificó la cuenta desde que se abrió el detalle.
 */
  async function cargarDetalle(limpiarError = true) {
    const id = operadorId.value
    if (!id || !abierto.value) return
    cancelarDetalle()
    const generacion = generacionDetalle
    const controlador = new AbortController()
    controladorDetalle = controlador
    cargando.value = true
    puedeReintentar.value = false
    if (limpiarError) error.value = ''
    try {
      const respuesta = await cliente.detalle(id, controlador.signal)
      if (controlador.signal.aborted || generacion !== generacionDetalle || id !== operadorId.value)
        return
      detalle.value = respuesta.datos
      etag.value = respuesta.etag
    } catch (fallo) {
      if (controlador.signal.aborted || generacion !== generacionDetalle) return
      if (fallo instanceof ErrorOperadoresApi && fallo.estado === 401) {
        await sesion.limpiar()
        await navigateTo('/panel')
        return
      }
      detalle.value = null
      etag.value = null
      error.value = mensajeFallo(fallo)
      puedeReintentar.value = true
    } finally {
      if (generacion === generacionDetalle) {
        cargando.value = false
        controladorDetalle = undefined
      }
    }
  }

  function abrir(id: string) {
    cancelarDetalle()
    operadorId.value = id
    detalle.value = null
    etag.value = null
    accion.value = null
    error.value = ''
    abierto.value = true
    void cargarDetalle()
  }

  function cerrar() {
    abierto.value = false
  }

  function clavePara(id: string, operacion: AccionAdministracionOperador) {
    const clave = `${id}:${operacion}`
    let valor = clavesIdempotencia.get(clave)
    if (!valor) {
      const aleatorios = new Uint8Array(16)
      globalThis.crypto.getRandomValues(aleatorios)
      valor = Array.from(aleatorios, (byte) => byte.toString(16).padStart(2, '0')).join('')
      clavesIdempotencia.set(clave, valor)
    }
    return { clave, valor }
  }

  function confirmarReemision(respuesta: RespuestaReemisionInvitacion) {
    toast.add({
      title: 'Invitación renovada',
      description: `Correo: ${textoInvitacion(respuesta.estadoInvitacion)}.`,
      color: respuesta.estadoInvitacion === 'ENVIADO' ? 'success' : 'warning',
    })
  }

  function confirmarRecuperacion(respuesta: RespuestaSolicitudRecuperacion) {
    const vencimiento = new Intl.DateTimeFormat('es-MX', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(respuesta.venceEn))
    toast.add({
      title: 'Enlace para cambiar la contraseña',
      description: `Correo: ${textoInvitacion(respuesta.estadoEnvio)}. Vence el ${vencimiento}.`,
      color: respuesta.estadoEnvio === 'ENVIADO' ? 'success' : 'warning',
    })
  }

  function confirmarEstado(estado: EstadoCuentaOperador) {
    toast.add({
      title: 'Cuenta actualizada',
      description:
        estado === 'INACTIVA'
          ? 'La persona ya no puede entrar en esta cuenta.'
          : 'La persona deberá crear una contraseña nueva antes de volver a entrar.',
      color: 'success',
    })
  }

  async function confirmarAccion(accionConfirmada: AccionAdministracionOperador) {
    const id = operadorId.value
    const revision = etag.value
    if (!id || !revision || ocupado.value || accion.value !== accionConfirmada) return
    ocupado.value = true
    error.value = ''
    const requiereClave =
      accionConfirmada === 'REEMITIR_INVITACION' ||
      accionConfirmada === 'REACTIVAR' ||
      accionConfirmada === 'SOLICITAR_RECUPERACION'
    let idempotencia: ReturnType<typeof clavePara> | null = null
    try {
      idempotencia = requiereClave ? clavePara(id, accionConfirmada) : null
      const token = await csrf.obtener()
      if (accionConfirmada === 'REEMITIR_INVITACION') {
        const respuesta = await cliente.reemitirInvitacion(id, revision, idempotencia!.valor, token)
        confirmarReemision(respuesta)
      } else if (accionConfirmada === 'SOLICITAR_RECUPERACION') {
        const respuesta = await cliente.solicitarRecuperacion(
          id,
          revision,
          idempotencia!.valor,
          token,
        )
        confirmarRecuperacion(respuesta)
      } else {
        const estado = accionConfirmada === 'DESACTIVAR' ? 'INACTIVA' : 'PENDIENTE'
        await cliente.cambiarEstado(id, estado, revision, token, idempotencia?.valor)
        confirmarEstado(estado)
      }
      if (idempotencia) clavesIdempotencia.delete(idempotencia.clave)
      accion.value = null
      actualizarDirectorio()
      await cargarDetalle()
    } catch (fallo) {
      error.value = mensajeFallo(fallo)
      if (
        fallo instanceof ErrorOperadoresApi &&
        fallo.estado === 403 &&
        fallo.codigo === 'CSRF_RECHAZADO'
      ) {
        csrf.limpiar()
      } else if (fallo instanceof ErrorOperadoresApi && fallo.estado === 401) {
        await sesion.limpiar()
        await navigateTo('/panel')
      } else if (
        fallo instanceof ErrorOperadoresApi &&
        (fallo.estado === 404 ||
          fallo.estado === 409 ||
          fallo.estado === 412 ||
          fallo.estado === 428)
      ) {
        if (idempotencia) clavesIdempotencia.delete(idempotencia.clave)
        accion.value = null
        actualizarDirectorio()
        const mensaje = error.value
        await cargarDetalle(false)
        error.value = mensaje
      }
    } finally {
      ocupado.value = false
    }
  }

  function programarRefrescoDetalle() {
    if (!abierto.value || !operadorId.value) return
    if (temporizadorDetalle) clearTimeout(temporizadorDetalle)
    temporizadorDetalle = setTimeout(() => {
      temporizadorDetalle = undefined
      void cargarDetalle()
    }, 100)
  }

  watch(abierto, (estaAbierto) => {
    if (estaAbierto) return
    cancelarDetalle()
    if (temporizadorDetalle) clearTimeout(temporizadorDetalle)
    temporizadorDetalle = undefined
    operadorId.value = null
    detalle.value = null
    etag.value = null
    accion.value = null
    error.value = ''
    puedeReintentar.value = false
  })

  onScopeDispose(() => {
    cancelarDetalle()
    if (temporizadorDetalle) clearTimeout(temporizadorDetalle)
  })

  return {
    abierto,
    detalle,
    accion,
    cargando,
    ocupado,
    error,
    puedeReintentar,
    abrir,
    cerrar,
    cargarDetalle,
    confirmarAccion,
    programarRefrescoDetalle,
  }
}
