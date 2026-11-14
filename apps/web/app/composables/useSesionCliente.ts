import { CLAVE_PORTAL_CLIENTE, ErrorClienteApi, useClienteApi } from '~/utils/cliente-api'
import type { EstadoSesionClienteWeb, RespuestaSesionCliente } from '~/types/cliente'
import { useCsrfCliente } from './useCsrfCliente'

/** Considera válida la sesión solo si el servidor confirma el rol de cliente
 * y devuelve un correo; una respuesta incompleta se trata como error.
 */
function proyectarSesion(respuesta: RespuestaSesionCliente): EstadoSesionClienteWeb {
  if (!respuesta.autenticada) return { estado: 'anonima', identidad: null }
  if (respuesta.rol !== 'CLIENTE' || typeof respuesta.correo !== 'string' || !respuesta.correo) {
    return { estado: 'error', identidad: null }
  }
  return {
    estado: 'autenticada',
    identidad: {
      correo: respuesta.correo,
      rol: 'CLIENTE',
    },
  }
}

/** Mantiene la información de acceso al portal y borra el perfil privado
 * si el cliente salió o ya no se puede confirmar su sesión.
 */
export function useSesionCliente() {
  const nuxtApp = useNuxtApp()
  const api = useClienteApi()
  const csrf = useCsrfCliente()
  let estadoConsultado: EstadoSesionClienteWeb | undefined

  async function consultarSesion(): Promise<EstadoSesionClienteWeb> {
    try {
      const respuesta = await api.consultarSesion()
      const sesion = proyectarSesion(respuesta)
      estadoConsultado = sesion
      return sesion
    } catch (error) {
      if (error instanceof ErrorClienteApi && error.estado === 401) {
        estadoConsultado = { estado: 'anonima', identidad: null }
        return estadoConsultado
      }
      estadoConsultado = { estado: 'error', identidad: null }
      return estadoConsultado
    }
  }

  const resultado = useAsyncData<EstadoSesionClienteWeb>(
    'sesion-cliente-web-actual',
    consultarSesion,
    {
      default: () => ({ estado: 'error', identidad: null }) as EstadoSesionClienteWeb,
      dedupe: 'defer',
      immediate: false,
    },
  )

  /** Vuelve a comprobar si el cliente sigue dentro y, si no se confirma,
   * borra los datos privados que el portal tenía cargados.
   */
  async function actualizar(): Promise<EstadoSesionClienteWeb> {
    estadoConsultado = undefined
    await resultado.refresh()
    const sesionActual = estadoConsultado ?? (resultado.data.value as EstadoSesionClienteWeb)
    if (sesionActual.estado !== 'autenticada') limpiarDatosPrivados()
    return sesionActual
  }

  /** Borra el código de seguridad del portal y los datos privados del cliente
   * que otra pantalla podría reutilizar.
   */
  function limpiarDatosPrivados() {
    csrf.limpiar()
    nuxtApp.runWithContext(() => clearNuxtData(CLAVE_PORTAL_CLIENTE))
  }

  function limpiar() {
    limpiarDatosPrivados()
    resultado.clear()
  }

  return {
    sesion: computed<EstadoSesionClienteWeb>(() => resultado.data.value as EstadoSesionClienteWeb),
    cargando: resultado.pending,
    actualizar,
    limpiar,
  }
}
