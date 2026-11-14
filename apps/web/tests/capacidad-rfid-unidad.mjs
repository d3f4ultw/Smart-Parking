import assert from 'node:assert/strict'
import { readFile, readdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { delay, evaluarTypescript } from './soporte-historial-accesos.mjs'

const require = createRequire(import.meta.url)
const paquetes = await readdir(new URL('../node_modules/.pnpm/', import.meta.url))
const vue = require(fileURLToPath(new URL(`../node_modules/.pnpm/${paquetes.find((p) => p.startsWith('vue@'))}/node_modules/vue`, import.meta.url)))
const { computed, effectScope, getCurrentScope, onScopeDispose, reactive, ref, watch } = vue

const fuenteApi = await readFile(new URL('../app/utils/capacidad-rfid-api.ts', import.meta.url), 'utf8')
const fuenteSalidaManual = await readFile(new URL('../app/utils/salida-manual-api.ts', import.meta.url), 'utf8')
const moduloSalidaManual = evaluarTypescript(fuenteSalidaManual, { '~/utils/api': {} })
let respuestaApi
let falloApi
const peticionesApi = []
const moduloApi = evaluarTypescript(fuenteApi.replaceAll('import.meta.server', 'false'), { h3: {}, '~/utils/salida-manual-api': moduloSalidaManual }, {
  useRequestFetch: () => async (ruta, opciones) => {
    peticionesApi.push({ ruta, opciones })
    if (falloApi) throw falloApi
    return respuestaApi
  },
})
const cliente = moduloApi.useClienteAccesos()
const signal = new AbortController().signal
respuestaApi = { capacidadTotal: 5, vehiculosDentro: 3, capacidadDisponible: 2, cursorEventos: 'epoch:7', uid: 'DATO_PRIVADO' }
const capacidad = await cliente.capacidad(signal)
assert.deepEqual(capacidad, { capacidadTotal: 5, vehiculosDentro: 3, capacidadDisponible: 2, cursorEventos: 'epoch:7' })
assert.doesNotMatch(JSON.stringify(capacidad), /DATO_PRIVADO|uid/)
respuestaApi = { ...respuestaApi, capacidadDisponible: 3 }
await assert.rejects(cliente.capacidad(signal), (e) => e.estado === 503)
respuestaApi = { capacidadTotal: 5, vehiculosDentro: 7, capacidadDisponible: 0, cursorEventos: null }
assert.equal((await cliente.capacidad(signal)).capacidadDisponible, 0)
respuestaApi = { ...respuestaApi, vehiculosDentro: -1 }
await assert.rejects(cliente.capacidad(signal), (e) => e.estado === 503)
respuestaApi = {
  items: [{ movimientoId: '8', persona: { tipo: 'CLIENTE', nombre: 'Persona sintética', codigo: 'CLI-0001', uid: 'DATO_PRIVADO' }, estadoTarjeta: 'CANCELADA', entradaEn: '2026-11-10T12:00:00Z', entradaEnLocal: '2026-11-10T06:00:00-06:00', salidaManual: null, uid: 'DATO_PRIVADO' }],
  pagina: 2, tamano: 10, totalRegistros: 11, haySiguiente: false, zonaHoraria: 'America/Mexico_City', cursorEventos: 'epoch:8', uid: 'DATO_PRIVADO',
}
const dentro = await cliente.dentro(2, 'CLI-0001', signal)
assert.deepEqual(peticionesApi.at(-1).opciones.query, { pagina: '2', busqueda: 'CLI-0001' })
assert.deepEqual(dentro.items[0], { movimientoId: '8', persona: { tipo: 'CLIENTE', nombre: 'Persona sintética', codigo: 'CLI-0001' }, estadoTarjeta: 'CANCELADA', entradaEn: '2026-11-10T12:00:00Z', entradaEnLocal: '2026-11-10T06:00:00-06:00', salidaManual: null })
assert.doesNotMatch(JSON.stringify(dentro), /DATO_PRIVADO|uid/)
respuestaApi.items[0].estadoTarjeta = 'DESCONOCIDA'
await assert.rejects(cliente.dentro(2, '', signal), (e) => e.estado === 503)
falloApi = { statusCode: 403, message: 'información no confiable' }
await assert.rejects(cliente.capacidad(signal), (e) => e.estado === 403 && !e.message.includes('información no confiable'))
falloApi = null

const fuenteConsulta = await readFile(new URL('../app/composables/useConsultaAccesos.ts', import.meta.url), 'utf8')
const fuenteCapacidad = await readFile(new URL('../app/composables/useCapacidadRfid.ts', import.meta.url), 'utf8')

function diferida() {
  let resolver
  const promesa = new Promise((resolve) => { resolver = resolve })
  return { promesa, resolver }
}

function superficie() {
  const escuchas = new Map()
  return {
    addEventListener(nombre, reaccion) {
      const lista = escuchas.get(nombre) ?? new Set()
      lista.add(reaccion)
      escuchas.set(nombre, lista)
    },
    removeEventListener(nombre, reaccion) { escuchas.get(nombre)?.delete(reaccion) },
    emitir(nombre) { for (const reaccion of escuchas.get(nombre) ?? []) reaccion() },
    cantidad() { return [...escuchas.values()].reduce((total, lista) => total + lista.size, 0) },
  }
}

function crearEntorno() {
  const document = Object.assign(superficie(), { visibilityState: 'visible' })
  const window = superficie()
  const navigator = { onLine: true }
  const suscripciones = new Set()
  const recursos = new Map()
  const montajes = []
  let limpiezasSesion = 0
  let navegaciones = 0
  const eventos = {
    suscribir(reaccion, cursor, nombre, cobertura, conexion) {
      const suscripcion = { reaccion, cursor, nombre, conexion }
      suscripciones.add(suscripcion)
      cobertura(false)
      return () => suscripciones.delete(suscripcion)
    },
  }
  const globales = {
    useNuxtApp: () => ({ $eventosAdministracion: eventos }),
    useSesion: () => ({ limpiar: async () => { limpiezasSesion += 1 } }),
    navigateTo: async () => { navegaciones += 1 },
    document, window, navigator, DOMException,
    useAsyncData: async (clave, handler, opciones) => {
      if (recursos.has(clave)) return recursos.get(clave)
      const data = ref(opciones.default())
      const pending = ref(false)
      let version = 0
      let controlador
      async function refresh() {
        if (pending.value) return
        const actual = ++version
        controlador = new AbortController()
        const signal = controlador.signal
        pending.value = true
        try {
          const resultado = await handler({}, { signal })
          if (actual === version && !signal.aborted) data.value = resultado
        } catch (fallo) {
          if (!signal.aborted && !(fallo instanceof DOMException && fallo.name === 'AbortError')) throw fallo
        } finally {
          if (actual === version) pending.value = false
        }
      }
      const recurso = {
        data, pending, refresh,
        clear() { version += 1; controlador?.abort(); data.value = opciones.default(); pending.value = false },
      }
      recursos.set(clave, recurso)
      if (opciones.immediate) await refresh()
      return recurso
    },
  }
  const modulo = evaluarTypescript(fuenteConsulta.replaceAll('import.meta.client', 'true'), {
    vue: { computed, getCurrentScope, onMounted: (fn) => montajes.push(fn), onScopeDispose, ref, watch },
    '~/utils/capacidad-rfid-api': { ErrorAccesosApi: moduloApi.ErrorAccesosApi },
  }, globales)
  return {
    document, window, navigator, suscripciones, recursos,
    get limpiezasSesion() { return limpiezasSesion },
    get navegaciones() { return navegaciones },
    async crear(opciones) {
      const scope = effectScope()
      const consulta = await scope.run(() => modulo.useConsultaAccesos(opciones))
      for (const montar of montajes.splice(0)) montar()
      await delay(0)
      return { consulta, scope }
    },
    emitir(nombre) { for (const sub of [...suscripciones]) if (sub.nombre === nombre) sub.reaccion() },
    interrumpir() { for (const sub of [...suscripciones]) sub.conexion.interrumpida() },
    recuperar() { for (const sub of [...suscripciones]) sub.conexion.recuperada() },
  }
}

const entorno = crearEntorno()
const identidad = ref('DUENO:ejemplo')
let solicitudes = 0
let siguiente
const opciones = {
  clave: 'capacidad:/admin', criterio: computed(() => identidad.value), inmediata: true,
  temas: ['acceso.historial.actualizado', 'vision.ocupacion.actualizada'],
  consultar: async () => {
    solicitudes += 1
    if (siguiente) { const actual = siguiente; siguiente = null; return actual.promesa }
    return { cursorEventos: 'epoch:12', valor: solicitudes }
  },
}
const { consulta, scope } = await entorno.crear(opciones)
assert.equal(consulta.datos.value.valor, 1)
assert.equal(entorno.suscripciones.size, 2)
assert.ok([...entorno.suscripciones].every((sub) => sub.cursor === 'epoch:12'))
for (let i = 0; i < 5; i += 1) entorno.emitir('acceso.historial.actualizado')
entorno.emitir('vision.ocupacion.actualizada')
assert.equal(consulta.desactualizado.value, true)
await delay(150)
assert.equal(solicitudes, 2, 'Las invalidaciones simultáneas se agrupan en una consulta.')
assert.equal(consulta.desactualizado.value, false)

entorno.interrumpir()
assert.equal(consulta.desactualizado.value, true)
await consulta.actualizar()
assert.equal(consulta.desactualizado.value, true, 'Una lectura HTTP durante el corte no declara recuperado el stream.')
entorno.recuperar()
await delay(150)
assert.equal(consulta.desactualizado.value, false, 'La recuperación SSE reconcilia el snapshot.')

const demorada = diferida()
siguiente = demorada
const pendiente = consulta.actualizar()
entorno.navigator.onLine = false
entorno.window.emitir('offline')
assert.equal(consulta.desactualizado.value, true)
demorada.resolver({ cursorEventos: 'epoch:12', valor: -1 })
await pendiente
await delay(0)
assert.equal(consulta.desactualizado.value, true, 'Una respuesta iniciada antes del corte no restaura vigencia.')
const antesRetorno = solicitudes
entorno.navigator.onLine = true
entorno.window.emitir('online')
await delay(150)
assert.equal(solicitudes, antesRetorno + 1)
assert.equal(consulta.desactualizado.value, false)

entorno.document.visibilityState = 'hidden'
entorno.document.emitir('visibilitychange')
assert.equal(consulta.desactualizado.value, true)
const antesVisible = solicitudes
entorno.document.visibilityState = 'visible'
entorno.document.emitir('visibilitychange')
await delay(150)
assert.equal(solicitudes, antesVisible + 1)
assert.equal(consulta.desactualizado.value, false)

const antigua = diferida()
siguiente = antigua
const peticionAntigua = consulta.actualizar()
identidad.value = 'OPERADOR:otro'
await delay(0)
assert.equal(consulta.datos.value.valor, solicitudes, 'El cambio de identidad vuelve a consultar.')
antigua.resolver({ cursorEventos: 'epoch:1', valor: -10 })
await peticionAntigua
await delay(0)
assert.notEqual(consulta.datos.value.valor, -10, 'Una respuesta obsoleta no cruza sesiones.')
identidad.value = null
assert.equal(consulta.datos.value, null)
assert.equal(entorno.suscripciones.size, 0)
scope.stop()
assert.equal(entorno.document.cantidad(), 0)
assert.equal(entorno.window.cantidad(), 0)

const rutas = []
let rutaActual = '/admin'
const moduloCapacidad = evaluarTypescript(fuenteCapacidad, {
  vue: { computed },
  '~/utils/capacidad-rfid-api': { useClienteAccesos: () => ({ capacidad: async () => ({}) }) },
}, {
  useRoute: () => ({ path: rutaActual }),
  useSesion: () => ({ sesion: ref({ estado: 'autenticada', identidad: { rol: 'DUENO', correo: 'ejemplo' } }) }),
  useConsultaAccesos: (opcion) => { rutas.push(opcion.clave); return opcion },
})
moduloCapacidad.useCapacidadRfid()
rutaActual = '/admin/vision'
moduloCapacidad.useCapacidadRfid()
assert.notEqual(rutas[0], rutas[1], 'Cada página tiene su propio recurso y cleanup.')
const entornoRutas = crearEntorno()
const uno = await entornoRutas.crear({ ...opciones, clave: rutas[0], criterio: computed(() => 'DUENO:ejemplo') })
const dos = await entornoRutas.crear({ ...opciones, clave: rutas[1], criterio: computed(() => 'DUENO:ejemplo') })
const valorSegundo = dos.consulta.datos.value
uno.scope.stop()
assert.deepEqual(dos.consulta.datos.value, valorSegundo, 'Desmontar la primera página no borra la segunda.')
dos.scope.stop()

const entornoTarjetas = crearEntorno()
let lecturasTarjetas = 0
const tarjetas = await entornoTarjetas.crear({
  clave: 'dentro', criterio: computed(() => 'OPERADOR:ejemplo:1'), inmediata: false,
  temas: ['acceso.historial.actualizado', 'rfid1.tarjetas.actualizadas'],
  consultar: async () => { lecturasTarjetas += 1; return { cursorEventos: 'epoch:1' } },
})
assert.equal(lecturasTarjetas, 1)
entornoTarjetas.emitir('rfid1.tarjetas.actualizadas')
await delay(150)
assert.equal(lecturasTarjetas, 2, 'Una cancelación de tarjeta invalida la lista de entradas.')
tarjetas.scope.stop()

const entornoBusqueda = crearEntorno()
const filtroBusqueda = ref({ pagina: 2, busqueda: 'anterior' })
let retrasarBusqueda = false
let signalAnterior
const respuestaAnterior = diferida()
const consultaBusqueda = await entornoBusqueda.crear({
  clave: 'dentro-busqueda',
  criterio: computed(() => JSON.stringify(filtroBusqueda.value)),
  inmediata: true,
  temas: ['acceso.historial.actualizado', 'rfid1.tarjetas.actualizadas'],
  consultar: async (signal) => {
    const filtro = { ...filtroBusqueda.value }
    if (retrasarBusqueda) {
      retrasarBusqueda = false
      signalAnterior = signal
      return respuestaAnterior.promesa
    }
    return { ...filtro, cursorEventos: 'epoch:1' }
  },
})
retrasarBusqueda = true
const solicitudAnterior = consultaBusqueda.consulta.actualizar()
filtroBusqueda.value = { pagina: 1, busqueda: 'E-0001' }
await delay(0)
assert.equal(signalAnterior.aborted, true)
assert.equal(consultaBusqueda.consulta.datos.value.busqueda, 'E-0001')
respuestaAnterior.resolver({ pagina: 2, busqueda: 'anterior', cursorEventos: 'epoch:1' })
await solicitudAnterior
assert.equal(consultaBusqueda.consulta.datos.value.busqueda, 'E-0001', 'La búsqueda anterior no reemplaza la nueva.')
consultaBusqueda.scope.stop()

const fuenteEntradas = await readFile(new URL('../app/composables/useEntradasActivas.ts', import.meta.url), 'utf8')
let opcionesEntradas
const solicitudesEntradas = []
const sesionEntradas = ref({ estado: 'autenticada', identidad: { rol: 'OPERADOR', correo: 'ejemplo' } })
const moduloEntradas = evaluarTypescript(fuenteEntradas, {
  vue: { computed, getCurrentScope, ref, watch },
  '~/utils/capacidad-rfid-api': { useClienteAccesos: () => ({
    dentro: async (pagina, busqueda) => { solicitudesEntradas.push({ pagina, busqueda }); return {} },
  }) },
}, {
  useRoute: () => ({ path: '/operador/accesos' }),
  useSesion: () => ({ sesion: sesionEntradas }),
  useConsultaAccesos: async (opciones) => { opcionesEntradas = opciones; return { datos: ref(null) } },
})
const scopeEntradas = effectScope()
const vistaEntradas = ref('DENTRO')
const entradas = await scopeEntradas.run(() => moduloEntradas.useEntradasActivas(vistaEntradas))
entradas.cambiarPagina(3)
let cambiosCriterio = 0
const pararCriterio = watch(opcionesEntradas.criterio, () => { cambiosCriterio += 1 }, { flush: 'sync' })
entradas.buscar('  CLI-0001  ')
assert.equal(cambiosCriterio, 1, 'Buscar y volver a página 1 constituye un solo cambio de criterio.')
assert.equal(entradas.busqueda.value, 'CLI-0001')
await opcionesEntradas.consultar(signal)
assert.deepEqual(solicitudesEntradas.at(-1), { pagina: 1, busqueda: 'CLI-0001' })
entradas.cambiarPagina(2)
await opcionesEntradas.consultar(signal)
assert.deepEqual(solicitudesEntradas.at(-1), { pagina: 2, busqueda: 'CLI-0001' })
entradas.buscar('')
await opcionesEntradas.consultar(signal)
assert.deepEqual(solicitudesEntradas.at(-1), { pagina: 1, busqueda: '' })
entradas.buscar('Persona sintética')
sesionEntradas.value = { estado: 'anonima', identidad: null }
assert.equal(entradas.busqueda.value, '', 'Al cerrar sesión se limpia el filtro privado.')
assert.equal(opcionesEntradas.criterio.value, null)
vistaEntradas.value = 'HISTORIAL'
assert.equal(opcionesEntradas.criterio.value, null)
pararCriterio()
scopeEntradas.stop()

const entorno403 = crearEntorno()
const acceso403 = await entorno403.crear({
  clave: 'protegido', criterio: computed(() => 'DUENO:ejemplo'), inmediata: true,
  temas: [], consultar: async () => { throw new moduloApi.ErrorAccesosApi(403, 'Sin acceso') },
})
assert.equal(acceso403.consulta.estado.value, 'sin-acceso')
assert.equal(acceso403.consulta.datos.value, null)
assert.equal(entorno403.limpiezasSesion, 0)
acceso403.scope.stop()

const entorno401 = crearEntorno()
const acceso401 = await entorno401.crear({
  clave: 'expirado', criterio: computed(() => 'DUENO:ejemplo'), inmediata: true,
  temas: [], consultar: async () => { throw new moduloApi.ErrorAccesosApi(401, 'Sesión vencida') },
})
assert.equal(acceso401.consulta.estado.value, 'sin-acceso')
assert.equal(acceso401.consulta.datos.value, null)
assert.equal(entorno401.limpiezasSesion, 1)
assert.equal(entorno401.navegaciones, 1)
acceso401.scope.stop()
console.log('PASS: contrato y privacidad, SSE, desconexión, visibilidad, aislamiento de rutas, sesiones y tarjetas.')
