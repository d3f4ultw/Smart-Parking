import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import {
  etiquetaEstadoMembresia,
  formatearFechaMembresia,
  formatearPrecioMembresia,
  obtenerPaginaSolicitadaClientes,
  puedeLeerClientesMembresias,
} from '../app/utils/clientes-membresias.ts'

const WEB_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')

function leerWeb(...partes: string[]): string {
  return readFileSync(join(WEB_ROOT, ...partes), 'utf8')
}

test('las capacidades del modulo son owner-only y no filtran roles operadores', () => {
  assert.equal(puedeLeerClientesMembresias('OWNER'), true)
  assert.equal(puedeLeerClientesMembresias('OPERADOR'), false)
  assert.equal(puedeLeerClientesMembresias(null), false)
  assert.equal(puedeLeerClientesMembresias(undefined), false)
})

test('la lista pagina desde uno y formatea precio y estados de Stripe', () => {
  assert.equal(obtenerPaginaSolicitadaClientes('3'), 3)
  assert.equal(obtenerPaginaSolicitadaClientes('0'), 1)
  assert.equal(obtenerPaginaSolicitadaClientes(['2']), 1)
  assert.match(formatearPrecioMembresia(39_900, 'mxn'), /399/)
  assert.equal(etiquetaEstadoMembresia('cancelacion_programada'), 'Cancelación programada')
  assert.equal(etiquetaEstadoMembresia('pago_vencido'), 'Pago vencido')
  assert.equal(formatearFechaMembresia(null), 'Sin fecha programada')
  assert.equal(formatearFechaMembresia('fecha inválida'), 'Sin fecha programada')
})

test('el admin mantiene SSR, paginación y detalle en un modal accesible', () => {
  const pagina = leerWeb('app', 'pages', 'admin', 'clientes', 'index.vue')
  const composable = leerWeb('app', 'composables', 'useClientesMembresias.ts')
  const layout = leerWeb('app', 'layouts', 'admin.vue')

  assert.match(pagina, /layout: 'admin'/)
  assert.match(pagina, /middleware: 'sesion-owner'/)
  assert.match(pagina, /await useAsyncData<ResultadoCarga>/)
  assert.match(pagina, /watch: \[paginaSolicitada, filtroEstado\]/)
  assert.match(pagina, /<dialog[\s\S]*aria-labelledby="detail-title"/)
  assert.match(pagina, /showModal\(\)/)
  assert.match(pagina, /Anterior[\s\S]*Siguiente/)
  assert.match(pagina, /Próxima renovación/)
  assert.match(composable, /useRequestFetch\(\)/)
  assert.match(composable, /cache: 'no-store'/)
  assert.match(layout, /v-if="puedeConsultarClientes"/)
  assert.match(layout, /to="\/admin\/clientes"/)
})

test('las vistas y respuestas BFF de clientes no exponen correo ni ids de Stripe', () => {
  const respuestaMembresia = leerWeb('server', 'api', 'clientes', 'membresia.get.ts')
  const types = leerWeb('app', 'utils', 'clientes-membresias.ts')
  const adminPage = leerWeb('app', 'pages', 'admin', 'clientes', 'index.vue')

  assert.match(respuestaMembresia, /return validarRespuestaMembresia\(respuesta\)/)
  assert.doesNotMatch(respuestaMembresia, /stripe_customer_id|stripe_subscription_id|stripe_price_id/)
  assert.doesNotMatch(types, /correo|stripe_customer|stripe_subscription|price_id/)
  assert.doesNotMatch(adminPage, /correo|stripe_customer|stripe_subscription|price_id/i)
})

test('BFF exige origen y schema allowlist para iniciar Checkout', () => {
  const proxy = leerWeb('server', 'utils', 'proxy-membresias.ts')
  const proxyClientes = leerWeb('server', 'utils', 'proxy-clientes.ts')
  const proxyAdmin = leerWeb('server', 'utils', 'proxy-admin-clientes.ts')
  const purchasePage = leerWeb('app', 'pages', 'cliente', 'membresias.vue')

  assert.match(proxy, /exigirOrigen: true/)
  assert.match(proxy, /incluirSesion: true/)
  assert.match(proxy, /leerObjetoJsonCliente\(event, \['plan_id'\]\)/)
  assert.match(proxyClientes, /function exigirOrigenMismoSitio/)
  assert.match(proxyClientes, /camposRequeridos\.some\(\(clave\) => !Object\.hasOwn\(cuerpo, clave\)\)/)
  assert.match(proxyClientes, /claves\.some\(\(clave\) => !camposPermitidos\.includes\(clave\)\)/)
  assert.match(proxy, /plan_id !== 'mensual'/)
  assert.match(proxy, /idempotency-key/)
  assert.match(proxyClientes, /const NOMBRE_COOKIE_CLIENTE = 'smart_parking_customer_session'/)
  assert.match(proxyClientes, /encabezados\.set\('cookie', cookieCliente\)/)
  assert.doesNotMatch(proxyClientes, /getCookie\(event, useRuntimeConfig\(event\)\.sessionCookieName/)
  assert.match(proxyAdmin, /encabezadosSesion/)
  assert.match(proxy, /incluirSesion: true,[\s\S]*?exigirOrigen: true/)
  assert.match(purchasePage, /crypto\.randomUUID\(\)/)
  assert.match(purchasePage, /hostname !== 'checkout\.stripe\.com'/)
  assert.match(proxyAdmin, /FILTROS_ESTADO = new Set\(\['sin_membresia', 'activa', 'cancelada'\]\)/)
  assert.match(proxyAdmin, /query\.set\('estado', estado\)/)
})

test('la pantalla de retorno no concede acceso según query ni confirma una compra', () => {
  const resultPage = leerWeb('app', 'pages', 'membresias', 'resultado.vue')
  assert.match(resultPage, /no confirma una membresía/i)
  assert.match(resultPage, /to="\/cliente\/membresias"/)
  assert.doesNotMatch(resultPage, /consultarEstadoCheckout|session_id|useRoute\(\)|registrarCliente/i)
  assert.doesNotMatch(resultPage, /crearCheckout|registrarCliente|correo|stripe_customer/i)
})
