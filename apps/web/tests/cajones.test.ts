import assert from 'node:assert/strict'
import test from 'node:test'

import {
  aplicarInstantaneaCajon,
  crearSolicitudEstadoOperativo,
  contarCajones,
  ETIQUETAS_ESTADO_EFECTIVO,
  ETIQUETAS_ESTADO_FISICO,
  ETIQUETAS_ESTADO_OPERATIVO,
  esRespuestaMutacionCajon,
  estadoOperativoSinCambios,
  ordenarCajones,
  type Cajon,
  type EstadoEfectivoCajon,
} from '../app/utils/cajones.ts'
import type { InstantaneaEventoCajon } from '../app/utils/eventos-tiempo-real.ts'

function crearCajon(
  id: number,
  numero: number,
  estadoEfectivo: EstadoEfectivoCajon,
): Cajon {
  const estados: Record<EstadoEfectivoCajon, Pick<
    Cajon,
    'estado_fisico' | 'estado_operativo' | 'motivo_operativo'
  >> = {
    LIBRE: {
      estado_fisico: 'LIBRE',
      estado_operativo: 'DISPONIBLE',
      motivo_operativo: null,
    },
    OCUPADO: {
      estado_fisico: 'OCUPADO',
      estado_operativo: 'DISPONIBLE',
      motivo_operativo: null,
    },
    NO_DISPONIBLE: {
      estado_fisico: 'LIBRE',
      estado_operativo: 'MANTENIMIENTO',
      motivo_operativo: 'Inspección',
    },
    DESCONOCIDO: {
      estado_fisico: 'DESCONOCIDO',
      estado_operativo: 'DISPONIBLE',
      motivo_operativo: null,
    },
  }

  return {
    id,
    numero,
    vision_zone_id: `00000000-0000-4000-8000-${String(id).padStart(12, '0')}`,
    activa: true,
    vision_desactualizada: false,
    ...estados[estadoEfectivo],
    estado_fisico_actualizado_en: null,
    estado_operativo_actualizado_en: '2026-10-07T12:00:00Z',
    creado_en: '2026-10-01T12:00:00Z',
    estado_efectivo: estadoEfectivo,
  }
}

function crearInstantaneaEventoCajon(
  cambios: Partial<InstantaneaEventoCajon> = {},
): InstantaneaEventoCajon {
  return {
    cajon_id: 41,
    numero: 1,
    vision_zone_id: '00000000-0000-4000-8000-000000000041',
    activa: true,
    vision_desactualizada: false,
    estado_fisico: 'LIBRE',
    estado_operativo: 'DISPONIBLE',
    motivo_operativo: null,
    estado_efectivo: 'LIBRE',
    estado_fisico_actualizado_en: '2026-10-08T10:30:00Z',
    estado_operativo_actualizado_en: '2026-10-08T09:00:00Z',
    actualizado_en: '2026-10-08T10:30:00Z',
    ...cambios,
  }
}

function verificarSuma(conteo: ReturnType<typeof contarCajones>) {
  assert.equal(
    conteo.libres
      + conteo.ocupados
      + conteo.noDisponibles
      + conteo.desconocidos,
    conteo.total,
  )
}

test('contarCajones returns zero counts for an empty list', () => {
  const conteo = contarCajones([])

  assert.deepEqual(conteo, {
    total: 0,
    libres: 0,
    ocupados: 0,
    noDisponibles: 0,
    desconocidos: 0,
  })
  verificarSuma(conteo)
})

test('contarCajones counts one authoritative effective state', () => {
  const cajon = crearCajon(12, 4, 'LIBRE')
  const conteo = contarCajones([cajon])

  assert.equal(conteo.total, 1)
  assert.equal(conteo.libres, 1)
  assert.equal(conteo.desconocidos, 0)
  verificarSuma(conteo)
})

