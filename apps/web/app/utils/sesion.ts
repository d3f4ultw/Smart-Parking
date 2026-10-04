export type RolUsuario = 'ADMIN' | 'OPERADOR'

export interface UsuarioSesion {
  nombre: string | null
  apellido_paterno: string | null
  apellido_materno: string | null
  correo: string
  rol: RolUsuario
}

export interface RespuestaSesion {
  autenticado: true
  usuario: UsuarioSesion
}

export function obtenerNombreCompleto(usuario: UsuarioSesion): string {
  const partes = [
    usuario.nombre,
    usuario.apellido_paterno,
    usuario.apellido_materno,
  ]
    .map((parte) => parte?.trim() ?? '')
    .filter(Boolean)

  return partes.join(' ') || 'Operador'
}
