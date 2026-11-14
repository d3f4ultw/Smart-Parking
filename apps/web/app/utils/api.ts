export interface IdentidadWeb {
  autenticada: boolean
  correo: string | null
  rol: 'DUENO' | 'OPERADOR' | null
}

export type CodigoApi =
  | 'CREDENCIALES_NO_VALIDAS'
  | 'SESION_NO_VIGENTE'
  | 'PERMISO_INSUFICIENTE'
  | 'CSRF_RECHAZADO'
  | 'CUERPO_DEMASIADO_GRANDE'
  | 'API_NO_DISPONIBLE'
  | 'SALIDA_MANUAL_NO_DISPONIBLE'
  | 'ERROR_API'

export class ErrorApi extends Error {
  constructor(
    public readonly estado: number,
    public readonly codigo: CodigoApi | null,
    mensaje: string,
  ) {
    super(mensaje)
  }
}

export async function solicitarApi<T>(
  ruta: string,
  opciones: Parameters<typeof $fetch<T>>[1] = {},
): Promise<T> {
  try {
    return (await $fetch<T>(ruta, {
      ...opciones,
      headers: {
        accept: 'application/json',
        ...opciones.headers,
      },
    })) as unknown as T
  } catch (error) {
    const fallo = error as {
      statusCode?: number
      status?: number
      data?: { codigo?: string; error?: string }
      message?: string
    }
    const estado = fallo.statusCode ?? fallo.status ?? 503
    const codigo = typeof fallo.data?.codigo === 'string' ? (fallo.data.codigo as CodigoApi) : null
    const mensaje =
      estado === 401
        ? 'Tu acceso venció. Inicia sesión de nuevo.'
        : estado >= 500
          ? 'No pudimos conectar con Smart Parking. Inténtalo de nuevo.'
          : 'No pudimos completar la acción. Inténtalo de nuevo.'
    throw new ErrorApi(estado, codigo, mensaje)
  }
}