test('contarCajones handles arbitrary N and all effective states', () => {
  const estados: EstadoEfectivoCajon[] = [
    'LIBRE',
    'OCUPADO',
    'NO_DISPONIBLE',
    'DESCONOCIDO',
    'LIBRE',
    'DESCONOCIDO',
    'NO_DISPONIBLE',
    'OCUPADO',
    'LIBRE',
    'NO_DISPONIBLE',
    'OCUPADO',
    'DESCONOCIDO',
    'LIBRE',
    'OCUPADO',
    'LIBRE',
  ]
  const cajones = estados.map((estado, indice) =>
    crearCajon(indice + 100, indice + 1, estado),
  )
  const conteo = contarCajones(cajones)

  assert.deepEqual(conteo, {
    total: 15,
    libres: 5,
    ocupados: 4,
    noDisponibles: 3,
    desconocidos: 3,
  })
  verificarSuma(conteo)
})

test('DESCONOCIDO remains separate from LIBRE even when operationally available', () => {
  const cajon = crearCajon(31, 1, 'DESCONOCIDO')
  const conteo = contarCajones([cajon])

  assert.equal(cajon.estado_fisico, 'DESCONOCIDO')
  assert.equal(cajon.estado_operativo, 'DISPONIBLE')
  assert.equal(conteo.libres, 0)
  assert.equal(conteo.desconocidos, 1)
  verificarSuma(conteo)
})

test('ordenarCajones uses numeric slot order and preserves stable records', () => {
  const cajonDiez = crearCajon(101, 10, 'OCUPADO')
  const cajonDos = crearCajon(202, 2, 'DESCONOCIDO')
  const cajonTres = crearCajon(303, 3, 'LIBRE')
  const entrada = [cajonDiez, cajonDos, cajonTres]
  const ordenados = ordenarCajones(entrada)

  assert.deepEqual(ordenados.map((cajon) => cajon.numero), [2, 3, 10])
  assert.strictEqual(ordenados[0], cajonDos)
  assert.strictEqual(ordenados[1], cajonTres)
  assert.strictEqual(ordenados[2], cajonDiez)
  assert.deepEqual(entrada, [cajonDiez, cajonDos, cajonTres])
  assert.equal(new Set(ordenados.map((cajon) => cajon.id)).size, entrada.length)
})

test('state labels cover the exact API unions without inventing a status', () => {
  assert.deepEqual(ETIQUETAS_ESTADO_EFECTIVO, {
    LIBRE: 'Libre',
    OCUPADO: 'Ocupado',
    NO_DISPONIBLE: 'No disponible',
    DESCONOCIDO: 'Desconocido',
  })
  assert.deepEqual(ETIQUETAS_ESTADO_FISICO, {
    DESCONOCIDO: 'Desconocido',
    LIBRE: 'Libre',
    OCUPADO: 'Ocupado',
  })
  assert.deepEqual(ETIQUETAS_ESTADO_OPERATIVO, {
    DISPONIBLE: 'Disponible',
    MANTENIMIENTO: 'Mantenimiento',
    FUERA_DE_SERVICIO: 'Fuera de servicio',
  })
})

test('operational requests include each API state and trim optional reasons', () => {
  assert.deepEqual(
    crearSolicitudEstadoOperativo('DISPONIBLE', ' motivo anterior '),
    { tipo: 'valida', solicitud: { estado: 'DISPONIBLE' } },
  )
  assert.deepEqual(
    crearSolicitudEstadoOperativo('MANTENIMIENTO', '  Inspección  '),
    { tipo: 'valida', solicitud: { estado: 'MANTENIMIENTO', motivo: 'Inspección' } },
  )
  assert.deepEqual(
    crearSolicitudEstadoOperativo('FUERA_DE_SERVICIO', '  Reparación  '),
    { tipo: 'valida', solicitud: { estado: 'FUERA_DE_SERVICIO', motivo: 'Reparación' } },
  )
})

