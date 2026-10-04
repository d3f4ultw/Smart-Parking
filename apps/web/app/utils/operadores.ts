export interface DatosFormularioOperador {
  nombre: string
  apellido_paterno: string
  apellido_materno: string
  correo: string
}

export interface SolicitudCrearOperador {
  nombre: string
  apellido_paterno: string
  apellido_materno: string
  correo: string
}

export interface RespuestaCrearOperador {
  estado: 'operador_creado'
}

export type CampoFormularioOperador = keyof DatosFormularioOperador
export type ErroresFormularioOperador = Partial<
  Record<CampoFormularioOperador, string>
>

export function validarDatosOperador(
  datos: DatosFormularioOperador,
): ErroresFormularioOperador {
  const errores: ErroresFormularioOperador = {}
  const camposNombre: CampoFormularioOperador[] = [
    'nombre',
    'apellido_paterno',
    'apellido_materno',
  ]

  for (const campo of camposNombre) {
    const valor = datos[campo].trim()
    const etiqueta = campo === 'nombre'
      ? 'El nombre'
      : campo === 'apellido_paterno'
        ? 'El apellido paterno'
        : 'El apellido materno'

    if (valor.length === 0) {
      errores[campo] = `${etiqueta} es obligatorio.`
    } else if (valor.length > 100) {
      errores[campo] = `${etiqueta} no puede superar 100 caracteres.`
    }
  }

  const correo = datos.correo.trim()
  if (correo.length === 0) {
    errores.correo = 'Ingresa un correo electrónico.'
  } else if (correo.length > 320) {
    errores.correo = 'El correo no puede superar 320 caracteres.'
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(correo)) {
    errores.correo = 'Ingresa un correo electrónico válido.'
  }

  return errores
}

export function construirSolicitudCrearOperador(
  datos: DatosFormularioOperador,
): SolicitudCrearOperador {
  return {
    nombre: datos.nombre,
    apellido_paterno: datos.apellido_paterno,
    apellido_materno: datos.apellido_materno,
    correo: datos.correo,
  }
}

export function obtenerEstadoErrorOperador(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null) {
    return undefined
  }

  const posibleError = error as {
    status?: unknown
    statusCode?: unknown
    response?: { status?: unknown }
  }

  if (typeof posibleError.status === 'number') {
    return posibleError.status
  }
  if (typeof posibleError.statusCode === 'number') {
    return posibleError.statusCode
  }
  if (typeof posibleError.response?.status === 'number') {
    return posibleError.response.status
  }

  return undefined
}

export function mapearErrorOperador(status: number | undefined): string {
  if (status === 409) {
    return 'Ese correo ya está registrado.'
  }
  if (status === 422) {
    return 'Revisa los datos ingresados.'
  }
  return 'No fue posible crear el operador. Intenta nuevamente.'
}
