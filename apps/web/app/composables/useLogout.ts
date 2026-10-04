import type { RespuestaLogout } from '~/utils/logout'

export function useLogout() {
  function cerrarSesion() {
    return $fetch<RespuestaLogout>('/api/autenticacion/logout', {
      method: 'POST',
      credentials: 'same-origin',
    })
  }

  return {
    cerrarSesion,
  }
}
