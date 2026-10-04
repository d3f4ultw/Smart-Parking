export const LONGITUD_CODIGO = 6
export const LONGITUD_MINIMA_CONTRASENA = 10
export const LONGITUD_MAXIMA_CONTRASENA = 128
export const CODIGO_ACTIVACION_NO_DISPONIBLE = 'ACTIVACION_NO_DISPONIBLE'
export const CODIGO_DATOS_ACTIVACION_INVALIDOS = 'DATOS_ACTIVACION_INVALIDOS'

export const CODIGOS_ERROR_ACTIVACION = [
  CODIGO_ACTIVACION_NO_DISPONIBLE,
  CODIGO_DATOS_ACTIVACION_INVALIDOS,
] as const

export const MODOS_ACTIVACION = ['manual', 'temporal'] as const
export type ModoActivacion = (typeof MODOS_ACTIVACION)[number]
export type CodigoErrorActivacion = (typeof CODIGOS_ERROR_ACTIVACION)[number]

export interface DatosFormularioActivacion {
  codigo: string
  contrasenaTemporal: string
  nuevaContrasena: string
  confirmarContrasena: string
}

export interface EstadoRequisitosContrasena {
  longitudValida: boolean
  mayusculaValida: boolean
  coincidenciaValida: boolean
  diferenteDeTemporal: boolean | null
}

export interface SolicitudActivacionManual {
  token: string
  codigo: string
}

export interface SolicitudActivacionTemporal {
  token: string
  codigo: string
  contrasena_temporal: string
  nueva_contrasena: string
  confirmar_contrasena: string
}

export type SolicitudActivacion =
  | SolicitudActivacionManual
  | SolicitudActivacionTemporal

export type EnviarActivacion = (
  modo: ModoActivacion,
  solicitud: SolicitudActivacion,
) => Promise<unknown>

export interface RespuestaActivacion {
  estado: 'activada'
}

export interface RespuestaPrevalidacionActivacion {
  modo: ModoActivacion
}

export function obtenerTokenActivacion(valor: unknown): string | null {
  return typeof valor === 'string' && valor.length > 0 ? valor : null
}

export function obtenerModoPrevalidado(valor: unknown): ModoActivacion | null {
  if (typeof valor !== 'object' || valor === null) {
    return null
  }

  const modo = (valor as { modo?: unknown }).modo
  return typeof modo === 'string' && esModoActivacion(modo) ? modo : null
}

export function esModoActivacion(valor: string): valor is ModoActivacion {
  return MODOS_ACTIVACION.includes(valor as ModoActivacion)
}

function contieneMayuscula(valor: string): boolean {
  return Array.from(valor).some((caracter) => {
    return (
      caracter.toUpperCase() === caracter &&
      caracter.toLowerCase() !== caracter
    )
  })
}

function contieneSoloCaracteresImprimibles(valor: string): boolean {
  return /^[\p{L}\p{M}\p{N}\p{P}\p{S}\p{Zs}]*$/u.test(valor)
}

export function evaluarDiferenciaContrasenaTemporal(
  nuevaContrasena: string,
  contrasenaTemporal: string,
): boolean | null {
  if (nuevaContrasena.length === 0 || contrasenaTemporal.length === 0) {
    return null
  }

  return nuevaContrasena !== contrasenaTemporal
}

export function evaluarRequisitosContrasena(
  nuevaContrasena: string,
  confirmarContrasena: string,
  contrasenaTemporal = '',
): EstadoRequisitosContrasena {
  const longitud = Array.from(nuevaContrasena).length
  return {
    longitudValida:
      longitud >= LONGITUD_MINIMA_CONTRASENA &&
      longitud <= LONGITUD_MAXIMA_CONTRASENA,
    mayusculaValida: contieneMayuscula(nuevaContrasena),
    coincidenciaValida:
      nuevaContrasena.length > 0 && nuevaContrasena === confirmarContrasena,
    diferenteDeTemporal: evaluarDiferenciaContrasenaTemporal(
      nuevaContrasena,
      contrasenaTemporal,
    ),
  }
}

export function validarDatosActivacion(
  modo: ModoActivacion,
  datos: DatosFormularioActivacion,
): string | null {
  if (!/^\d{6}$/.test(datos.codigo)) {
    return 'Ingresa un código de activación de 6 dígitos.'
  }

  if (modo === 'manual') {
    return null
  }

  if (datos.contrasenaTemporal.length === 0) {
    return 'Ingresa la contraseña temporal recibida por correo.'
  }

  const requisitos = evaluarRequisitosContrasena(
    datos.nuevaContrasena,
    datos.confirmarContrasena,
    datos.contrasenaTemporal,
  )
  const longitudNueva = Array.from(datos.nuevaContrasena).length
  if (!requisitos.longitudValida && longitudNueva < LONGITUD_MINIMA_CONTRASENA) {
    return `La nueva contraseña debe tener al menos ${LONGITUD_MINIMA_CONTRASENA} caracteres.`
  }
  if (!requisitos.longitudValida && longitudNueva > LONGITUD_MAXIMA_CONTRASENA) {
    return `La nueva contraseña no puede superar ${LONGITUD_MAXIMA_CONTRASENA} caracteres.`
  }
  if (!contieneSoloCaracteresImprimibles(datos.nuevaContrasena)) {
    return 'La nueva contraseña contiene caracteres no válidos.'
  }
  if (!requisitos.mayusculaValida) {
    return 'La nueva contraseña debe incluir al menos una letra mayúscula.'
  }
  if (!requisitos.coincidenciaValida) {
    return 'Las contraseñas nuevas no coinciden.'
  }
  if (!requisitos.diferenteDeTemporal) {
    return 'Debe ser diferente de la contraseña temporal.'
  }

  return null
}

