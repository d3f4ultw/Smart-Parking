import { solicitarApi } from '~/utils/api'

interface RespuestaCsrf {
  token: string
}

/** Guarda en el navegador el código de seguridad que las acciones administrativas
 * deben enviar; si no lo tiene, lo pide antes de continuar.
 */
export function useCsrf() {
  const memoriaCliente = useNuxtApp().$csrf

  /** Pide el código al servidor cuando una acción necesita protección y aún no lo tiene. */
  async function obtener(): Promise<string> {
    if (!import.meta.client) throw new Error('El token CSRF solo se solicita desde el navegador.')
    let token = memoriaCliente.leer()
    if (!token) {
      const respuesta = await solicitarApi<RespuestaCsrf>('/api/v1/csrf')
      memoriaCliente.guardar(respuesta.token)
      token = respuesta.token
    }
    return token
  }

  function actualizar(nuevoToken: string | null | undefined) {
    memoriaCliente.guardar(import.meta.client && nuevoToken ? nuevoToken : null)
  }

  return {
    obtener,
    actualizar,
    limpiar: () => memoriaCliente.guardar(null),
  }
}
