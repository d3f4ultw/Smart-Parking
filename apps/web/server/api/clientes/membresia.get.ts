import { createError } from 'h3'

import {
  exigirSinParametros,
  solicitarApiCliente,
} from '../../utils/proxy-clientes'

const ESTADOS_MEMBRESIA = new Set([
  'sin_membresia',
  'pendiente',
  'activa',
  'cancelacion_programada',
  'pago_vencido',
  'inactiva',
  'cancelada',
])

function respuestaNoValida(): never {
  throw createError({ statusCode: 502, statusMessage: 'La respuesta de membresía no es válida.' })
}

function esFechaNullable(valor: unknown): valor is string | null {
  return valor === null || typeof valor === 'string'
}

function validarRespuestaMembresia(valor: unknown) {
  if (valor === null || typeof valor !== 'object' || Array.isArray(valor)) {
    return respuestaNoValida()
  }

  const respuesta = valor as Record<string, unknown>
  const membresia = respuesta.membresia
  if (
    typeof respuesta.estado !== 'string'
    || !ESTADOS_MEMBRESIA.has(respuesta.estado)
    || typeof respuesta.checkout_pendiente !== 'boolean'
    || typeof respuesta.puede_comprar !== 'boolean'
    || (membresia !== null && (typeof membresia !== 'object' || Array.isArray(membresia)))
  ) {
    return respuestaNoValida()
  }

  if (membresia === null) {
    return {
      estado: respuesta.estado,
      membresia: null,
      checkout_pendiente: respuesta.checkout_pendiente,
      puede_comprar: respuesta.puede_comprar,
    }
  }

  const detalle = membresia as Record<string, unknown>
  if (
    typeof detalle.plan !== 'string'
    || typeof detalle.monto_centavos !== 'number'
    || !Number.isSafeInteger(detalle.monto_centavos)
    || typeof detalle.moneda !== 'string'
    || typeof detalle.intervalo !== 'string'
    || typeof detalle.intervalo_cantidad !== 'number'
    || !Number.isSafeInteger(detalle.intervalo_cantidad)
    || !esFechaNullable(detalle.fecha_inicio)
    || !esFechaNullable(detalle.periodo_actual_inicio)
    || !esFechaNullable(detalle.periodo_actual_fin)
    || typeof detalle.cancelacion_programada !== 'boolean'
  ) {
    return respuestaNoValida()
  }

  return {
    estado: respuesta.estado,
    membresia: {
      plan: detalle.plan,
      monto_centavos: detalle.monto_centavos,
      moneda: detalle.moneda,
      intervalo: detalle.intervalo,
      intervalo_cantidad: detalle.intervalo_cantidad,
      fecha_inicio: detalle.fecha_inicio,
      periodo_actual_inicio: detalle.periodo_actual_inicio,
      periodo_actual_fin: detalle.periodo_actual_fin,
      cancelacion_programada: detalle.cancelacion_programada,
    },
    checkout_pendiente: respuesta.checkout_pendiente,
    puede_comprar: respuesta.puede_comprar,
  }
}

export default defineEventHandler(async (event) => {
  exigirSinParametros(event, 'La consulta de membresía no es válida.')
  const respuesta = await solicitarApiCliente(event, {
    ruta: '/api/clientes/membresia',
    metodo: 'GET',
    incluirSesion: true,
  })
  return validarRespuestaMembresia(respuesta)
})