test('operational reason is optional and validation uses its trimmed length', () => {
  assert.deepEqual(
    crearSolicitudEstadoOperativo('MANTENIMIENTO', '   '),
    { tipo: 'valida', solicitud: { estado: 'MANTENIMIENTO' } },
  )
  assert.deepEqual(
    crearSolicitudEstadoOperativo('FUERA_DE_SERVICIO', ''),
    { tipo: 'valida', solicitud: { estado: 'FUERA_DE_SERVICIO' } },
  )
  assert.deepEqual(
    crearSolicitudEstadoOperativo('MANTENIMIENTO', ` ${'x'.repeat(250)} `),
    { tipo: 'valida', solicitud: { estado: 'MANTENIMIENTO', motivo: 'x'.repeat(250) } },
  )
  assert.deepEqual(
    crearSolicitudEstadoOperativo('FUERA_DE_SERVICIO', 'x'.repeat(251)),
    { tipo: 'invalida', mensaje: 'El motivo no puede superar 250 caracteres.' },
  )
})

test('available state rejects a reason and no-op comparison uses normalized payload', () => {
  assert.deepEqual(
    crearSolicitudEstadoOperativo('DISPONIBLE', ''),
    { tipo: 'valida', solicitud: { estado: 'DISPONIBLE' } },
  )
  const cajon = crearCajon(41, 1, 'NO_DISPONIBLE')
  assert.equal(
    estadoOperativoSinCambios(cajon, {
      estado: 'MANTENIMIENTO',
      motivo: 'Inspección',
    }),
    true,
  )
  assert.equal(
    estadoOperativoSinCambios(
      { ...cajon, motivo_operativo: '  Inspección  ' },
      { estado: 'MANTENIMIENTO', motivo: 'Inspección' },
    ),
    true,
  )
  assert.equal(
    estadoOperativoSinCambios(cajon, {
      estado: 'FUERA_DE_SERVICIO',
      motivo: 'Inspección',
    }),
    false,
  )
})

test('mutation response must match the selected ID and use a strict boolean', () => {
  const respuesta = {
    ...crearCajon(41, 1, 'NO_DISPONIBLE'),
    cambio_aplicado: false,
  }

  assert.equal(esRespuestaMutacionCajon(respuesta, 41), true)
  assert.equal(esRespuestaMutacionCajon(respuesta, 42), false)
  assert.equal(
    esRespuestaMutacionCajon({ ...respuesta, cambio_aplicado: 0 }, 41),
    false,
  )
  assert.equal(
    esRespuestaMutacionCajon({ ...respuesta, estado_fisico: 'EN_USO' }, 41),
    false,
  )
})

test('aplicarInstantaneaCajon updates only the stable ID and preserves list-only fields', () => {
  const cajonObjetivo = crearCajon(41, 1, 'LIBRE')
  const cajonNoRelacionado = crearCajon(7, 41, 'DESCONOCIDO')
  const respuesta = {
    cajones: [cajonObjetivo, cajonNoRelacionado],
    cursor_eventos: '350',
    vision: { stale: false, last_heartbeat_at: null, last_observation_at: null, stale_after_seconds: 45 },
  }

  const resultado = aplicarInstantaneaCajon(
    respuesta,
    crearInstantaneaEventoCajon({
      numero: 9,
      estado_fisico: 'OCUPADO',
      estado_efectivo: 'OCUPADO',
    }),
  )

  assert.equal(resultado.tipo, 'aplicada')
  if (resultado.tipo !== 'aplicada') {
    return
  }
  assert.deepEqual(resultado.respuesta.cajones[0], {
    ...cajonObjetivo,
    numero: 9,
    estado_fisico: 'OCUPADO',
    estado_fisico_actualizado_en: '2026-10-08T10:30:00Z',
    estado_operativo_actualizado_en: '2026-10-08T09:00:00Z',
    estado_efectivo: 'OCUPADO',
  })
  assert.strictEqual(resultado.respuesta.cajones[1], cajonNoRelacionado)
  assert.equal(resultado.respuesta.cajones[0]?.creado_en, cajonObjetivo.creado_en)
  assert.equal(resultado.respuesta.cursor_eventos, '350')
  assert.equal(cajonObjetivo.estado_efectivo, 'LIBRE')
})

