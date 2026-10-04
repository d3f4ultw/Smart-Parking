import type {
  RespuestaCrearOperador,
  SolicitudCrearOperador,
} from '~/utils/operadores'
import type {
  Operador,
  RespuestaAccionOperador,
  RespuestaListaOperadores,
} from '~/utils/gestion-operadores'

export function useOperadores() {
  const fetchConCookies = useRequestFetch()

  function listarOperadores(pagina = 1) {
    return fetchConCookies<RespuestaListaOperadores>('/api/admin/operadores', {
      credentials: 'same-origin',
      query: { pagina },
    })
  }

  function obtenerOperador(operadorId: string | number) {
    return fetchConCookies<Operador>(
      `/api/admin/operadores/${encodeURIComponent(String(operadorId))}`,
      { credentials: 'same-origin' },
    )
  }

  function crearOperador(solicitud: SolicitudCrearOperador) {
    return $fetch<RespuestaCrearOperador>('/api/admin/operadores', {
      method: 'POST',
      body: solicitud,
      credentials: 'same-origin',
    })
  }

  function desactivarOperador(operadorId: number) {
    return $fetch<RespuestaAccionOperador>(
      `/api/admin/operadores/${operadorId}/desactivar`,
      { method: 'POST', credentials: 'same-origin' },
    )
  }

  function reactivarOperador(operadorId: number) {
    return $fetch<RespuestaAccionOperador>(
      `/api/admin/operadores/${operadorId}/reactivar`,
      { method: 'POST', credentials: 'same-origin' },
    )
  }

  function regenerarContrasenaOperador(operadorId: number) {
    return $fetch<RespuestaAccionOperador>(
      `/api/admin/operadores/${operadorId}/regenerar-contrasena`,
      { method: 'POST', credentials: 'same-origin' },
    )
  }

  function reenviarInvitacionOperador(operadorId: number) {
    return $fetch<RespuestaAccionOperador>(
      `/api/admin/operadores/${operadorId}/reenviar-invitacion`,
      { method: 'POST', credentials: 'same-origin' },
    )
  }

  return {
    crearOperador,
    desactivarOperador,
    listarOperadores,
    obtenerOperador,
    reactivarOperador,
    reenviarInvitacionOperador,
    regenerarContrasenaOperador,
  }
}
