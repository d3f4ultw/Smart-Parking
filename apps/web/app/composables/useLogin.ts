import type { RespuestaLogin, SolicitudLogin } from '~/utils/login'

export function useLogin() {
  function iniciarSesion(solicitud: SolicitudLogin) {
    return $fetch<RespuestaLogin>('/api/login', {
      method: 'POST',
      body: solicitud,
      credentials: 'same-origin',
    })
  }

  return {
    iniciarSesion,
  }
}
