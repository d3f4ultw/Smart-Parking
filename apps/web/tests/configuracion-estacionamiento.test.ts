import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import {
  MODALIDADES_ESTACIONAMIENTO,
  mapearErrorConfiguracion,
  puedeGuardarModalidad,
} from '../app/utils/configuracion-estacionamiento.ts'
import {
  crearHorariosConfigurables,
  modalidadAdmiteHorarios,
  TURNOS_CONFIGURABLES,
  TURNO_SIN_RESTRICCION,
  validarHorariosConfigurables,
} from '../app/utils/horarios-empleados.ts'

const WEB_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')

test('la interfaz ofrece solo las tres clasificaciones existentes', () => {
  assert.deepEqual(
    MODALIDADES_ESTACIONAMIENTO.map((opcion) => [
      opcion.valor,
      opcion.etiqueta,
      opcion.descripcion,
    ]),
    [
      ['PRIVADO', 'Privado', 'Privado empresarial'],
      ['PUBLICO', 'Público', 'Público comercial'],
      ['MIXTO', 'Mixto', 'Clasificación mixta'],
    ],
  )
})

test('el guardado se bloquea sin cambios o durante una escritura', () => {
  assert.equal(puedeGuardarModalidad('PRIVADO', 'PRIVADO', false), false)
  assert.equal(puedeGuardarModalidad('PRIVADO', 'PUBLICO', true), false)
  assert.equal(puedeGuardarModalidad('PRIVADO', '', false), false)
  assert.equal(puedeGuardarModalidad('PRIVADO', 'PUBLICO', false), true)
  assert.equal(puedeGuardarModalidad(null, 'MIXTO', false), true)
  assert.equal(puedeGuardarModalidad('PRIVADO', 'PUBLICO', false, true), false)
})

test('los errores muestran mensajes seguros y distinguen permiso y concurrencia', () => {
  assert.match(mapearErrorConfiguracion({ status: 401 }), /sesión o tus permisos/)
  assert.match(mapearErrorConfiguracion({ statusCode: 403 }), /sesión o tus permisos/)
  assert.match(mapearErrorConfiguracion({ status: 409 }), /otra sesión/)
  assert.match(mapearErrorConfiguracion({ status: 422 }), /no es válida/)
  assert.match(mapearErrorConfiguracion(new Error('detalle interno')), /No fue posible/)
  assert.doesNotMatch(mapearErrorConfiguracion(new Error('detalle interno')), /detalle interno/)
})

