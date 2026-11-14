import { appendResponseHeader, setResponseHeader } from 'h3'
import type { IdentidadWeb } from '~/utils/api'

/** Indica si hay sesión administrativa, qué correo y rol tiene, o si no se pudo comprobar. */
export type EstadoSesionWeb =
  | { estado: 'anonima'; identidad: null }
  | { estado: 'autenticada'; identidad: IdentidadWeb }
  | { estado: 'error'; identidad: null }

interface RespuestaSesionApi {
  autenticada?: boolean
  correo?: string | null
  rol?: string | null
}

/** Acepta solo sesiones con correo y rol de dueño u operador; si falta alguno,
 * trata la respuesta como un error y no muestra una identidad incompleta.
 */
function proyectarSesion(respuesta: RespuestaSesionApi): EstadoSesionWeb {
  if (!respuesta.autenticada) return { estado: 'anonima', identidad: null }
  const rol = respuesta.rol === 'DUENO' || respuesta.rol === 'OPERADOR' ? respuesta.rol : null
  if (!rol || !respuesta.correo) return { estado: 'error', identidad: null }
  return {
    estado: 'autenticada',
    identidad: { autenticada: true, correo: respuesta.correo, rol },
  }
}

/** Permite que las páginas administrativas consulten la misma información de sesión
 * sin hacer varias consultas mientras una ya está en curso.
 */
export function useSesion() {
  const fetchSesion = useRequestFetch()

  /** Consulta quién inició sesión al preparar la página o al cambiar de pantalla. Si lo hace
   * el servidor, no guarda el resultado para reutilizarlo y devuelve al navegador cualquier
   * dato de sesión actualizado que haya recibido.
   */
  async function consultarSesion(): Promise<EstadoSesionWeb> {
    const evento = import.meta.server ? useRequestEvent() : undefined
    if (evento) {
      setResponseHeader(evento, 'cache-control', 'no-store, private')
      setResponseHeader(evento, 'vary', 'Cookie')
    }
    try {
      const respuesta = await fetchSesion<RespuestaSesionApi>('/api/v1/sesion', {
        onResponse({ response }) {
          if (!evento) return
          for (const valor of response.headers.getSetCookie())
            appendResponseHeader(evento, 'set-cookie', valor)
        },
      })
      return proyectarSesion(respuesta ?? {})
    } catch (error) {
      const estado = Number(
        (error as { statusCode?: number; status?: number }).statusCode ??
          (error as { status?: number }).status,
      )
      if (estado === 401) return { estado: 'anonima', identidad: null }
      return { estado: 'error', identidad: null }
    }
  }

  const resultado = useAsyncData<EstadoSesionWeb>('sesion-web-actual', consultarSesion, {
    default: () => ({ estado: 'error', identidad: null }) as EstadoSesionWeb,
    dedupe: 'defer',
    immediate: false,
  })

  return {
    sesion: computed<EstadoSesionWeb>(() => resultado.data.value as EstadoSesionWeb),
    cargando: resultado.pending,
    actualizar: resultado.refresh,
    limpiar: resultado.clear,
  }
}
