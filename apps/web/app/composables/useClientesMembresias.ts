import type {
  DetalleMembresiaCliente,
  EstadoCheckout,
  FiltroEstadoClientes,
  RespuestaMembresiaCliente,
  RespuestaCheckout,
  RespuestaListaClientes,
  RespuestaPlanesMembresia,
} from '~/utils/clientes-membresias'

export function useClientesMembresias() {
  const fetchConCookies = useRequestFetch()

  function listarClientes(
    pagina = 1,
    estado: FiltroEstadoClientes = 'todos',
    signal?: AbortSignal,
  ) {
    return fetchConCookies<RespuestaListaClientes>('/api/admin/clientes', {
      credentials: 'same-origin',
      cache: 'no-store',
      query: {
        pagina,
        ...(estado === 'todos' ? {} : { estado }),
      },
      signal,
    })
  }

  function consultarMembresiaCliente(signal?: AbortSignal) {
    return fetchConCookies<RespuestaMembresiaCliente>('/api/clientes/membresia', {
      credentials: 'same-origin',
      cache: 'no-store',
      signal,
    })
  }

  function consultarDetalle(codigoCliente: string, signal?: AbortSignal) {
    return fetchConCookies<DetalleMembresiaCliente>(
      `/api/admin/clientes/${encodeURIComponent(codigoCliente)}`,
      {
        credentials: 'same-origin',
        cache: 'no-store',
        signal,
      },
    )
  }

  function consultarPlanes(signal?: AbortSignal) {
    return fetchConCookies<RespuestaPlanesMembresia>('/api/membresias/planes', {
      credentials: 'same-origin',
      cache: 'no-store',
      signal,
    })
  }

  function crearCheckout(claveIdempotencia: string) {
    return $fetch<RespuestaCheckout>('/api/membresias/checkout', {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { 'Idempotency-Key': claveIdempotencia },
      body: { plan_id: 'mensual' },
    })
  }

  function cambiarContrasenaCliente(
    contrasenaActual: string,
    contrasenaNueva: string,
  ) {
    return $fetch<{ estado: 'contrasena_actualizada' }>('/api/clientes/contrasena', {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      body: {
        contrasena_actual: contrasenaActual,
        contrasena_nueva: contrasenaNueva,
      },
    })
  }

  function consultarEstadoCheckout(sessionId: string, signal?: AbortSignal) {
    return fetchConCookies<EstadoCheckout>(
      `/api/membresias/checkout/${encodeURIComponent(sessionId)}/estado`,
      {
        credentials: 'same-origin',
        cache: 'no-store',
        signal,
      },
    )
  }

  return {
    cambiarContrasenaCliente,
    consultarMembresiaCliente,
    consultarDetalle,
    consultarEstadoCheckout,
    consultarPlanes,
    crearCheckout,
    listarClientes,
  }
}