test('la página conserva el límite OWNER, el SSR y la respuesta persistida', () => {
  const pagina = readFileSync(
    join(WEB_ROOT, 'app', 'pages', 'admin', 'configuracion.vue'),
    'utf8',
  )
  const layout = readFileSync(
    join(WEB_ROOT, 'app', 'layouts', 'admin.vue'),
    'utf8',
  )

  assert.match(pagina, /layout: 'admin'/)
  assert.match(pagina, /middleware: 'sesion-owner-operadores'/)
  assert.match(pagina, /await useAsyncData<ResultadoCarga>/)
  assert.match(pagina, /const fetchConCookies = useRequestFetch\(\)/)
  assert.match(pagina, /cache: 'no-store'/)
  assert.doesNotMatch(pagina, /window\.confirm/)
  assert.match(pagina, /<dialog[\s\S]*aria-labelledby="confirmation-title"/)
  assert.match(pagina, /dialogoConfirmacion\.value\?\.showModal\(\)/)
  assert.match(pagina, /Cancelar/)
  assert.match(pagina, /mostrarToast\('Modalidad '/)
  assert.match(pagina, /modalidadGuardada\.value = configuracion\.modalidad/)
  assert.match(pagina, /catch \(error: unknown\)[\s\S]*mensajeError\.value = mapearErrorConfiguracion/)
  assert.match(pagina, /name="modalidad"/)
  assert.match(pagina, /Acceso del estacionamiento/)
  assert.match(pagina, /Fuera de servicio/)
  assert.match(pagina, /Acceso suspendido/)
  assert.match(pagina, /acceso_suspendido/)
  assert.match(pagina, /disabled="!configuracionDisponible \|\| guardando \|\| accesoSuspendido"/)
  assert.match(pagina, /mostrarToast\(configuracion\.acceso_suspendido/)
  assert.match(pagina, /await carga\.refresh\(\)/)
  assert.match(pagina, /obtenerCodigoErrorHttp\(error\) === 409/)
  assert.match(pagina, /await actualizarConfiguracionAutoritativa\(\)/)
  assert.match(pagina, /'\/api\/admin\/configuracion\/acceso'/)
  assert.doesNotMatch(pagina, /window\.confirm|Notification\.requestPermission|new Notification/)
  assert.match(pagina, /Guardar cambios/)
  assert.match(pagina, /no cambia las operaciones de/)
  assert.match(layout, /v-if="usuario\?\.rol === 'OWNER'"/)
  assert.match(layout, /to="\/admin\/configuracion"/)
})

test('los horarios solo aplican a Empresarial y Mixta', () => {
  assert.equal(modalidadAdmiteHorarios('PRIVADO'), true)
  assert.equal(modalidadAdmiteHorarios('MIXTO'), true)
  assert.equal(modalidadAdmiteHorarios('PUBLICO'), false)
  assert.equal(modalidadAdmiteHorarios(null), false)
  assert.deepEqual(TURNOS_CONFIGURABLES.map(({ codigo, etiqueta }) => [codigo, etiqueta]), [
    ['MATUTINO', 'Matutino'],
    ['VESPERTINO', 'Vespertino'],
    ['NOCTURNO', 'Nocturno'],
  ])
  assert.deepEqual(TURNO_SIN_RESTRICCION, {
    codigo: 'SIN_RESTRICCION',
    etiqueta: 'Sin restricción',
  })
})

test('la interfaz valida intervalos completos y permite cruce de medianoche', () => {
  const respuesta = {
    revision: 4,
    zona_horaria: 'America/Mexico_City',
    turnos: [
      { id: 1, codigo: 'MATUTINO', nombre: 'Matutino', hora_inicio: null, hora_fin: null },
      { id: 2, codigo: 'VESPERTINO', nombre: 'Vespertino', hora_inicio: null, hora_fin: null },
      { id: 3, codigo: 'NOCTURNO', nombre: 'Nocturno', hora_inicio: null, hora_fin: null },
      { id: 4, codigo: 'SIN_RESTRICCION', nombre: 'Sin restricción', hora_inicio: null, hora_fin: null },
    ],
  } as const
  const horarios = crearHorariosConfigurables(respuesta)

  assert.deepEqual(validarHorariosConfigurables(horarios), {})
  assert.deepEqual(validarHorariosConfigurables({
    ...horarios,
    NOCTURNO: { hora_inicio: '22:00', hora_fin: '06:00' },
  }), {})
  assert.match(validarHorariosConfigurables({
    ...horarios,
    MATUTINO: { hora_inicio: '06:00', hora_fin: null },
  }).MATUTINO ?? '', /ambas horas/)
  assert.match(validarHorariosConfigurables({
    ...horarios,
    MATUTINO: { hora_inicio: '06:00', hora_fin: '06:00' },
  }).MATUTINO ?? '', /distintas/)
  assert.match(validarHorariosConfigurables({
    ...horarios,
    MATUTINO: { hora_inicio: '24:00', hora_fin: '06:00' },
  }).MATUTINO ?? '', /válidas/)
})

test('la sección solo se monta para el Dueño y modalidad permitida', () => {
  const pagina = readFileSync(
    join(WEB_ROOT, 'app', 'pages', 'admin', 'configuracion.vue'),
    'utf8',
  )
  const panel = readFileSync(
    join(WEB_ROOT, 'app', 'components', 'admin', 'HorariosEmpleadosPanel.vue'),
    'utf8',
  )

  assert.match(pagina, /usuario\.value\?\.rol === 'OWNER'/)
  assert.match(pagina, /modalidadGuardada\.value === 'PRIVADO'/)
  assert.match(pagina, /modalidadGuardada\.value === 'MIXTO'/)
  assert.match(pagina, /<AdminHorariosEmpleadosPanel v-if="puedeAdministrarHorarios"/)
  assert.match(panel, /useRequestFetch\(\)/)
  assert.match(panel, /cache: 'no-store'/)
  assert.match(panel, /clearNuxtData\(CLAVE_DATOS\)/)
  assert.match(panel, /TURNO_SIN_RESTRICCION\.etiqueta/)
  assert.match(panel, /Si el turno termina al día siguiente/)
  assert.match(panel, /22:00|hora_inicio/)
  assert.doesNotMatch(panel, /timezone.*select|type="timezone"/i)
})
