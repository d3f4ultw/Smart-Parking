import { ErrorClienteApi, useClienteApi } from '~/utils/cliente-api'

/** Guarda por separado el código de seguridad de las acciones del portal,
 * para no confundirlo con el que usa la administración.
 */
export function useCsrfCliente() {
  const api = useClienteApi()
  const token = useState<string | null>('csrf-cliente', () => null)

  /** Pide el código desde el navegador y rechaza la respuesta si no contiene
   * un valor que pueda proteger la acción.
   */
  async function obtener(): Promise<string> {
    if (!import.meta.client) {
      throw new Error('El token CSRF de cliente solo se solicita desde el navegador.')
    }
    if (!token.value) {
      const respuesta = await api.obtenerCsrf()
      if (typeof respuesta.token !== 'string' || !respuesta.token) {
        throw new ErrorClienteApi(502, 'TOKEN_CSRF_NO_VALIDO', 'No pudimos proteger esta acción.')
      }
      token.value = respuesta.token
    }
    return token.value
  }

  function actualizar(nuevoToken: string | null | undefined) {
    token.value = import.meta.client && nuevoToken ? nuevoToken : null
  }

  function manejarFallo(error: unknown) {
    if (error instanceof ErrorClienteApi && error.codigo === 'CSRF_RECHAZADO') {
      token.value = null
    }
  }

  function limpiar() {
    token.value = null
  }

  return { obtener, actualizar, manejarFallo, limpiar }
}
