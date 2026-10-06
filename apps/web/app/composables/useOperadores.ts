import type {
  RespuestaCrearOperador,
  SolicitudCrearOperador,
} from '~/utils/operadores'
import { obtenerSegundosRetryAfter } from '~/utils/gestion-operadores'
import type {
  DetalleOperadorConCooldown,
  Operador,
  RespuestaAccionOperador,
  RespuestaListaOperadores,
} from '~/utils/gestion-operadores'

export function useOperadores() {
  const fetchConCookies = useRequestFetch()

  function listarOperadores(pagina = 1, signal?: AbortSignal, buscar?: string) {
    return fetchConCookies<RespuestaListaOperadores>('/api/admin/operadores', {
      credentials: 'same-origin',
      query: {
        pagina,
        ...(buscar ? { buscar } : {}),
      },
      signal,
    })
  }

  function obtenerOperador(operadorId: string | number, signal?: AbortSignal) {
    return fetchConCookies<Operador>(
      `/api/admin/operadores/${encodeURIComponent(String(operadorId))}`,
      { credentials: 'same-origin', signal },
    )
  }

  async function obtenerDetalleOperador(
    operadorId: string | number,
    signal?: AbortSignal,
  ): Promise<DetalleOperadorConCooldown> {
    let cooldownReenvioSegundos = 0
    const operador = await fetchConCookies<Operador>(
      `/api/admin/operadores/${encodeURIComponent(String(operadorId))}`,
      {
        credentials: 'same-origin',
        signal,
        onResponse({ response }) {
          if (response.ok) {
            cooldownReenvioSegundos = obtenerSegundosRetryAfter(
              response.headers.get('Retry-After'),
            ) ?? 0
          }
        },
      },
    )

    return {
      operador,
      cooldown_reenvio_segundos: cooldownReenvioSegundos,
    }
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

  function reenviarInvitacionOperador(
    operadorId: number,
    alRecibirCooldown?: (segundos: number) => void,
  ) {
    return $fetch<RespuestaAccionOperador>(
      `/api/admin/operadores/${operadorId}/reenviar-invitacion`,
      {
        method: 'POST',
        credentials: 'same-origin',
        onResponse({ response }) {
          if (!response.ok) {
            return
          }

          const segundos = obtenerSegundosRetryAfter(
            response.headers.get('Retry-After'),
          )
          if (segundos !== null) {
            alRecibirCooldown?.(segundos)
          }
        },
      },
    )
  }

  return {
    crearOperador,
    desactivarOperador,
    listarOperadores,
    obtenerDetalleOperador,
    obtenerOperador,
    reactivarOperador,
    reenviarInvitacionOperador,
    regenerarContrasenaOperador,
  }
}
