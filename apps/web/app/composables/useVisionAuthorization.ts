type EstadoAutorizacionVision = {
  authorized: boolean
}

type EstadoLocalVision = 'loading' | 'required' | 'authorized' | 'error'

export function useVisionAuthorization() {
  const estado = useState<{
    state: EstadoLocalVision
  }>('vision-owner-authorization', () => ({ state: 'loading' }))
  const solicitud = useRequestFetch()

  function limpiar() {
    estado.value = { state: 'required' }
  }

  function aplicar(respuesta: EstadoAutorizacionVision) {
    estado.value = { state: respuesta.authorized ? 'authorized' : 'required' }
  }

  function codigoHttp(error: unknown) {
    if (error === null || typeof error !== 'object') return null
    const http = error as { status?: unknown; statusCode?: unknown }
    return typeof http.statusCode === 'number'
      ? http.statusCode
      : typeof http.status === 'number'
        ? http.status
        : null
  }

  async function manejarErrorProtegido(error: unknown) {
    const codigo = codigoHttp(error)
    if (codigo === 401) {
      limpiar()
      await navigateTo('/login', { replace: true })
    } else if (codigo === 403) {
      await actualizar()
    }
  }

  async function actualizar() {
    estado.value = { state: 'loading' }
    try {
      const respuesta = await solicitud<EstadoAutorizacionVision>(
        '/api/admin/vision/authorization',
        { credentials: 'same-origin', cache: 'no-store', timeout: 10_000 },
      )
      aplicar(respuesta)
    } catch (error: unknown) {
      if (codigoHttp(error) === 401) {
        limpiar()
        await navigateTo('/login', { replace: true })
      } else {
        estado.value = { state: 'error' }
      }
    }
  }

  async function verificar(contrasenaAdmin: string) {
    const respuesta = await solicitud<EstadoAutorizacionVision>(
      '/api/admin/vision/authorization',
      {
        method: 'POST',
        credentials: 'same-origin',
        cache: 'no-store',
        body: { contrasena_admin: contrasenaAdmin },
      },
    )
    aplicar(respuesta)
  }

  async function revocar() {
    await solicitud<EstadoAutorizacionVision>(
      '/api/admin/vision/authorization',
      { method: 'DELETE', credentials: 'same-origin', cache: 'no-store' },
    )
    limpiar()
  }

  return {
    estado,
    autorizado: computed(() => estado.value.state === 'authorized'),
    actualizar,
    verificar,
    revocar,
    limpiar,
    manejarErrorProtegido,
  }
}
