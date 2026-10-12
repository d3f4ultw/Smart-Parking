import type { TipoCuentaPropietario } from '~/utils/activacion-propietario'

type EstadoFlujo =
  | 'verificando'
  | 'intercambiando'
  | 'requerido'
  | 'formulario'
  | 'enviando'
  | 'exito'
  | 'invalido'
  | 'error'

type RespuestaDesafioPropietario = {
  valido: boolean
  tipo_cuenta: TipoCuentaPropietario | null
  nombre: string | null
  apellido_paterno: string | null
  apellido_materno: string | null
  expira_en: string | null
}

function codigoError(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null) {
    return undefined
  }
  const posible = error as { status?: unknown; statusCode?: unknown }
  if (typeof posible.statusCode === 'number') {
    return posible.statusCode
  }
  return typeof posible.status === 'number' ? posible.status : undefined
}

export function useActivacionPropietario() {
  const estado = ref<EstadoFlujo>('verificando')
  const tipoCuenta = ref<TipoCuentaPropietario | null>(null)
  const identidadDesafio = ref({
    nombre: null as string | null,
    apellidoPaterno: null as string | null,
    apellidoMaterno: null as string | null,
  })
  const expiraEn = ref<string | null>(null)
  const mensajeError = ref('')

  function aplicarDesafio(respuesta: RespuestaDesafioPropietario): boolean {
    const valido = respuesta.valido
      && respuesta.tipo_cuenta !== null
      && respuesta.expira_en !== null
    tipoCuenta.value = valido ? respuesta.tipo_cuenta : null
    identidadDesafio.value = {
      nombre: valido ? respuesta.nombre : null,
      apellidoPaterno: valido ? respuesta.apellido_paterno : null,
      apellidoMaterno: valido ? respuesta.apellido_materno : null,
    }
    expiraEn.value = valido ? respuesta.expira_en : null
    estado.value = valido ? 'formulario' : 'requerido'
    mensajeError.value = ''
    return valido
  }

  async function canjearEnlace(token: string): Promise<boolean> {
    estado.value = 'intercambiando'
    try {
      await $fetch('/api/autenticacion/activacion-propietario/enlace', {
        method: 'POST',
        body: { token },
        credentials: 'same-origin',
        cache: 'no-store',
      })
      return await revisarDesafio()
    } catch (error: unknown) {
      estado.value = codigoError(error) === 404 ? 'invalido' : 'error'
      return false
    }
  }

  async function revisarDesafio(): Promise<boolean> {
    estado.value = 'verificando'
    try {
      const respuesta = await $fetch<RespuestaDesafioPropietario>(
        '/api/autenticacion/activacion-propietario/desafio',
        {
          credentials: 'same-origin',
          cache: 'no-store',
        },
      )
      return aplicarDesafio(respuesta)
    } catch {
      tipoCuenta.value = null
      identidadDesafio.value = {
        nombre: null,
        apellidoPaterno: null,
        apellidoMaterno: null,
      }
      expiraEn.value = null
      estado.value = 'error'
      return false
    }
  }

  async function completar(solicitud: {
    nombre: string
    apellido_paterno: string
    apellido_materno: string | null
    contrasena_admin: string
    confirmar_contrasena_admin: string
    contrasena_login?: string
    confirmar_contrasena_login?: string
  }): Promise<boolean> {
    if (estado.value === 'enviando') {
      return false
    }
    estado.value = 'enviando'
    mensajeError.value = ''
    try {
      await $fetch('/api/autenticacion/activacion-propietario/completar', {
        method: 'POST',
        body: solicitud,
        credentials: 'same-origin',
        cache: 'no-store',
      })
      estado.value = 'exito'
      return true
    } catch (error: unknown) {
      const codigo = codigoError(error)
      if (codigo === 404) {
        estado.value = 'invalido'
      } else {
        estado.value = 'formulario'
        mensajeError.value = codigo === 422
          ? 'Revisa los campos y las contraseñas.'
          : 'No fue posible establecer tu cuenta. Intenta nuevamente.'
      }
      return false
    }
  }

  return {
    estado,
    tipoCuenta,
    identidadDesafio,
    expiraEn,
    mensajeError,
    canjearEnlace,
    revisarDesafio,
    completar,
  }
}