test('event snapshots drive effective counters for transitions and maintenance precedence', () => {
  const cajonLibre = crearCajon(41, 1, 'LIBRE')
  const cajonMantenimiento = crearCajon(12, 2, 'NO_DISPONIBLE')
  const cajonDesconocido = crearCajon(5, 3, 'DESCONOCIDO')
  const respuesta = {
    cajones: [cajonLibre, cajonMantenimiento, cajonDesconocido],
    cursor_eventos: '351',
    vision: { stale: false, last_heartbeat_at: null, last_observation_at: null, stale_after_seconds: 45 },
  }

  const ocupado = aplicarInstantaneaCajon(
    respuesta,
    crearInstantaneaEventoCajon({
      estado_fisico: 'OCUPADO',
      estado_efectivo: 'OCUPADO',
    }),
  )
  assert.equal(ocupado.tipo, 'aplicada')
  if (ocupado.tipo !== 'aplicada') {
    return
  }
  assert.deepEqual(contarCajones(ocupado.respuesta.cajones), {
    total: 3,
    libres: 0,
    ocupados: 1,
    noDisponibles: 1,
    desconocidos: 1,
  })
  verificarSuma(contarCajones(ocupado.respuesta.cajones))

  const libreOtraVez = aplicarInstantaneaCajon(
    ocupado.respuesta,
    crearInstantaneaEventoCajon({
      estado_fisico: 'LIBRE',
      estado_efectivo: 'LIBRE',
      estado_fisico_actualizado_en: '2026-10-08T10:31:00Z',
      actualizado_en: '2026-10-08T10:31:00Z',
    }),
  )
  assert.equal(libreOtraVez.tipo, 'aplicada')
  if (libreOtraVez.tipo !== 'aplicada') {
    return
  }
  assert.equal(libreOtraVez.respuesta.cajones[0]?.estado_efectivo, 'LIBRE')
  assert.deepEqual(contarCajones(libreOtraVez.respuesta.cajones), {
    total: 3,
    libres: 1,
    ocupados: 0,
    noDisponibles: 1,
    desconocidos: 1,
  })

  const noDisponible = aplicarInstantaneaCajon(
    libreOtraVez.respuesta,
    crearInstantaneaEventoCajon({
      cajon_id: 12,
      numero: 2,
      vision_zone_id: '00000000-0000-4000-8000-000000000012',
      estado_fisico: 'LIBRE',
      estado_operativo: 'MANTENIMIENTO',
      motivo_operativo: 'Inspección',
      estado_efectivo: 'NO_DISPONIBLE',
    }),
  )
  assert.equal(noDisponible.tipo, 'aplicada')
  if (noDisponible.tipo !== 'aplicada') {
    return
  }
  assert.equal(noDisponible.respuesta.cajones[1]?.estado_fisico, 'LIBRE')
  assert.equal(noDisponible.respuesta.cajones[1]?.estado_efectivo, 'NO_DISPONIBLE')
  assert.equal(contarCajones(noDisponible.respuesta.cajones).libres, 1)
})

test('an unknown event ID requests authoritative reconciliation without adding a partial row', () => {
  const respuesta = {
    cajones: [crearCajon(41, 1, 'LIBRE')],
    cursor_eventos: '352',
    vision: { stale: false, last_heartbeat_at: null, last_observation_at: null, stale_after_seconds: 45 },
  }

  const resultado = aplicarInstantaneaCajon(
    respuesta,
    crearInstantaneaEventoCajon({ cajon_id: 999, numero: 2 }),
  )

  assert.deepEqual(resultado, { tipo: 'cajon-desconocido', respuesta })
  assert.strictEqual(resultado.respuesta, respuesta)
  assert.equal(resultado.respuesta.cajones.length, 1)
})
