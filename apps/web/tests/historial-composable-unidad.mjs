import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import {
  computed,
  reactive,
  ref,
  watch,
  delay,
  evaluarTypescript,
} from './soporte-historial-accesos.mjs'

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
  const ruta = reactive({ path: '/admin/accesos', query: { ...consulta } })
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
    listar(pagina, lector, resultado, periodo, desde, hasta, signal) {
      const diferida = diferidas[solicitudesAntiguas.length]
      solicitudesAntiguas.push({ pagina, lector, resultado, periodo, desde, hasta, signal })
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
  solicitudesAntiguas.map(({ pagina, lector, resultado, periodo }) => ({ pagina, lector, resultado, periodo })),
  [
    { pagina: '4', lector: 'TODOS', resultado: 'TODOS', periodo: 'ULTIMOS_7_DIAS' },
    { pagina: '1', lector: 'RFID3', resultado: 'TODOS', periodo: 'ULTIMOS_7_DIAS' },
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
  tamano: 10,
  totalRegistros: 1,
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

const consultasConRango = []
const entornoRango = crearComposable({
  consulta: {
    pagina: '3',
    lector: 'RFID2',
    resultado: 'DENEGADA',
    periodo: 'TODO',
    conservar: 'valor',
  },
  api: {
    listar(pagina, lector, resultado, periodo, desde, hasta) {
      consultasConRango.push({ pagina, lector, resultado, periodo, desde, hasta })
      return Promise.resolve({
        items: [],
        pagina: Number(pagina),
        tamano: 10,
        totalRegistros: 75,
        haySiguiente: true,
        zonaHoraria: 'America/Mexico_City',
        cursorEventos: 'epoch-web:32',
      })
    },
  },
})
const historialRango = await entornoRango.historial
await historialRango.cambiarRango('2026-11-01', '2026-11-07')
assert.equal(entornoRango.ruta.query.pagina, undefined, 'Aplicar un rango vuelve a página 1.')
assert.equal(entornoRango.ruta.query.periodo, 'PERSONALIZADO')
assert.equal(entornoRango.ruta.query.desde, '2026-11-01')
assert.equal(entornoRango.ruta.query.hasta, '2026-11-07')
assert.equal(entornoRango.ruta.query.conservar, 'valor')
await delay(0)
assert.deepEqual(consultasConRango.at(-1), {
  pagina: '1',
  lector: 'RFID2',
  resultado: 'DENEGADA',
  periodo: 'PERSONALIZADO',
  desde: '2026-11-01',
  hasta: '2026-11-07',
})
await historialRango.cambiarPagina(6)
assert.equal(entornoRango.ruta.query.pagina, '6')
assert.equal(entornoRango.ruta.query.desde, '2026-11-01', 'Cambiar de página conserva el rango.')
await historialRango.limpiarFiltros()
assert.deepEqual(entornoRango.ruta.query, { conservar: 'valor' }, 'Limpiar vuelve al periodo predeterminado.')
for (const reaccion of entornoRango.disposiciones) reaccion()

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
        tamano: 10,
        totalRegistros: 0,
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
    tamano: 10,
    totalRegistros: 0,
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
    tamano: 10,
    totalRegistros: 0,
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
