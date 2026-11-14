import assert from 'node:assert/strict'
import { readFile, readdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const dependenciasPnpm = await readdir(new URL('../node_modules/.pnpm/', import.meta.url))
const paqueteVue = dependenciasPnpm.find((nombre) => nombre.startsWith('vue@'))
assert.ok(paqueteVue, 'Vue debe estar disponible como dependencia transitiva de Nuxt.')
const vue = require(
  fileURLToPath(new URL(`../node_modules/.pnpm/${paqueteVue}/node_modules/vue`, import.meta.url)),
)
const { computed, reactive, ref, watch } = vue
const delay = (milisegundos) => new Promise((resolve) => setTimeout(resolve, milisegundos))

function evaluarTypescript(origen, dependencias, globales = {}) {
  const javascript = ts.transpileModule(origen, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const modulo = { exports: {} }
  const cargar = (nombre) => {
    if (Object.hasOwn(dependencias, nombre)) return dependencias[nombre]
    return require(nombre)
  }
  const nombres = Object.keys(globales)
  const valores = Object.values(globales)
  new Function('require', 'module', 'exports', ...nombres, javascript)(
    cargar,
    modulo,
    modulo.exports,
    ...valores,
  )
  return modulo.exports
}

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

class ErrorHistorialAccesosApi extends Error {
  constructor(estado, codigo, mensaje) {
    super(mensaje)
    this.estado = estado
    this.codigo = codigo
  }
}

const fuenteComposable = await readFile(
  new URL('../app/composables/useHistorialAccesos.ts', import.meta.url),
  'utf8',
)

function crearComposable({ consulta, api, eventos = { suscribir: () => () => {} } }) {
  const ruta = reactive({ query: { ...consulta } })
  const router = {
    async push(destino) {
      ruta.query = destino.query
    },
  }
  const sesion = ref({ estado: 'autenticada', identidad: { rol: 'DUENO' } })
  const disposiciones = []
  let datosAsync
  const dependencias = {
    vue: {
      computed,
      getCurrentScope: () => ({ run: (reaccion) => reaccion() }),
      onScopeDispose: (reaccion) => disposiciones.push(reaccion),
      watch,
    },
    '~/utils/accesos-api': {
      ErrorHistorialAccesosApi,
      useClienteHistorialAccesos: () => api,
    },
  }
  const globales = {
    useRoute: () => ruta,
    useRouter: () => router,
    useNuxtApp: () => ({ $eventosAdministracion: eventos }),
    useSesion: () => ({ sesion, limpiar: async () => {} }),
    DOMException,
    document: {
      visibilityState: 'visible',
      addEventListener() {},
      removeEventListener(nombre) {
        if (nombre === 'visibilitychange') eventos.quitados?.push(nombre)
      },
    },
    window: {
      addEventListener() {},
      removeEventListener(nombre) {
        if (nombre === 'focus') eventos.quitados?.push(nombre)
      },
    },
  }
  globales.useAsyncData = (clave, handler, opciones) => {
    const data = ref(opciones.default())
    const pending = ref(false)
    let generacion = 0
    let controlador
    async function refresh() {
      const actual = ++generacion
      controlador?.abort()
      controlador = new AbortController()
      const signal = controlador.signal
      pending.value = true
      try {
        const resultado = await handler({}, { signal })
        if (actual === generacion && !signal.aborted) data.value = resultado
      } catch (fallo) {
        if (!signal.aborted && !(fallo instanceof DOMException && fallo.name === 'AbortError')) {
          throw fallo
        }
      } finally {
        if (actual === generacion) pending.value = false
      }
    }
    watch(opciones.watch, () => void refresh(), { flush: 'sync' })
    void refresh()
    datosAsync = {
      data,
      pending,
      refresh,
      clear() {
        controlador?.abort()
        data.value = opciones.default()
        pending.value = false
      },
    }
    return datosAsync
  }
  const modulo = evaluarTypescript(
    fuenteComposable.replaceAll('import.meta.client', 'true'),
    dependencias,
    globales,
  )
  return {
    ruta,
    disposiciones,
    datosAsync: () => datosAsync,
    historial: modulo.useHistorialAccesos(),
  }
}

function promesaDiferida() {
  let resolver
  const promesa = new Promise((resolve) => (resolver = resolve))
  return { promesa, resolver }
}

const solicitudesAntiguas = []
const diferidas = [promesaDiferida(), promesaDiferida()]
const entornoFiltro = crearComposable({
  consulta: { pagina: '4', lector: 'TODOS', resultado: 'TODOS', conservar: 'valor' },
  api: {
    listar(pagina, lector, resultado, signal) {
      const diferida = diferidas[solicitudesAntiguas.length]
      solicitudesAntiguas.push({ pagina, lector, resultado, signal })
      return diferida.promesa
    },
  },
})
const historialFiltro = await entornoFiltro.historial
await historialFiltro.cambiarLector('RFID3')
assert.equal(entornoFiltro.ruta.query.pagina, undefined, 'Cambiar un filtro reinicia a página 1.')
assert.equal(entornoFiltro.ruta.query.lector, 'RFID3')
assert.equal(
  entornoFiltro.ruta.query.conservar,
  'valor',
  'Se conservan los parámetros ajenos al módulo.',
)
assert.deepEqual(
  solicitudesAntiguas.map(({ pagina, lector, resultado }) => ({ pagina, lector, resultado })),
  [
    { pagina: '4', lector: 'TODOS', resultado: 'TODOS' },
    { pagina: '1', lector: 'RFID3', resultado: 'TODOS' },
  ],
)
assert.equal(
  solicitudesAntiguas[0].signal.aborted,
  true,
  'La consulta anterior se cancela al cambiar filtro.',
)
const paginaNueva = {
  items: [{ id: 2 }],
  pagina: 1,
  tamano: 50,
  haySiguiente: false,
  zonaHoraria: 'UTC',
  cursorEventos: 'epoch-web:30',
}
diferidas[1].resolver(paginaNueva)
await delay(0)
diferidas[0].resolver({ ...paginaNueva, items: [{ id: 1 }], pagina: 4 })
await delay(0)
assert.equal(
  historialFiltro.eventosAcceso.value[0].id,
  2,
  'Una respuesta HTTP vieja no reemplaza al filtro nuevo.',
)
for (const reaccion of entornoFiltro.disposiciones) reaccion()

const solicitudInicial = promesaDiferida()
const solicitudesCoalescidas = []
const quitados = []
let invalidar
let vecesDesuscrito = 0
const entornoSse = crearComposable({
  consulta: { pagina: '1', lector: 'TODOS', resultado: 'TODOS' },
  api: {
    listar(pagina, lector, resultado) {
      if (!solicitudesCoalescidas.length) {
        solicitudesCoalescidas.push({ pagina, lector, resultado })
        return solicitudInicial.promesa
      }
      solicitudesCoalescidas.push({ pagina, lector, resultado })
      return Promise.resolve({
        items: [],
        pagina: 1,
        tamano: 50,
        haySiguiente: false,
        zonaHoraria: 'UTC',
        cursorEventos: 'epoch-web:31',
      })
    },
  },
  eventos: {
    quitados,
    suscribir(reaccion, cursor, nombre, cobertura) {
      assert.equal(
        cursor,
        'epoch-web:29',
        'El composable entrega el cursor del snapshot SSR al stream.',
      )
      assert.equal(nombre, 'acceso.historial.actualizado')
      cobertura(false)
      invalidar = reaccion
      return () => (vecesDesuscrito += 1)
    },
  },
})
const historialSse = await entornoSse.historial
entornoSse.datosAsync().data.value = {
  estado: 'listo',
  datos: {
    items: [],
    pagina: 1,
    tamano: 50,
    haySiguiente: false,
    zonaHoraria: 'UTC',
    cursorEventos: 'epoch-web:29',
  },
}
historialSse.iniciarEventos()
for (let indice = 0; indice < 8; indice += 1) invalidar()
await delay(120)
assert.equal(
  solicitudesCoalescidas.length,
  1,
  'Invalidaciones durante una respuesta pendiente se agrupan.',
)
solicitudInicial.resolver({
  items: [],
  pagina: 1,
  tamano: 50,
  haySiguiente: false,
  zonaHoraria: 'UTC',
  cursorEventos: 'epoch-web:30',
})
await delay(180)
assert.equal(
  solicitudesCoalescidas.length,
  2,
  'Ocho invalidaciones producen solo una reconsulta adicional.',
)
invalidar()
for (const reaccion of entornoSse.disposiciones) reaccion()
await delay(140)
assert.equal(
  solicitudesCoalescidas.length,
  2,
  'El cleanup cancela el timer de reconsulta pendiente.',
)
assert.equal(vecesDesuscrito, 1, 'El dispose libera la suscripción SSE.')
assert.deepEqual(
  quitados.sort(),
  ['focus', 'visibilitychange'],
  'El dispose elimina listeners de foco y visibilidad.',
)

console.log(
  'PASS: stream compartido, cursor/gap/resync, coalescencia, filtro nuevo, respuesta vieja y cleanup.',
)
