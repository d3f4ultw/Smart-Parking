import type {
  Empleado,
  RespuestaListaEmpleados,
  SolicitudCambiarEstadoEmpleado,
  SolicitudRegistrarEmpleado,
} from '~/utils/empleados'

export function useEmpleados() {
  const fetchConCookies = useRequestFetch()

  function listarEmpleados(pagina = 1, signal?: AbortSignal) {
    return fetchConCookies<RespuestaListaEmpleados>('/api/admin/empleados', {
      credentials: 'same-origin',
      cache: 'no-store',
      query: { pagina },
      signal,
    })
  }

  function registrarEmpleado(
    solicitud: SolicitudRegistrarEmpleado,
    claveIdempotencia: string,
  ) {
    let status = 0
    return $fetch<Empleado>('/api/admin/empleados', {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { 'Idempotency-Key': claveIdempotencia },
      body: solicitud,
      onResponse({ response }) {
        status = response.status
      },
    }).then((empleado) => ({ empleado, status }))
  }

  function cambiarEstadoEmpleado(
    empleadoId: string,
    solicitud: SolicitudCambiarEstadoEmpleado,
  ) {
    return $fetch<Empleado>(
      `/api/admin/empleados/${encodeURIComponent(empleadoId)}/estado`,
      {
        method: 'PATCH',
        credentials: 'same-origin',
        cache: 'no-store',
        body: solicitud,
      },
    )
  }

  return {
    cambiarEstadoEmpleado,
    listarEmpleados,
    registrarEmpleado,
  }
}
