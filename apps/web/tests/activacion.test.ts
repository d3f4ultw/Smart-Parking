import assert from 'node:assert/strict'
import test from 'node:test'

import {
  activarSiEsValida,
  construirSolicitudActivacion,
  esActivacionNoDisponible,
  evaluarDiferenciaContrasenaTemporal,
  evaluarRequisitosContrasena,
  limpiarDatosFormularioActivacion,
  mapearErrorActivacion,
  obtenerModoPrevalidado,
  obtenerTokenActivacion,
  puedeEnviarActivacion,
  validarDatosActivacion,
  type DatosFormularioActivacion,
} from '../app/utils/activacion.ts'

const datosBase: DatosFormularioActivacion = {
  codigo: '123456',
  contrasenaTemporal: 'Temporal exacta con espacios',
  nuevaContrasena: 'MiClaveNueva',
  confirmarContrasena: 'MiClaveNueva',
}

test('lee solamente el token presente en la URL', () => {
  assert.equal(obtenerTokenActivacion('token-de-prueba'), 'token-de-prueba')
  assert.equal(obtenerTokenActivacion(''), null)
  assert.equal(obtenerTokenActivacion(['token-de-prueba']), null)
})

test('acepta unicamente el modo resuelto por el backend', () => {
  assert.equal(obtenerModoPrevalidado({ modo: 'manual' }), 'manual')
  assert.equal(obtenerModoPrevalidado({ modo: 'temporal' }), 'temporal')
  assert.equal(obtenerModoPrevalidado({ modo: 'otro' }), null)
  assert.equal(obtenerModoPrevalidado({}), null)
  assert.equal(obtenerModoPrevalidado(null), null)
})

test('valida el formulario manual sin crear campos de contraseña', () => {
  assert.equal(validarDatosActivacion('manual', datosBase), null)
  const solicitud = construirSolicitudActivacion(
    'manual',
    'token-no-renderizado',
    datosBase,
  )
  assert.deepEqual(solicitud, {
    token: 'token-no-renderizado',
    codigo: '123456',
  })
})

test('conserva exactamente las contraseñas temporales al construir el payload', () => {
  const datos = {
    ...datosBase,
    contrasenaTemporal: ' temporal con espacios ',
    nuevaContrasena: 'Nueva contrasena con espacios 123',
    confirmarContrasena: 'Nueva contrasena con espacios 123',
  }
  const solicitud = construirSolicitudActivacion(
    'temporal',
    'token-no-renderizado',
    datos,
  )
  assert.equal(validarDatosActivacion('temporal', datos), null)
  assert.deepEqual(solicitud, {
    token: 'token-no-renderizado',
    codigo: '123456',
    contrasena_temporal: ' temporal con espacios ',
    nueva_contrasena: 'Nueva contrasena con espacios 123',
    confirmar_contrasena: 'Nueva contrasena con espacios 123',
  })
})

test('valida código, longitud y coincidencia de contraseñas', () => {
  assert.match(
    validarDatosActivacion('manual', { ...datosBase, codigo: '' }) ?? '',
    /6 dígitos/,
  )
  assert.match(
    validarDatosActivacion('temporal', {
      ...datosBase,
      nuevaContrasena: 'corta',
      confirmarContrasena: 'corta',
    }) ?? '',
    /al menos 10/,
  )
  assert.match(
    validarDatosActivacion('temporal', {
      ...datosBase,
      nuevaContrasena: 'abcdefghij',
      confirmarContrasena: 'abcdefghij',
    }) ?? '',
    /letra mayúscula/,
  )
  assert.match(
    validarDatosActivacion('temporal', {
      ...datosBase,
      confirmarContrasena: 'otra contraseña segura 123',
    }) ?? '',
    /no coinciden/,
  )
})

test('muestra el estado independiente de cada requisito de contraseña', () => {
  assert.deepEqual(evaluarRequisitosContrasena('Abc123', 'Abc123'), {
    longitudValida: false,
    mayusculaValida: true,
    coincidenciaValida: true,
    diferenteDeTemporal: null,
  })
  assert.deepEqual(evaluarRequisitosContrasena('abcdefghij', 'abcdefghix'), {
    longitudValida: true,
    mayusculaValida: false,
    coincidenciaValida: false,
    diferenteDeTemporal: null,
  })
  assert.deepEqual(evaluarRequisitosContrasena('MiClaveNueva', 'MiClaveNueva'), {
    longitudValida: true,
    mayusculaValida: true,
    coincidenciaValida: true,
    diferenteDeTemporal: null,
  })
})

