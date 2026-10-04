import type {
  ModoActivacion,
  RespuestaActivacion,
  RespuestaPrevalidacionActivacion,
  SolicitudActivacion,
} from '~/utils/activacion'

export function useActivacion() {
  const requestFetch = useRequestFetch()

  function prevalidarActivacion(token: string) {
    return requestFetch<RespuestaPrevalidacionActivacion>(
      '/api/activacion/prevalidar',
      {
        method: 'POST',
        body: { token },
        credentials: 'same-origin',
      },
    )
  }

  function activarCuenta(
    modo: ModoActivacion,
    solicitud: SolicitudActivacion,
  ) {
    return $fetch<RespuestaActivacion>(`/api/activacion/${modo}`, {
      method: 'POST',
      body: solicitud,
    })
  }

  return {
    activarCuenta,
    prevalidarActivacion,
  }
}