export function puedeEnviarActivacion(
  modo: ModoActivacion,
  datos: DatosFormularioActivacion,
  parametrosValidos: boolean,
): boolean {
  return parametrosValidos && validarDatosActivacion(modo, datos) === null
}

export async function activarSiEsValida(
  modo: ModoActivacion,
  token: string,
  datos: DatosFormularioActivacion,
  enviar: EnviarActivacion,
): Promise<string | null> {
  const errorLocal = validarDatosActivacion(modo, datos)
  if (errorLocal !== null) {
    return errorLocal
  }

  await enviar(modo, construirSolicitudActivacion(modo, token, datos))
  return null
}

export function construirSolicitudActivacion(
  modo: ModoActivacion,
  token: string,
  datos: DatosFormularioActivacion,
): SolicitudActivacion {
  if (modo === 'manual') {
    return {
      token,
      codigo: datos.codigo,
    }
  }

  return {
    token,
    codigo: datos.codigo,
    contrasena_temporal: datos.contrasenaTemporal,
    nueva_contrasena: datos.nuevaContrasena,
    confirmar_contrasena: datos.confirmarContrasena,
  }
}

function esCodigoErrorActivacion(
  valor: unknown,
): valor is CodigoErrorActivacion {
  return (
    typeof valor === 'string' &&
    CODIGOS_ERROR_ACTIVACION.includes(valor as CodigoErrorActivacion)
  )
}

function obtenerCodigoDesdeDato(valor: unknown): CodigoErrorActivacion | undefined {
  if (typeof valor !== 'object' || valor === null) {
    return undefined
  }

  const posibleDato = valor as {
    code?: unknown
    detail?: unknown
  }
  if (esCodigoErrorActivacion(posibleDato.code)) {
    return posibleDato.code
  }
  if (typeof posibleDato.detail === 'object' && posibleDato.detail !== null) {
    const detalle = posibleDato.detail as { code?: unknown }
    if (esCodigoErrorActivacion(detalle.code)) {
      return detalle.code
    }
  }
  return undefined
}

export function obtenerCodigoError(
  error: unknown,
): CodigoErrorActivacion | undefined {
  if (typeof error !== 'object' || error === null) {
    return undefined
  }

  const posibleError = error as {
    code?: unknown
    data?: unknown
    response?: { _data?: unknown } | unknown
  }
  const codigoDirecto = obtenerCodigoDesdeDato(posibleError)
  if (codigoDirecto !== undefined) {
    return codigoDirecto
  }

  const codigoDeDatos = obtenerCodigoDesdeDato(posibleError.data)
  if (codigoDeDatos !== undefined) {
    return codigoDeDatos
  }

  if (typeof posibleError.response === 'object' && posibleError.response !== null) {
    return obtenerCodigoDesdeDato(
      (posibleError.response as { _data?: unknown })._data,
    )
  }

  return undefined
}

export function esActivacionNoDisponible(error: unknown): boolean {
  return obtenerCodigoError(error) === CODIGO_ACTIVACION_NO_DISPONIBLE
}

export function limpiarDatosFormularioActivacion(
  datos: DatosFormularioActivacion,
): void {
  datos.codigo = ''
  datos.contrasenaTemporal = ''
  datos.nuevaContrasena = ''
  datos.confirmarContrasena = ''
}

export function obtenerEstadoError(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null) {
    return undefined
  }

  const posibleError = error as { status?: unknown; statusCode?: unknown }
  if (typeof posibleError.status === 'number') {
    return posibleError.status
  }
  if (typeof posibleError.statusCode === 'number') {
    return posibleError.statusCode
  }
  return undefined
}

export function mapearErrorActivacion(status: number | undefined): string {
  if (status === 404) {
    return 'El enlace o código de activación ya no es válido.'
  }
  if (status === 422) {
    return 'Revisa los datos de activación e inténtalo de nuevo.'
  }
  if (status === 429) {
    return 'Se alcanzó el límite de intentos. Inténtalo más tarde.'
  }
  return 'No pudimos activar la cuenta en este momento. Inténtalo más tarde.'
}
