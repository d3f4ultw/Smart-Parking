import type { RespuestaLogout } from '~/utils/logout'

export function useLogout() {
  async function cerrarSesion() {
    const respuesta = await $fetch<RespuestaLogout>('/api/autenticacion/logout', {
      method: 'POST',
      credentials: 'same-origin',
    })
    useVisionAuthorization().limpiar()
    return respuesta
  }

  return {
    cerrarSesion,
  }
}
