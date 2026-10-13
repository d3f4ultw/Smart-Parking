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
