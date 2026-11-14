import assert from 'node:assert/strict'
import { readFile, readdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const paquetes = await readdir(new URL('../node_modules/.pnpm/', import.meta.url))
const paqueteVue = paquetes.find((nombre) => nombre.startsWith('vue@'))
assert.ok(paqueteVue, 'Vue debe estar disponible para las pruebas de estado.')
const { computed, reactive, ref, watch } = require(
  fileURLToPath(new URL(`../node_modules/.pnpm/${paqueteVue}/node_modules/vue`, import.meta.url)),
)

const fuente = await readFile(
  new URL('../app/composables/useOcupacionVision.ts', import.meta.url),
  'utf8',
)
const codigo = ts.transpileModule(fuente.replaceAll('import.meta.client', 'true'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText

class ErrorVisionApi extends Error {
  constructor(estado) {
    super('Error sintético')
    this.estado = estado
    this.codigo = null
  }
}

class Reloj {
  tiempo = 0
  siguiente = 0
  tareas = new Map()

  programar(reaccion, retraso) {
    const id = ++this.siguiente
    this.tareas.set(id, { en: this.tiempo + retraso, reaccion })
    return id
  }

  cancelar(id) {
    this.tareas.delete(id)
  }

  proximoRetraso() {
    const tiempos = [...this.tareas.values()].map((tarea) => tarea.en)
    return tiempos.length ? Math.min(...tiempos) - this.tiempo : null
  }

  async avanzar(milisegundos) {
    const limite = this.tiempo + milisegundos
    for (;;) {
      const siguiente = [...this.tareas.entries()]
        .filter(([, tarea]) => tarea.en <= limite)
        .sort((a, b) => a[1].en - b[1].en)[0]
      if (!siguiente) break
      const [id, tarea] = siguiente
      this.tiempo = tarea.en
      this.tareas.delete(id)
      tarea.reaccion()
      await vaciarPromesas()
    }
    this.tiempo = limite
    await vaciarPromesas()
  }
}

class Emisor {
  escuchas = new Map()

  addEventListener(nombre, reaccion) {
    const lista = this.escuchas.get(nombre) ?? new Set()
    lista.add(reaccion)
    this.escuchas.set(nombre, lista)
  }

  removeEventListener(nombre, reaccion) {
    this.escuchas.get(nombre)?.delete(reaccion)
  }

  emitir(nombre, evento = { isTrusted: false }) {
    for (const reaccion of this.escuchas.get(nombre) ?? []) reaccion(evento)
  }

  cantidad() {
    return [...this.escuchas.values()].reduce((total, lista) => total + lista.size, 0)
  }
}

async function vaciarPromesas() {
  for (let i = 0; i < 12; i += 1) await Promise.resolve()
}

function diferida() {
  let resolver
  let rechazar
  const promesa = new Promise((resolve, reject) => {
    resolver = resolve
    rechazar = reject
  })
  return { promesa, resolver, rechazar }
}

function cajon(etiqueta, estado = 'LIBRE') {
  return { cajonId: etiqueta, etiqueta, estado, ultimoEstadoConfirmado: estado, observadoEn: null }
}

async function crearEntorno(listar, payload, revalidar = async () => {}) {
  const reloj = new Reloj()
  const documento = new Emisor()
  documento.visibilityState = 'visible'
  const ventana = new Emisor()
  const navegador = { onLine: true }
  const ruta = reactive({ path: '/admin' })
  const sesion = ref({
    estado: 'autenticada',
    identidad: { rol: 'DUENO', correo: 'persona-sintetica@ejemplo.invalid' },
  })
  const montajes = []
  const disposiciones = []
  const navegaciones = []
  const csrf = { presente: true, limpiezas: 0, orden: [] }
  let suscripcion
  let avisosConexion
  const globales = {
    computed,
    ref,
    watch,
    getCurrentScope: () => ({ run: (reaccion) => reaccion() }),
    onMounted: (reaccion) => montajes.push(reaccion),
    onScopeDispose: (reaccion) => disposiciones.push(reaccion),
    useRoute: () => ruta,
    useNuxtApp: () => ({
      $eventosAdministracion: {
        suscribir(reaccion, _cursor, _nombre, cobertura, avisos) {
          suscripcion = reaccion
          avisosConexion = avisos
          cobertura?.(false)
          return () => {
            suscripcion = undefined
            avisosConexion = undefined
          }
        },
      },
    }),
    useSesion: () => ({
      sesion,
      limpiar: () => (sesion.value = { estado: 'anonima', identidad: null }),
      actualizar: () => revalidar(sesion),
    }),
    useCsrf: () => ({
      limpiar: () => {
        csrf.presente = false
        csrf.limpiezas += 1
        csrf.orden.push('limpiar')
      },
    }),
    useAsyncData: async (_clave, manejador, opciones) => {
      const data = ref(payload ?? opciones.default())
      const pending = ref(payload === undefined)
      if (payload === undefined) {
        data.value = await manejador({}, { signal: new AbortController().signal })
        pending.value = false
      }
      return {
        data,
        pending,
        clear() {
          data.value = opciones.default()
          pending.value = false
        },
      }
    },
    navigateTo: async (destino) => {
      navegaciones.push(destino)
      csrf.orden.push('navegar')
    },
    document: documento,
    window: ventana,
    navigator: navegador,
    performance: { now: () => reloj.tiempo },
    setTimeout: (reaccion, retraso) => reloj.programar(reaccion, retraso),
    clearTimeout: (id) => reloj.cancelar(id),
    AbortController,
    DOMException,
  }
  const dependencias = {
    '~/utils/vision-api': {
      ErrorVisionApi,
      useClienteVision: () => ({
        listar: async (signal) => {
          const lectura = await listar(signal)
          return Array.isArray(lectura)
            ? { cajones: lectura, cursor: 'epoca:0', vigenciaRestanteMs: 120_000 }
            : lectura
        },
      }),
    },
  }
  const modulo = { exports: {} }
  const cargar = (nombre) => dependencias[nombre] ?? require(nombre)
  new Function('require', 'module', 'exports', ...Object.keys(globales), codigo)(
    cargar,
    modulo,
    modulo.exports,
    ...Object.values(globales),
  )
  const vision = await modulo.exports.useOcupacionVision()
  return {
    vision,
    reloj,
    documento,
    ventana,
    navegador,
    ruta,
    sesion,
    navegaciones,
    csrf,
    evento: () => suscripcion?.(),
    interrupcion: () => avisosConexion?.interrumpida?.(),
    recuperacion: () => avisosConexion?.recuperada?.(),
    montar: () => montajes.forEach((reaccion) => reaccion()),
    desmontar: () => disposiciones.forEach((reaccion) => reaccion()),
  }
}

// SSR y la hidratación conservan el cursor sin un GET duplicado.
let llamadas = 0
const carga = await crearEntorno(async () => {
  llamadas += 1
  return [cajon('C1')]
})
assert.equal(llamadas, 1)
const payload = {
  estado: 'actual',
  datos: carga.vision.cajones.value,
  ultimaConsulta: carga.vision.ultimaConsulta.value,
  mensaje: '',
  cursor: 'epoca:0',
  vigenciaRestanteMs: 120_000,
  inicioClienteMs: null,
}
const hidratacion = await crearEntorno(async () => {
  llamadas += 1
  return [cajon('C2', 'OCUPADO')]
}, payload)
hidratacion.montar()
await hidratacion.reloj.avanzar(29_999)
assert.equal(llamadas, 1)
await hidratacion.reloj.avanzar(1)
assert.equal(llamadas, 2)
assert.equal(hidratacion.vision.cajones.value[0].etiqueta, 'C2')
hidratacion.desmontar()

// El tablero continúa durante dos minutos sin input y sin sondeo de cinco segundos.
let pasivas = 0
const continuo = await crearEntorno(async () => [cajon(`C${++pasivas}`)])
continuo.montar()
await continuo.reloj.avanzar(120_000)
assert.equal(pasivas, 5)
assert.equal(continuo.vision.estado.value, 'actual')
continuo.desmontar()

// Una ráfaga se agrupa; una invalidación durante la consulta exige otra lectura.
let cambios = 0
const demorada = diferida()
const eventos = await crearEntorno(async () => {
  cambios += 1
  if (cambios === 2) return demorada.promesa
  return [cajon(`C${cambios}`)]
})
eventos.montar()
eventos.evento()
eventos.evento()
await eventos.reloj.avanzar(99)
assert.equal(cambios, 1)
await eventos.reloj.avanzar(1)
assert.equal(cambios, 2)
eventos.evento()
eventos.evento()
demorada.resolver([cajon('C2')])
await vaciarPromesas()
await eventos.reloj.avanzar(100)
assert.equal(cambios, 3)
assert.equal(eventos.vision.cajones.value[0].etiqueta, 'C3')
eventos.interrupcion()
assert.equal(eventos.vision.estado.value, 'historico')
eventos.recuperacion()
await eventos.reloj.avanzar(100)
assert.equal(eventos.vision.estado.value, 'actual')
eventos.desmontar()

// El plazo Java neutraliza la presentación y consulta al servidor; TTL cero no hace un ciclo.
let plazos = 0
const vigencia = await crearEntorno(async () => {
  plazos += 1
  if (plazos === 1) return { cajones: [cajon('C1')], cursor: 'epoca:0', vigenciaRestanteMs: 1000 }
  return { cajones: [cajon('C1', 'NO_VERIFICABLE')], cursor: 'epoca:1', vigenciaRestanteMs: null }
})
vigencia.montar()
await vigencia.reloj.avanzar(1_000)
assert.equal(plazos, 2)
assert.equal(vigencia.vision.cajones.value[0].estado, 'NO_VERIFICABLE')
vigencia.desmontar()

// El deadline se respeta aunque otra lectura siga esperando una respuesta.
let consultasPlazoEnVuelo = 0
const respuestaLenta = diferida()
const plazoEnVuelo = await crearEntorno(async () => {
  consultasPlazoEnVuelo += 1
  if (consultasPlazoEnVuelo === 1) {
    return { cajones: [cajon('ANTERIOR')], cursor: 'epoca:0', vigenciaRestanteMs: 1_000 }
  }
  if (consultasPlazoEnVuelo === 2) return respuestaLenta.promesa
  return {
    cajones: [cajon('ANTERIOR', 'NO_VERIFICABLE')],
    cursor: 'epoca:1',
    vigenciaRestanteMs: null,
  }
})
plazoEnVuelo.montar()
const consultaLenta = plazoEnVuelo.vision.actualizar()
await plazoEnVuelo.reloj.avanzar(999)
assert.equal(plazoEnVuelo.vision.estado.value, 'actual')
await plazoEnVuelo.reloj.avanzar(1)
assert.equal(plazoEnVuelo.vision.estado.value, 'historico')
assert.equal(plazoEnVuelo.vision.cajones.value[0].etiqueta, 'ANTERIOR')
assert.equal(plazoEnVuelo.vision.pendiente.value, true)
assert.equal(consultasPlazoEnVuelo, 2, 'No se solapa un GET cuando vence la vigencia.')
respuestaLenta.resolver({
  cajones: [cajon('ANTERIOR', 'NO_VERIFICABLE')],
  cursor: 'epoca:1',
  vigenciaRestanteMs: null,
})
await consultaLenta
await plazoEnVuelo.reloj.avanzar(0)
assert.equal(consultasPlazoEnVuelo, 3, 'La caducidad pendiente se reconcilia al terminar el GET.')
assert.equal(plazoEnVuelo.vision.cajones.value[0].estado, 'NO_VERIFICABLE')
plazoEnVuelo.desmontar()

// Un TTL positivo que se agota durante el viaje exige una recuperación acotada.
let lecturasTtlConsumido = 0
const respuestaTtlConsumido = diferida()
const ttlConsumido = await crearEntorno(async () => {
  lecturasTtlConsumido += 1
  if (lecturasTtlConsumido === 1) {
    return { cajones: [cajon('C1')], cursor: 'epoca:0', vigenciaRestanteMs: 1_000 }
  }
  if (lecturasTtlConsumido === 2) return respuestaTtlConsumido.promesa
  return {
    cajones: [cajon('C1', 'NO_VERIFICABLE')],
    cursor: 'epoca:1',
    vigenciaRestanteMs: null,
  }
})
ttlConsumido.montar()
await ttlConsumido.reloj.avanzar(1_000)
assert.equal(lecturasTtlConsumido, 2)
await ttlConsumido.reloj.avanzar(100)
respuestaTtlConsumido.resolver({
  cajones: [cajon('C1')],
  cursor: 'epoca:1',
  vigenciaRestanteMs: 50,
})
await vaciarPromesas()
assert.equal(ttlConsumido.vision.estado.value, 'historico')
assert.equal(ttlConsumido.reloj.proximoRetraso(), 5_000)
await ttlConsumido.reloj.avanzar(5_000)
assert.equal(lecturasTtlConsumido, 3)
assert.equal(ttlConsumido.vision.cajones.value[0].estado, 'NO_VERIFICABLE')
ttlConsumido.desmontar()

// Una sucesión de TTL cero no puede generar un ciclo inmediato de solicitudes.
let lecturasTtlCero = 0
const ttlCeroRepetido = await crearEntorno(async () => {
  lecturasTtlCero += 1
  if (lecturasTtlCero === 1) {
    return { cajones: [cajon('C1')], cursor: 'epoca:0', vigenciaRestanteMs: 1_000 }
  }
  if (lecturasTtlCero <= 5) {
    return { cajones: [cajon('C1')], cursor: 'epoca:1', vigenciaRestanteMs: 0 }
  }
  return { cajones: [cajon('C1', 'NO_VERIFICABLE')], cursor: 'epoca:1', vigenciaRestanteMs: null }
})
ttlCeroRepetido.montar()
await ttlCeroRepetido.reloj.avanzar(1_000)
assert.equal(lecturasTtlCero, 2)
assert.equal(ttlCeroRepetido.vision.estado.value, 'historico')
assert.equal(ttlCeroRepetido.reloj.proximoRetraso(), 5_000)
for (const retraso of [5_000, 10_000, 20_000, 30_000]) {
  ttlCeroRepetido.evento()
  assert.equal(ttlCeroRepetido.reloj.proximoRetraso(), retraso)
  await ttlCeroRepetido.reloj.avanzar(retraso)
}
assert.equal(lecturasTtlCero, 6)
assert.equal(ttlCeroRepetido.vision.cajones.value[0].estado, 'NO_VERIFICABLE')
ttlCeroRepetido.desmontar()

const ttlCero = await crearEntorno(async () => ({
  cajones: [cajon('C1')],
  cursor: 'epoca:0',
  vigenciaRestanteMs: 0,
}))
ttlCero.montar()
assert.equal(ttlCero.vision.estado.value, 'historico')
assert.equal(ttlCero.reloj.proximoRetraso(), 5_000)
ttlCero.sesion.value = { estado: 'anonima', identidad: null }
assert.equal(ttlCero.vision.hayDatos.value, false)
assert.equal(ttlCero.reloj.proximoRetraso(), null)
ttlCero.desmontar()

for (const ttl of [null, -1, Number.NaN]) {
  const ttlInvalido = await crearEntorno(async () => ({
    cajones: [cajon('C1')],
    cursor: 'epoca:0',
    vigenciaRestanteMs: ttl,
  }))
  ttlInvalido.montar()
  assert.equal(ttlInvalido.vision.estado.value, 'historico')
  assert.equal(ttlInvalido.reloj.proximoRetraso(), 5_000)
  ttlInvalido.desmontar()
}

const sinEstadosVigentes = await crearEntorno(async () => ({
  cajones: [cajon('C1', 'NO_VERIFICABLE')],
  cursor: 'epoca:0',
  vigenciaRestanteMs: null,
}))
sinEstadosVigentes.montar()
assert.equal(sinEstadosVigentes.vision.estado.value, 'actual')
assert.equal(sinEstadosVigentes.reloj.proximoRetraso(), 30_000)
sinEstadosVigentes.desmontar()

// La navegación consumió el TTL de SSR: se neutraliza al montar y se consulta una vez.
let lecturasSsrVencido = 0
const ssrVencido = await crearEntorno(
  async () => {
    lecturasSsrVencido += 1
    return [cajon('FRESCO')]
  },
  { ...payload, vigenciaRestanteMs: 1_000 },
)
await ssrVencido.reloj.avanzar(1_500)
assert.equal(ssrVencido.vision.estado.value, 'actual')
ssrVencido.montar()
assert.equal(ssrVencido.vision.estado.value, 'historico')
await ssrVencido.reloj.avanzar(100)
assert.equal(lecturasSsrVencido, 1)
assert.equal(ssrVencido.vision.cajones.value[0].etiqueta, 'FRESCO')
ssrVencido.desmontar()

// Ocultar/online invalida respuestas viejas y reanuda sin interacción.
let visibilidadLlamadas = 0
let signalAntiguo
const vieja = diferida()
const visibilidad = await crearEntorno(async (signal) => {
  visibilidadLlamadas += 1
  if (visibilidadLlamadas === 1) return [cajon('C1')]
  if (visibilidadLlamadas === 2) {
    signalAntiguo = signal
    return vieja.promesa
  }
  return [cajon('C3', 'OCUPADO')]
})
visibilidad.montar()
const peticionVieja = visibilidad.vision.actualizar()
await vaciarPromesas()
visibilidad.documento.visibilityState = 'hidden'
visibilidad.documento.emitir('visibilitychange')
assert.equal(signalAntiguo.aborted, true)
assert.equal(visibilidad.vision.estado.value, 'historico')
visibilidad.documento.visibilityState = 'visible'
visibilidad.documento.emitir('visibilitychange')
vieja.resolver([cajon('VIEJO')])
await peticionVieja
await visibilidad.reloj.avanzar(0)
assert.equal(visibilidadLlamadas, 3)
assert.equal(visibilidad.vision.cajones.value[0].etiqueta, 'C3')
visibilidad.navegador.onLine = false
visibilidad.ventana.emitir('offline')
await visibilidad.reloj.avanzar(10_000)
assert.equal(visibilidadLlamadas, 3)
visibilidad.navegador.onLine = true
visibilidad.ventana.emitir('online')
await visibilidad.reloj.avanzar(0)
assert.equal(visibilidadLlamadas, 4)
visibilidad.desmontar()
assert.equal(visibilidad.documento.cantidad(), 0)
assert.equal(visibilidad.ventana.cantidad(), 0)

// El backoff limita incluso las invalidaciones repetidas.
let intentos = 0
const reintentos = await crearEntorno(async () => {
  intentos += 1
  if (intentos > 1 && intentos < 6) throw new ErrorVisionApi(503)
  return [cajon(intentos === 1 ? 'C1' : 'C9')]
})
reintentos.montar()
await reintentos.vision.actualizar()
for (const retraso of [5_000, 10_000, 20_000, 30_000]) {
  reintentos.evento()
  assert.equal(reintentos.reloj.proximoRetraso(), retraso)
  await reintentos.reloj.avanzar(retraso)
}
assert.equal(intentos, 6)
assert.equal(reintentos.vision.cajones.value[0].etiqueta, 'C9')
reintentos.desmontar()

// Timeout y respuesta tardía tras logout no restauran datos.
let timeoutLlamadas = 0
const tiempoLimite = await crearEntorno(async (signal) => {
  timeoutLlamadas += 1
  if (timeoutLlamadas === 1) return [cajon('C1')]
  return new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('Tiempo agotado', 'AbortError')))
  })
})
tiempoLimite.montar()
void tiempoLimite.vision.actualizar()
await tiempoLimite.reloj.avanzar(8_000)
assert.equal(tiempoLimite.vision.estado.value, 'historico')
assert.equal(tiempoLimite.reloj.proximoRetraso(), 5_000)
tiempoLimite.desmontar()
let signalSesion
const trasSalida = diferida()
let sesionesLlamadas = 0
const salida = await crearEntorno(async (signal) => {
  sesionesLlamadas += 1
  if (sesionesLlamadas === 1) return [cajon('C1')]
  signalSesion = signal
  return trasSalida.promesa
})
salida.montar()
const peticionSalida = salida.vision.actualizar()
await vaciarPromesas()
salida.sesion.value = { estado: 'anonima', identidad: null }
assert.equal(signalSesion.aborted, true)
trasSalida.resolver([cajon('PRIVADO')])
await peticionSalida
assert.equal(salida.vision.hayDatos.value, false)
assert.equal(salida.reloj.proximoRetraso(), null)
salida.desmontar()

// Autorización denegada no conserva el snapshot; 401 confirma la sesión.
for (const codigo of [401, 403]) {
  let consultas = 0
  const acceso = await crearEntorno(
    async () => {
      if (++consultas === 1) return [cajon('C1')]
      throw new ErrorVisionApi(codigo)
    },
    undefined,
    async (sesion) => {
      if (codigo === 401) sesion.value = { estado: 'anonima', identidad: null }
    },
  )
  acceso.montar()
  await acceso.vision.actualizar()
  assert.equal(acceso.vision.hayDatos.value, false)
  if (codigo === 401) {
    assert.equal(acceso.csrf.limpiezas, 1)
    assert.deepEqual(acceso.navegaciones, ['/panel'])
  } else {
    assert.equal(acceso.csrf.limpiezas, 0)
    assert.equal(acceso.vision.estado.value, 'sin-sesion')
  }
  acceso.desmontar()
}
console.log('PASS: SSR, SSE, reconciliación, vigencia, backoff, sesión y limpieza Vision.')
