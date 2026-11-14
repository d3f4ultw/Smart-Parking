/** Correo y tipo de cuenta que el portal muestra mientras el cliente tiene acceso. */
export interface IdentidadClienteWeb {
  correo: string
  rol: 'CLIENTE'
}

/** Distingue entre no tener una sesión de cliente y no poder comprobarla;
 * ante un error, el portal no supone que el cliente salió.
 */
export type EstadoSesionClienteWeb =
  | { estado: 'anonima'; identidad: null }
  | { estado: 'autenticada'; identidad: IdentidadClienteWeb }
  | { estado: 'error'; identidad: null }

/** Datos que devuelve el servidor al comprobar el acceso del cliente,
 * como su correo y el código de seguridad que el portal podría necesitar.
 */
export interface RespuestaSesionCliente {
  autenticada: boolean
  clienteId?: string | null
  correo?: string | null
  rol?: string | null
  csrfToken?: string | null
}

export interface SolicitudRegistroCliente {
  nombres: string
  primerApellido: string
  segundoApellido: string | null
  correo: string
  contrasena: string
}

export interface RespuestaRegistroCliente {
  clienteId: string
  correo: string
}

export interface SolicitudInicioSesionCliente {
  correo: string
  contrasena: string
}

export interface SolicitudCambioContrasenaCliente {
  contrasenaActual: string
  nuevaContrasena: string
}

export interface RespuestaCsrfCliente {
  token: string
}

/** Situaciones que puede tener la membresía y que el portal explica al cliente. */
export type EstadoMembresiaCliente =
  | 'SIN_MEMBRESIA'
  | 'PENDIENTE'
  | 'ACTIVA'
  | 'PAGO_VENCIDO'
  | 'CANCELADA'
  | 'INACTIVA'

/** Compra iniciada pero no terminada; permite volver a pagar mientras el enlace
 * siga disponible y no haya vencido.
 */
export interface IntentoCheckoutPendienteCliente {
  intentoId: string
  estado: string
  expiraEn: string | null
}

/** Enlace temporal que lleva al proveedor de pago para terminar la compra. */
export interface RespuestaCheckoutMembresia {
  intentoId: string
  estado: string
  checkoutUrl: string
  expiraEn: string
}

export interface RespuestaEstadoCheckoutMembresia {
  intentoId: string
  estado: string
  checkoutUrl?: string | null
  expiraEn?: string | null
}

/** Información que el portal muestra sobre el plan, sus fechas de vigencia,
 * el siguiente cobro y si el cliente puede iniciar o retomar una compra.
 */
export interface MembresiaCliente {
  estado: EstadoMembresiaCliente
  plan: {
    productoId: string
    precioId: string
    nombre: string
    importeMenorUnidad: number
    moneda: string
    intervalo: string
    intervaloCantidad: number
  }
  periodoInicio: string | null
  periodoFin: string | null
  siguienteCobroEn: string | null
  cancelacionAlFinal: boolean
  puedeComprar: boolean
  checkoutPendiente: IntentoCheckoutPendienteCliente | null
}

/** Perfil del cliente y datos de su membresía que forman la pantalla principal del portal. */
export interface PortalCliente {
  cliente: {
    clienteId: string
    nombres: string
    primerApellido: string
    segundoApellido: string | null
    correo: string
  }
  membresia: MembresiaCliente
}
