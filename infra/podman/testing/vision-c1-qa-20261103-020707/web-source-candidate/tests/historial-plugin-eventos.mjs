import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { evaluarTypescript, ref, watch } from './soporte-historial-accesos.mjs'

class EventSourceFalso {
  constructor(url) {
    this.url = url
    this.cerrado = false
    this.escuchas = new Map()
    EventSourceFalso.instancias.push(this)
  }

  addEventListener(nombre, reaccion) {
    const lista = this.escuchas.get(nombre) ?? []
    lista.push(reaccion)
    this.escuchas.set(nombre, lista)
  }

  emitir(nombre, lastEventId, data = '') {
    for (const reaccion of this.escuchas.get(nombre) ?? []) {
      reaccion({ type: nombre, lastEventId, data })
    }
  }

  close() {
    this.cerrado = true
  }
}
EventSourceFalso.instancias = []

const fuentePlugin = await readFile(
  new URL('../app/plugins/eventos-administracion.client.ts', import.meta.url),
  'utf8',
)
const sesionPlugin = ref({ estado: 'autenticada', identidad: { rol: 'DUENO' } })
let resolverCsrf
let solicitudesAck = 0
const plugin = evaluarTypescript(
  fuentePlugin,
  { vue: { watch } },
  {
    defineNuxtPlugin: (inicializar) => inicializar(),
    useSesion: () => ({ sesion: sesionPlugin, actualizar: async () => {} }),
    useRoute: () => ({ path: '/admin/accesos' }),
    useCsrf: () => ({
      obtener: () =>
        new Promise((resolver) => {
          resolverCsrf = resolver
        }),
    }),
    EventSource: EventSourceFalso,
    fetch: async () => {
      solicitudesAck += 1
      return { status: 204 }
    },
    navigateTo: async () => {},
  },
).default
const eventosCompartidos = plugin.provide.eventosAdministracion
let coberturaInicial
let coberturaMismoSnapshot
let coberturaDistinta
let coberturaTrasHueco
let coberturaCursorAntiguo
const reacciones = []
const desuscribir = eventosCompartidos.suscribir(
  () => reacciones.push('primera'),
  'epoch-web:20',
  'acceso.historial.actualizado',
  (requiere) => (coberturaInicial = requiere),
)
assert.equal(EventSourceFalso.instancias.length, 1, 'La primera suscripción abre un stream.')
assert.equal(
  new URL(EventSourceFalso.instancias[0].url, 'http://localhost').searchParams.get('despues'),
  'epoch-web:20',
  'El stream reanuda desde el snapshot.',
)
assert.equal(coberturaInicial, false)
const desuscribirSegunda = eventosCompartidos.suscribir(
  () => reacciones.push('segunda'),
  'epoch-web:20',
  'acceso.historial.actualizado',
  (requiere) => (coberturaMismoSnapshot = requiere),
)
assert.equal(EventSourceFalso.instancias.length, 1, 'Ambas suscripciones comparten EventSource.')
assert.equal(coberturaMismoSnapshot, false, 'El replay cubre el mismo snapshot antes de eventos.')
const desuscribirDistinta = eventosCompartidos.suscribir(
  () => reacciones.push('snapshot-distinto'),
  'epoch-web:21',
  'acceso.historial.actualizado',
  (requiere) => (coberturaDistinta = requiere),
)
assert.equal(coberturaDistinta, true, 'Un snapshot distinto requiere reconciliación.')
const stream = EventSourceFalso.instancias[0]
let eventosVision = 0
const desuscribirVision = eventosCompartidos.suscribir(
  () => {
    eventosVision += 1
  },
  'epoch-web:20',
  'vision.ocupacion.actualizada',
)
assert.equal(EventSourceFalso.instancias.length, 1, 'Vision comparte el mismo EventSource.')
stream.emitir('vision.ocupacion.actualizada', 'epoch-web:21')
assert.equal(eventosVision, 1)
stream.emitir('acceso.historial.actualizado', 'epoch-web:21')
const desuscribirCursorAntiguo = eventosCompartidos.suscribir(
  () => {},
  'epoch-web:20',
  'acceso.historial.actualizado',
  (requiere) => (coberturaCursorAntiguo = requiere),
)
assert.equal(coberturaCursorAntiguo, true, 'C1 no cubre una página SSR que tomó C0.')
assert.equal(reacciones.length, 3, 'La invalidación de acceso despierta a todos los suscriptores.')
stream.emitir('administracion.directorio.resincronizar', 'epoch-web:22')
assert.equal(reacciones.length, 6, 'La señal de hueco resincroniza todos los directorios.')
assert.equal(eventosVision, 2, 'Un hueco también invalida Vision.')
const desuscribirTrasHueco = eventosCompartidos.suscribir(
  () => reacciones.push('suscriptor-posterior-al-hueco'),
  'epoch-web:20',
  'acceso.historial.actualizado',
  (requiere) => (coberturaTrasHueco = requiere),
)
assert.equal(coberturaTrasHueco, true, 'Un snapshot anterior al hueco debe reconciliarse.')
stream.emitir(
  'empleado.heartbeat',
  '',
  JSON.stringify({
    suscripcionId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    secuencia: 1,
  }),
)
desuscribir()
desuscribirSegunda()
desuscribirDistinta()
desuscribirCursorAntiguo()
desuscribirVision()
assert.equal(stream.cerrado, false, 'El stream sigue abierto mientras queda otra suscripción.')
assert.equal(reacciones.length, 6)
desuscribirTrasHueco()
assert.equal(stream.cerrado, true, 'El stream se cierra al liberar la última suscripción.')
resolverCsrf('csrf-sintetico')
await Promise.resolve()
await Promise.resolve()
assert.equal(solicitudesAck, 0, 'Un ACK atrasado no se envía después del cierre.')
stream.emitir('vision.ocupacion.actualizada', 'epoch-web:23')
assert.equal(eventosVision, 2, 'Un evento atrasado de un stream cerrado se ignora.')