test('evalúa la diferencia temporal sin normalizar y mantiene estado neutral al inicio', () => {
  assert.equal(evaluarDiferenciaContrasenaTemporal('', ''), null)
  assert.equal(evaluarDiferenciaContrasenaTemporal('', 'TemporalABC123'), null)
  assert.equal(evaluarDiferenciaContrasenaTemporal('NuevaABC123', ''), null)
  assert.equal(
    evaluarDiferenciaContrasenaTemporal('TemporalABC123', 'TemporalABC123'),
    false,
  )
  assert.equal(
    evaluarDiferenciaContrasenaTemporal('NuevaABC123', 'TemporalABC123'),
    true,
  )
  assert.equal(
    evaluarDiferenciaContrasenaTemporal(' TemporalABC123 ', 'TemporalABC123'),
    true,
  )
})

test('cambia de diferente a igual de forma reactiva y bloquea el envío', async () => {
  const temporal = 'TemporalABC123'
  const datos = {
    ...datosBase,
    contrasenaTemporal: temporal,
    nuevaContrasena: 'NuevaClaveABC123',
    confirmarContrasena: 'NuevaClaveABC123',
  }

  assert.equal(
    evaluarRequisitosContrasena(
      datos.nuevaContrasena,
      datos.confirmarContrasena,
      datos.contrasenaTemporal,
    ).diferenteDeTemporal,
    true,
  )

  datos.nuevaContrasena = temporal
  datos.confirmarContrasena = temporal
  const requisitos = evaluarRequisitosContrasena(
    datos.nuevaContrasena,
    datos.confirmarContrasena,
    datos.contrasenaTemporal,
  )
  assert.equal(requisitos.diferenteDeTemporal, false)
  assert.equal(puedeEnviarActivacion('temporal', datos, true), false)

  let llamadas = 0
  const error = await activarSiEsValida(
    'temporal',
    'token-no-renderizado',
    datos,
    async () => {
      llamadas += 1
    },
  )
  assert.match(error ?? '', /diferente de la contraseña temporal/)
  assert.equal(llamadas, 0)
})

test('cambia de igual a diferente y conserva las demás reglas válidas', () => {
  const datos = {
    ...datosBase,
    contrasenaTemporal: 'TemporalABC123',
    nuevaContrasena: 'TemporalABC123',
    confirmarContrasena: 'TemporalABC123',
  }
  assert.equal(
    evaluarRequisitosContrasena(
      datos.nuevaContrasena,
      datos.confirmarContrasena,
      datos.contrasenaTemporal,
    ).diferenteDeTemporal,
    false,
  )

  datos.nuevaContrasena = 'NuevaClaveABC123'
  datos.confirmarContrasena = datos.nuevaContrasena
  assert.deepEqual(
    evaluarRequisitosContrasena(
      datos.nuevaContrasena,
      datos.confirmarContrasena,
      datos.contrasenaTemporal,
    ),
    {
      longitudValida: true,
      mayusculaValida: true,
      coincidenciaValida: true,
      diferenteDeTemporal: true,
    },
  )
})

test('mantiene independientes coincidencia, diferencia, longitud y mayúscula', () => {
  const temporal = 'TemporalABC123'
  const datosCoincidencia = {
    ...datosBase,
    contrasenaTemporal: temporal,
    nuevaContrasena: 'NuevaPasswordABC',
    confirmarContrasena: 'OtraPasswordABC',
  }
  const requisitosCoincidencia = evaluarRequisitosContrasena(
    datosCoincidencia.nuevaContrasena,
    datosCoincidencia.confirmarContrasena,
    datosCoincidencia.contrasenaTemporal,
  )
  assert.equal(requisitosCoincidencia.diferenteDeTemporal, true)
  assert.equal(requisitosCoincidencia.coincidenciaValida, false)
  assert.equal(puedeEnviarActivacion('temporal', datosCoincidencia, true), false)

  const datosCorta = {
    ...datosBase,
    contrasenaTemporal: temporal,
    nuevaContrasena: 'Abc',
    confirmarContrasena: 'Abc',
  }
  const requisitosCorta = evaluarRequisitosContrasena(
    datosCorta.nuevaContrasena,
    datosCorta.confirmarContrasena,
    datosCorta.contrasenaTemporal,
  )
  assert.equal(requisitosCorta.diferenteDeTemporal, true)
  assert.equal(requisitosCorta.longitudValida, false)
  assert.equal(puedeEnviarActivacion('temporal', datosCorta, true), false)

  const datosSinMayuscula = {
    ...datosBase,
    contrasenaTemporal: temporal,
    nuevaContrasena: 'abcdefghijk',
    confirmarContrasena: 'abcdefghijk',
  }
  const requisitosSinMayuscula = evaluarRequisitosContrasena(
    datosSinMayuscula.nuevaContrasena,
    datosSinMayuscula.confirmarContrasena,
    datosSinMayuscula.contrasenaTemporal,
  )
  assert.equal(requisitosSinMayuscula.diferenteDeTemporal, true)
  assert.equal(requisitosSinMayuscula.mayusculaValida, false)
  assert.equal(
    puedeEnviarActivacion('temporal', datosSinMayuscula, true),
    false,
  )
})

