import type { RespuestaValidacionRecuperacion } from '~/types/operador'

export class ErrorRecuperacionOperador extends Error {
  constructor(
    public readonly estado: number,
    public readonly codigo: string | null,
    mensaje: string,
  ) {
    super(mensaje)
  }
}

function mensajeSeguro(estado: number) {
  if (estado === 400) return 'Revisa la contraseña e inténtalo de nuevo.'
  if (estado === 403) return 'No pudimos comprobar el enlace. Inténtalo de nuevo.'
  if (estado === 410) return 'Este enlace venció o ya se usó. Pide otro al propietario.'
  if (estado === 429) return 'Lo intentaste varias veces. Espera un momento y vuelve a intentarlo.'
  return 'No pudimos cambiar la contraseña. Revisa tu conexión e inténtalo de nuevo.'
}

async function solicitar<T>(ruta: string, datos: object, csrf: string) {
  try {
    return await $fetch<T>(ruta, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'content-type': 'application/json',
        'x-csrf-token': csrf,
      },
      body: datos,
    })
  } catch (fallo) {
    const error = fallo as {
      statusCode?: number
      status?: number
      response?: { status?: number }
      data?: { codigo?: string }
    }
    const estado = error.response?.status ?? error.statusCode ?? error.status ?? 0
    throw new ErrorRecuperacionOperador(estado, error.data?.codigo ?? null, mensajeSeguro(estado))
  }
}

export async function validarTokenRecuperacion(token: string, csrf: string) {
  const respuesta = await solicitar<RespuestaValidacionRecuperacion>(
    '/api/v1/operadores/recuperacion/validar',
    { token },
    csrf,
  )
  if (respuesta.valida !== true) {
    throw new ErrorRecuperacionOperador(410, 'TOKEN_RECUPERACION_INVALIDO', mensajeSeguro(410))
  }
}

export async function completarRecuperacionOperador(
  token: string,
  contrasena: string,
  confirmarContrasena: string,
  csrf: string,
) {
  await solicitar<void>(
    '/api/v1/operadores/recuperacion/completar',
    { token, contrasena, confirmarContrasena },
    csrf,
  )
}
