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
  assert.match(pagina, /watch: \[paginaSolicitada\]/)
  assert.match(pagina, /<dialog[\s\S]*aria-labelledby="detail-title"/)
  assert.match(pagina, /showModal\(\)/)
  assert.match(pagina, /Anterior[\s\S]*Siguiente/)
  assert.match(pagina, /Próxima renovación/)
  assert.match(composable, /useRequestFetch\(\)/)
  assert.match(composable, /cache: 'no-store'/)
  assert.match(layout, /v-if="puedeConsultarClientes"/)
  assert.match(layout, /to="\/admin\/clientes"/)
})

test('ninguna respuesta o vista de clientes expone correo ni ids de Stripe', () => {
  const apiSchemas = readFileSync(
    join(WEB_ROOT, '..', 'api', 'app', 'esquemas', 'clientes_membresias.py'),
    'utf8',
  )
  const types = leerWeb('app', 'utils', 'clientes-membresias.ts')
  const adminPage = leerWeb('app', 'pages', 'admin', 'clientes', 'index.vue')

  assert.doesNotMatch(apiSchemas, /correo_privado|stripe_customer_id|stripe_subscription_id|stripe_price_id/)
  assert.doesNotMatch(types, /correo|stripe_customer|stripe_subscription|price_id/)
  assert.doesNotMatch(adminPage, /correo|stripe_customer|stripe_subscription|price_id/i)
})

test('BFF exige origen y schema allowlist para iniciar Checkout', () => {
  const proxy = leerWeb('server', 'utils', 'proxy-membresias.ts')
  const proxyAdmin = leerWeb('server', 'utils', 'proxy-admin-clientes.ts')
  const purchasePage = leerWeb('app', 'pages', 'membresias', 'index.vue')

  assert.match(proxy, /exigirOrigenMismoSitio/)
  assert.match(proxy, /Object\.keys\(body\)\.length !== 1/)
  assert.match(proxy, /plan_id !== 'mensual'/)
  assert.match(proxy, /idempotency-key/)
  assert.doesNotMatch(proxy, /encabezadosSesion/)
  assert.match(proxyAdmin, /encabezadosSesion/)
  assert.match(purchasePage, /crypto\.randomUUID\(\)/)
  assert.match(purchasePage, /hostname !== 'checkout\.stripe\.com'/)
})

test('la pantalla de retorno no afirma éxito antes del webhook confirmado', () => {
  const resultPage = leerWeb('app', 'pages', 'membresias', 'resultado.vue')
  assert.match(resultPage, /consultarEstadoCheckout/)
  assert.match(resultPage, /estado\.value === 'confirmado'/)
  assert.match(resultPage, /registro se completa únicamente después/)
  assert.doesNotMatch(resultPage, /crearCheckout|registrarCliente|correo|stripe_customer/i)
})