test('aísla el modo manual de la comparación temporal', () => {
  const datosManuales: DatosFormularioActivacion = {
    codigo: '123456',
    contrasenaTemporal: '',
    nuevaContrasena: '',
    confirmarContrasena: '',
  }

  assert.equal(validarDatosActivacion('manual', datosManuales), null)
  assert.equal(puedeEnviarActivacion('manual', datosManuales, true), true)
  assert.deepEqual(
    construirSolicitudActivacion('manual', 'token-no-renderizado', datosManuales),
    { token: 'token-no-renderizado', codigo: '123456' },
  )
})

test('no hace request si la contraseña temporal es inválida', async () => {
  let llamadas = 0
  const error = await activarSiEsValida(
    'temporal',
    'token-no-renderizado',
    {
      ...datosBase,
      nuevaContrasena: 'abcdefghij',
      confirmarContrasena: 'abcdefghij',
    },
    async () => {
      llamadas += 1
    },
  )

  assert.match(error ?? '', /letra mayúscula/)
  assert.equal(llamadas, 0)
})

test('hace exactamente un request cuando la activación es válida', async () => {
  let llamadas = 0
  const error = await activarSiEsValida(
    'temporal',
    'token-no-renderizado',
    datosBase,
    async () => {
      llamadas += 1
    },
  )

  assert.equal(error, null)
  assert.equal(llamadas, 1)
})

test('deshabilita el envío para estados inválidos del formulario', () => {
  assert.equal(
    puedeEnviarActivacion(
      'temporal',
      { ...datosBase, nuevaContrasena: 'Abc123', confirmarContrasena: 'Abc123' },
      true,
    ),
    false,
  )
  assert.equal(puedeEnviarActivacion('temporal', datosBase, true), true)
  assert.equal(puedeEnviarActivacion('temporal', datosBase, false), false)
})

test('mapea fallos del backend sin devolver detalles internos', () => {
  assert.match(mapearErrorActivacion(404), /ya no es válido/)
  assert.match(mapearErrorActivacion(422), /Revisa los datos/)
  assert.match(mapearErrorActivacion(429), /límite/)
  assert.match(mapearErrorActivacion(503), /Inténtalo más tarde/)
})

test('usa la categoría estructurada para detectar activación no disponible', () => {
  assert.equal(
    esActivacionNoDisponible({
      data: {
        detail: {
          code: 'ACTIVACION_NO_DISPONIBLE',
          message: 'Activacion no disponible',
        },
      },
    }),
    true,
  )
  assert.equal(
    esActivacionNoDisponible({
      data: {
        detail: {
          code: 'DATOS_ACTIVACION_INVALIDOS',
        },
      },
    }),
    false,
  )
  assert.equal(
    esActivacionNoDisponible({
      status: 404,
      data: { detail: 'Activacion no disponible' },
    }),
    false,
  )
})

test('limpia todos los campos sensibles del formulario', () => {
  const datos = {
    codigo: '123456',
    contrasenaTemporal: 'Temporal secreta',
    nuevaContrasena: 'NuevaClaveSegura',
    confirmarContrasena: 'NuevaClaveSegura',
  }

  limpiarDatosFormularioActivacion(datos)

  assert.deepEqual(datos, {
    codigo: '',
    contrasenaTemporal: '',
    nuevaContrasena: '',
    confirmarContrasena: '',
  })
})
