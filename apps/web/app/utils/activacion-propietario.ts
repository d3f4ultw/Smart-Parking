export type TipoCuentaPropietario = 'nueva' | 'retorno'
export type PasoPropietario = 1 | 2 | 3

export type CredencialesPropietario = {
  nombre: string
  apellidoPaterno: string
  apellidoMaterno: string
  contrasenaAdmin: string
  confirmarContrasenaAdmin: string
  contrasenaLogin: string
  confirmarContrasenaLogin: string
}

export type DatosPersonalesPropietario = Pick<
  CredencialesPropietario,
  'nombre' | 'apellidoPaterno' | 'apellidoMaterno'
>

export type ErroresPasoPropietario = Partial<
  Record<keyof CredencialesPropietario, string>
>

export type ProgresoActivacionPropietario = DatosPersonalesPropietario & {
  tipoCuenta: TipoCuentaPropietario
  expiraEn: string
  paso: PasoPropietario
}

export function extraerTokenInvitacionPropietario(url: URL): string | null {
  const valores = url.searchParams.getAll('token')
  if (valores.length !== 1) {
    return null
  }

  const token = valores[0]
  if (token === undefined || !/^[A-Za-z0-9_-]{32,128}$/.test(token)) {
    return null
  }

  return token
}

export function rutaActivacionPropietarioSinToken(): string {
  return '/activar-propietario'
}

export function evaluarRequisitosContrasenaPropietario(valor: string) {
  const longitud = Array.from(valor).length
  return {
    longitudValida: longitud >= 10 && longitud <= 128,
    caracteresImprimibles: valor.trim().length > 0
      && /^[\p{L}\p{M}\p{N}\p{P}\p{S} ]*$/u.test(valor),
    incluyeMayuscula: /\p{Lu}/u.test(valor),
  }
}

function errorContrasena(valor: string, etiqueta: string): string | null {
  const requisitos = evaluarRequisitosContrasenaPropietario(valor)
  if (!requisitos.longitudValida || !requisitos.caracteresImprimibles) {
    return `${etiqueta} debe tener entre 10 y 128 caracteres imprimibles.`
  }
  if (!requisitos.incluyeMayuscula) {
    return `${etiqueta} debe incluir una letra mayúscula.`
  }
  return null
}

function errorCampoNombre(valor: string, etiqueta: string, obligatorio: boolean): string | null {
  const normalizado = valor.trim()
  if (obligatorio && normalizado.length === 0) {
    return `Escribe ${etiqueta.toLowerCase()}.`
  }
  if (Array.from(normalizado).length > 100) {
    return `${etiqueta} debe contener hasta 100 caracteres.`
  }
  if (/\p{C}/u.test(valor)) {
    return `${etiqueta} contiene caracteres no válidos.`
  }
  return null
}

function agregarError(
  errores: ErroresPasoPropietario,
  campo: keyof CredencialesPropietario,
  error: string | null,
) {
  if (error !== null) {
    errores[campo] = error
  }
}

function validarContrasenaAdmin(datos: CredencialesPropietario): ErroresPasoPropietario {
  const errores: ErroresPasoPropietario = {}
  agregarError(
    errores,
    'contrasenaAdmin',
    errorContrasena(datos.contrasenaAdmin, 'La contraseña administrativa'),
  )
  if (datos.confirmarContrasenaAdmin.length === 0) {
    errores.confirmarContrasenaAdmin = 'Confirma la contraseña administrativa.'
  } else if (datos.contrasenaAdmin !== datos.confirmarContrasenaAdmin) {
    errores.confirmarContrasenaAdmin = 'Las contraseñas administrativas no coinciden.'
  }
  return errores
}

export function validarPasoPropietario(
  tipoCuenta: TipoCuentaPropietario,
  paso: PasoPropietario,
  datos: CredencialesPropietario,
): ErroresPasoPropietario {
  const errores: ErroresPasoPropietario = {}

  if (paso === 1) {
    agregarError(errores, 'nombre', errorCampoNombre(datos.nombre, 'Nombre(s)', true))
    agregarError(
      errores,
      'apellidoPaterno',
      errorCampoNombre(datos.apellidoPaterno, 'Apellido paterno', true),
    )
    agregarError(
      errores,
      'apellidoMaterno',
      errorCampoNombre(datos.apellidoMaterno, 'Apellido materno', false),
    )
    return errores
  }

  if (tipoCuenta === 'nueva' && paso === 2) {
    agregarError(
      errores,
      'contrasenaLogin',
      errorContrasena(datos.contrasenaLogin, 'La contraseña'),
    )
    if (datos.confirmarContrasenaLogin.length === 0) {
      errores.confirmarContrasenaLogin = 'Confirma la contraseña.'
    } else if (datos.contrasenaLogin !== datos.confirmarContrasenaLogin) {
      errores.confirmarContrasenaLogin = 'Las contraseñas de acceso no coinciden.'
    }
    return errores
  }

  const erroresAdmin = validarContrasenaAdmin(datos)
  Object.assign(errores, erroresAdmin)
  if (tipoCuenta === 'nueva' && datos.contrasenaAdmin.length > 0
    && datos.contrasenaAdmin === datos.contrasenaLogin) {
    errores.contrasenaAdmin = 'Debe ser distinta de la contraseña de acceso.'
  }
  return errores
}

export function normalizarCampoNombre(valor: string): string {
  return valor.trim().replace(/\s+/gu, ' ')
}

export function serializarProgresoActivacionPropietario(
  tipoCuenta: TipoCuentaPropietario,
  expiraEn: string,
  paso: PasoPropietario,
  datos: DatosPersonalesPropietario,
): string {
  return JSON.stringify({
    version: 1,
    tipoCuenta,
    expiraEn,
    paso,
    nombre: datos.nombre,
    apellidoPaterno: datos.apellidoPaterno,
    apellidoMaterno: datos.apellidoMaterno,
  })
}

export function recuperarProgresoActivacionPropietario(
  contenido: string | null,
  tipoCuenta: TipoCuentaPropietario,
  expiraEn: string,
  maximoPasos: 2 | 3,
): ProgresoActivacionPropietario | null {
  if (contenido === null) {
    return null
  }
  try {
    const valor: unknown = JSON.parse(contenido)
    if (typeof valor !== 'object' || valor === null) {
      return null
    }
    const borrador = valor as Record<string, unknown>
    const paso = borrador.paso
    if (
      borrador.version !== 1
      || borrador.tipoCuenta !== tipoCuenta
      || borrador.expiraEn !== expiraEn
      || typeof paso !== 'number'
      || !Number.isInteger(paso)
      || paso < 1
      || paso > maximoPasos
      || typeof borrador.nombre !== 'string'
      || typeof borrador.apellidoPaterno !== 'string'
      || typeof borrador.apellidoMaterno !== 'string'
      || Array.from(borrador.nombre).length > 100
      || Array.from(borrador.apellidoPaterno).length > 100
      || Array.from(borrador.apellidoMaterno).length > 100
    ) {
      return null
    }

    return {
      tipoCuenta,
      expiraEn,
      paso: paso as PasoPropietario,
      nombre: borrador.nombre,
      apellidoPaterno: borrador.apellidoPaterno,
      apellidoMaterno: borrador.apellidoMaterno,
    }
  } catch {
    return null
  }
}
