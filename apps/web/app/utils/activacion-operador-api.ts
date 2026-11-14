interface RespuestaValidacionInvitacion {
  valida: true
}

export class ErrorActivacionOperador extends Error {
  constructor(
    public readonly estado: number,
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
  return 'No pudimos activar la cuenta. Revisa tu conexión e inténtalo de nuevo.'
}

async function solicitar<T>(ruta: string, token: string, csrf: string, datos?: object) {
  try {
    return await $fetch<T>(ruta, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'content-type': 'application/json',
        'x-csrf-token': csrf,
      },
      body: { token, ...datos },
    })
  } catch (fallo) {
    const error = fallo as { statusCode?: number; status?: number; response?: { status?: number } }
    const estado = error.response?.status ?? error.statusCode ?? error.status ?? 0
    throw new ErrorActivacionOperador(estado, mensajeSeguro(estado))
  }
}

export async function validarInvitacionOperador(token: string, csrf: string) {
  const respuesta = await solicitar<RespuestaValidacionInvitacion>(
    '/api/v1/operadores/activacion/validar',
    token,
    csrf,
  )
  if (respuesta.valida !== true) throw new ErrorActivacionOperador(410, mensajeSeguro(410))
}

export async function completarActivacionOperador(token: string, contrasena: string, csrf: string) {
  // El servidor pide contraseña y confirmación; se envía el mismo valor en ambos campos
  // para que la persona solo tenga que escribirlo una vez.
  await solicitar<void>('/api/v1/operadores/activacion/completar', token, csrf, {
    contrasena,
    confirmarContrasena: contrasena,
  })
}
