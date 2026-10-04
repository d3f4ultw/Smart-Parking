export function extraerTokenInvitacionOperador(url: URL): string | null {
  if (url.pathname !== '/activar-cuenta') {
    return null
  }

  const token = url.searchParams.get('token')
  return token && /^[A-Za-z0-9_-]{32,128}$/.test(token) ? token : null
}

export function rutaActivacionSinToken(): string {
  return '/activar-cuenta'
}

export function evaluarRequisitosNuevaContrasenaOperador(contrasena: string) {
  const caracteres = Array.from(contrasena)
  return {
    longitudMinima: contrasena.length >= 10,
    longitudMaxima: contrasena.length <= 128,
    caracteresImprimibles: caracteres.every(
      caracter => caracter === ' ' || !/[\p{C}\p{Z}]/u.test(caracter),
    ),
    mayuscula: caracteres.some(
      caracter => caracter.toUpperCase() === caracter
        && caracter.toLowerCase() !== caracter,
    ),
  }
}

export function validarNuevaContrasenaOperador(
  contrasena: string,
  confirmacion: string,
): string | null {
  const requisitos = evaluarRequisitosNuevaContrasenaOperador(contrasena)
  if (!requisitos.longitudMinima) {
    return 'La contraseña debe tener al menos 10 caracteres.'
  }
  if (!requisitos.longitudMaxima) {
    return 'La contraseña no puede superar 128 caracteres.'
  }
  if (!requisitos.caracteresImprimibles) {
    return 'La contraseña contiene caracteres no válidos.'
  }
  if (!requisitos.mayuscula) {
    return 'La contraseña debe incluir al menos una letra mayúscula.'
  }
  if (contrasena !== confirmacion) {
    return 'Las contraseñas no coinciden.'
  }
  return null
}
