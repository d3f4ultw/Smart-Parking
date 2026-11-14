export const ID_PENDIENTE = '10000000-0000-4000-8000-000000000001'
export const ID_EXPIRADO = '10000000-0000-4000-8000-000000000002'
export const ID_USADO = '10000000-0000-4000-8000-000000000003'
export const ID_ACTIVO = '10000000-0000-4000-8000-000000000004'
export const ID_INACTIVO = '10000000-0000-4000-8000-000000000005'
export const ID_EMPLEADO = '900000000001'
export const CORREO_SINTETICO = 'alta.qa@example.test'

type EstadoCuenta = 'PENDIENTE' | 'ACTIVA' | 'INACTIVA'
type EstadoInvitacion = 'ENVIADO' | 'EXPIRADA' | 'CONSUMIDA' | 'FALLIDO'
type OperadorSintetico = {
  id: string
  nombres: string
  primerApellido: string
  segundoApellido: string | null
  correo: string
  estado: EstadoCuenta
  estadoInvitacion: EstadoInvitacion
  puedeReemitirInvitacion: boolean
  empleadoIdTexto: string | null
  estadoConciliacion: 'VINCULADO' | 'LEGADO_SIN_VINCULO'
}
type EmpleadoSintetico = {
  idTexto: string
  nombres: string
  primerApellido: string
  segundoApellido: string | null
  correo: string | null
  codigo: string
  estado: 'ACTIVO'
  operador: null
  revisionTexto: string
}

export const operadoresSinteticos: OperadorSintetico[] = [
  crearOperador(ID_PENDIENTE, 'Ana', 'Pendiente', 'PENDIENTE', 'ENVIADO'),
  crearOperador(ID_EXPIRADO, 'Beto', 'Expirado', 'PENDIENTE', 'EXPIRADA'),
  crearOperador(ID_USADO, 'Cora', 'Usado', 'ACTIVA', 'CONSUMIDA'),
  crearOperador(ID_ACTIVO, 'Dalia', 'Activa', 'ACTIVA', 'ENVIADO'),
  crearOperador(ID_INACTIVO, 'Eli', 'Inactivo', 'INACTIVA', 'EXPIRADA'),
  ...Array.from({ length: 7 }, (_, indice) =>
    crearOperador(
      `10000000-0000-4000-8000-${String(indice + 6).padStart(12, '0')}`,
      `Operador${String(indice + 6).padStart(2, '0')}`,
      'Sintético',
      indice % 2 ? 'ACTIVA' : 'PENDIENTE',
      indice % 2 ? 'ENVIADO' : 'FALLIDO',
    ),
  ),
  crearOperador('10000000-0000-4000-8000-000000000013', 'Zoe', 'PáginaDos', 'ACTIVA', 'ENVIADO'),
]

export const empleadoSintetico: EmpleadoSintetico = {
  idTexto: ID_EMPLEADO,
  nombres: 'Ana',
  primerApellido: 'Disponible',
  segundoApellido: null,
  correo: null,
  codigo: 'E-0001',
  estado: 'ACTIVO',
  operador: null,
  revisionTexto: '1',
}

function crearOperador(
  id: string,
  nombres: string,
  primerApellido: string,
  estado: EstadoCuenta,
  estadoInvitacion: EstadoInvitacion,
): OperadorSintetico {
  return {
    id,
    nombres,
    primerApellido,
    segundoApellido: 'Prueba',
    correo: `${nombres.toLowerCase()}@example.test`,
    estado,
    estadoInvitacion,
    puedeReemitirInvitacion: estado === 'PENDIENTE',
    empleadoIdTexto: '900000000010',
    estadoConciliacion: 'VINCULADO',
  }
}

export function crearDetalleSintetico(operador: OperadorSintetico) {
  return {
    ...operador,
    invitacionGeneradaEn: '2026-11-09T12:00:00Z',
    invitacionVenceEn: operador.estadoInvitacion === 'EXPIRADA' ? '2026-11-01T12:00:00Z' : null,
    invitacionConsumidaEn:
      operador.estadoInvitacion === 'CONSUMIDA' ? '2026-11-09T13:00:00Z' : null,
    creadaEn: '2026-10-01T12:00:00Z',
    reenvioDisponibleEn: null,
    reemisionesRestantes: 2,
    recuperacionDisponibleEn: null,
    recuperacionesRestantes: 2,
    puedeDesactivar: operador.estado === 'ACTIVA',
    puedeReactivar: operador.estado === 'INACTIVA',
    puedeSolicitarRecuperacion: operador.estado === 'ACTIVA',
  }
}
