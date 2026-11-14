export const RUTAS_MODULOS_OPERADOR = [
  '/operador/monitoreo',
  '/operador/accesos',
  '/operador/clientes',
  '/operador/tarjetas',
] as const

export function esRutaModuloOperador(ruta: string) {
  return RUTAS_MODULOS_OPERADOR.includes(ruta as (typeof RUTAS_MODULOS_OPERADOR)[number])
}
