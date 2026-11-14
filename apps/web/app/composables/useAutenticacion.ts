import { ErrorApi, solicitarApi } from '~/utils/api'
import { useCsrf } from './useCsrf'
import { useSesion } from './useSesion'

interface RespuestaAcceso {
  csrfToken?: string | null
}

/** Inicia y cierra la sesión administrativa, guarda el nuevo código de seguridad
 * cuando el servidor lo devuelve y comprueba el acceso si el cierre no se confirma.
 */
export function useAutenticacion() {
  const csrf = useCsrf()
  const sesionWeb = useSesion()

  /** Envía el correo y la contraseña; si el acceso se acepta, guarda el código
   * de seguridad recibido y vuelve a consultar quién inició sesión.
   */
  async function iniciar(correo: string, contrasena: string) {
    const token = await csrf.obtener()
    const respuesta = await solicitarApi<RespuestaAcceso>('/api/v1/sesion', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-csrf-token': token },
      body: { correo, contrasena },
    })
    csrf.actualizar(respuesta.csrfToken)
    await sesionWeb.actualizar()
  }

  /** Intenta cerrar la sesión. Si ya venció, vuelve a la pantalla de acceso;
   * si se rechaza el código de seguridad, comprueba si la sesión sigue activa
   * y no afirma que se cerró cuando no pudo confirmarlo.
   */
  async function cerrar() {
    try {
      const token = await csrf.obtener()
      const respuesta = await solicitarApi<RespuestaAcceso>('/api/v1/sesion', {
        method: 'DELETE',
        headers: { 'x-csrf-token': token },
      })
      csrf.actualizar(respuesta.csrfToken)
      sesionWeb.limpiar()
      await navigateTo('/panel')
    } catch (error) {
      if (error instanceof ErrorApi && error.estado === 401) {
        csrf.limpiar()
        sesionWeb.limpiar()
        await navigateTo('/panel')
        return
      }
      if (error instanceof ErrorApi && error.estado === 403 && error.codigo === 'CSRF_RECHAZADO') {
        csrf.limpiar()
        try {
          await sesionWeb.actualizar()
        } catch {
          throw new ErrorApi(503, 'API_NO_DISPONIBLE', 'No pudimos comprobar tu sesión.')
        }

        if (sesionWeb.sesion.value.estado === 'anonima') {
          sesionWeb.limpiar()
          await navigateTo('/panel')
          return
        }
        if (sesionWeb.sesion.value.estado === 'error') {
          throw new ErrorApi(503, 'API_NO_DISPONIBLE', 'No pudimos comprobar tu sesión.')
        }
        throw new ErrorApi(403, 'ERROR_API', 'La sesión sigue activa; no se confirmó el cierre.')
      }
      throw error
    }
  }

  function manejarFalloCsrf(error: unknown) {
    if (error instanceof ErrorApi && error.codigo === 'CSRF_RECHAZADO') csrf.limpiar()
  }

  return { iniciar, cerrar, manejarFalloCsrf }
}
