import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, delay, evaluarTypescript, ref, watch } from './soporte-historial-accesos.mjs'

const id = '01234567-89ab-4cde-8abc-0123456789ab'
const entrada = {
  movimientoId: '19',
  persona: { tipo: 'EMPLEADO', nombre: 'Persona sintética', codigo: 'E-0001' },
  estadoTarjeta: 'CANCELADA',
  entradaEn: '2026-11-10T12:00:00Z',
  entradaEnLocal: '2026-11-10T06:00:00-06:00',
  salidaManual: null,
}
const fuenteApi = await readFile(new URL('../app/utils/salida-manual-api.ts', import.meta.url), 'utf8')
const solicitudes = []
let respuesta = { operacionId: id, movimientoId: '19', estado: 'PENDIENTE' }
const moduloApi = evaluarTypescript(fuenteApi, {
  '~/utils/api': {
    solicitarApi: async (ruta, opciones) => {
      solicitudes.push({ ruta, opciones })
      return respuesta
    },
  },
})
const cliente = moduloApi.useClienteSalidaManual()
assert.deepEqual(await cliente.solicitar('19', id, 'csrf-sintetico'), { operacionId: id, estado: 'PENDIENTE' })
assert.equal(solicitudes[0].ruta, '/api/v1/accesos/movimientos/19/salida-manual')
assert.equal(solicitudes[0].opciones.headers['idempotency-key'], id)
assert.equal(solicitudes[0].opciones.headers['x-csrf-token'], 'csrf-sintetico')
assert.equal(solicitudes[0].opciones.retry, 0)
await cliente.consultar('19', id)
assert.equal(solicitudes[1].ruta, `/api/v1/accesos/salidas-manuales/${id}`)
respuesta = { ...respuesta, movimientoId: '20' }
await assert.rejects(cliente.consultar('19', id), /verificar/)
respuesta = { ...respuesta, movimientoId: '19', estado: 'INVENTADO' }
await assert.rejects(cliente.consultar('19', id), /verificar/)
assert.equal(moduloApi.leerSalidaManual({ operacionId: id, estado: 'PENDIENTE', uid: 'DATO_PRIVADO' }).uid, undefined)

const fuente = await readFile(new URL('../app/composables/useSalidasManuales.ts', import.meta.url), 'utf8')
const fuenteErrores = await readFile(new URL('../app/utils/api.ts', import.meta.url), 'utf8')
const { ErrorApi, solicitarApi } = evaluarTypescript(fuenteErrores, {}, {
  $fetch: async () => { throw { statusCode: 503, data: { codigo: 'SALIDA_MANUAL_NO_DISPONIBLE' } } },
})
await assert.rejects(
  solicitarApi('/api/v1/accesos/movimientos/19/salida-manual'),
  (fallo) => fallo instanceof ErrorApi && fallo.estado === 503 && fallo.codigo === 'SALIDA_MANUAL_NO_DISPONIBLE',
  'El cliente conserva el código específico incluido en el cuerpo del BFF.',
)
const sesion = ref({ estado: 'autenticada', identidad: { rol: 'DUENO', correo: 'dueno@ejemplo.test' } })
const pagina = ref({ items: [entrada] })
let enviar
let resolverEnvio
let consultas = []
let actualizacionesDentro = 0
let actualizacionesHistorial = 0
const modulo = evaluarTypescript(fuente.replaceAll('import.meta.client', 'true'), {
  vue: { computed, ref, watch },
  '~/utils/api': { ErrorApi },
  '~/utils/salida-manual-api': {
    useClienteSalidaManual: () => ({
      solicitar: (...argumentos) => {
        enviar.push(argumentos)
        return new Promise((resolve, reject) => { resolverEnvio = { resolve, reject } })
      },
      consultar: async (...argumentos) => {
        consultas.push(argumentos)
        return { operacionId: id, estado: 'INCIERTA' }
      },
    }),
  },
}, {
  useSesion: () => ({ sesion }),
  useCsrf: () => ({ obtener: async () => 'csrf-sintetico' }),
  globalThis: { crypto: { randomUUID: () => id } },
})
enviar = []
const disponible = ref(true)
const flujo = modulo.useSalidasManuales(pagina, async () => { actualizacionesDentro += 1 }, async () => { actualizacionesHistorial += 1 }, () => disponible.value)
assert.equal(flujo.puedeSolicitar(entrada), true)
assert.equal(flujo.puedeSolicitar({ ...entrada, estadoTarjeta: 'ACTIVA' }), false)
disponible.value = false
assert.equal(flujo.puedeSolicitar(entrada), false, 'La salida requiere prueba fresca del dispositivo.')
disponible.value = true
flujo.seleccionar(entrada)
assert.equal(flujo.abierta.value, true)
const primero = flujo.confirmar()
await delay(0)
await flujo.confirmar()
assert.equal(enviar.length, 1, 'El doble clic no inicia otra solicitud.')
assert.deepEqual(enviar[0], ['19', id, 'csrf-sintetico'])
assert.equal(flujo.estado(entrada).estado, 'SIN_CONFIRMACION')
assert.equal(pagina.value.items.length, 1, 'La visita sigue abierta mientras no exista confirmación.')
resolverEnvio.reject(new Error('respuesta perdida'))
await primero
assert.equal(flujo.estado(entrada).estado, 'SIN_CONFIRMACION')
assert.equal(flujo.puedeSolicitar(entrada), false)
await flujo.consultar(entrada)
assert.deepEqual(consultas, [['19', id]], 'La consulta conserva la clave original tras timeout.')
assert.equal(flujo.estado(entrada).estado, 'INCIERTA')
assert.equal(pagina.value.items.length, 1)
assert.ok(actualizacionesDentro >= 1)
assert.equal(actualizacionesHistorial, 0)
sesion.value = { estado: 'autenticada', identidad: { rol: 'OPERADOR', correo: 'operador@ejemplo.test' } }
assert.equal(flujo.estado(entrada), null, 'Cambiar de identidad limpia las referencias locales.')
sesion.value = { estado: 'autenticada', identidad: { rol: 'CLIENTE', correo: 'cliente@ejemplo.test' } }
assert.equal(flujo.puedeSolicitar(entrada), false)

sesion.value = { estado: 'autenticada', identidad: { rol: 'DUENO', correo: 'dueno@ejemplo.test' } }
flujo.seleccionar(entrada)
const sinClave = flujo.confirmar()
await delay(0)
resolverEnvio.reject(new ErrorApi(503, 'SALIDA_MANUAL_NO_DISPONIBLE', 'No disponible'))
await sinClave
assert.equal(flujo.estado(entrada), null, 'El rechazo de configuración no creó solicitud.')
assert.equal(flujo.puedeSolicitar(entrada), true, 'El usuario puede confirmar otro intento explícito.')
assert.match(flujo.mensaje.value, /no está disponible/i)
const posterioresAlRechazo = enviar.length
await delay(0)
assert.equal(enviar.length, posterioresAlRechazo, 'Un rechazo no dispara otro POST automáticamente.')

const conflicto = flujo.confirmar()
await delay(0)
resolverEnvio.reject(new ErrorApi(409, 'CONFLICTO', 'Conflicto'))
await conflicto
assert.equal(flujo.estado(entrada).estado, 'SIN_CONFIRMACION', 'Un 409 requiere reconciliar la solicitud.')
assert.equal(flujo.puedeSolicitar(entrada), false)

sesion.value = { estado: 'autenticada', identidad: { rol: 'OPERADOR', correo: 'operador@ejemplo.test' } }
flujo.seleccionar(entrada)
const indisponibleGenerico = flujo.confirmar()
await delay(0)
resolverEnvio.reject(new ErrorApi(503, 'API_NO_DISPONIBLE', 'Sin respuesta'))
await indisponibleGenerico
assert.equal(flujo.estado(entrada).operacionId, id, 'El 503 de transporte conserva la clave.')
assert.equal(flujo.estado(entrada).estado, 'SIN_CONFIRMACION')
assert.equal(flujo.puedeSolicitar(entrada), false)

sesion.value = { estado: 'autenticada', identidad: { rol: 'DUENO', correo: 'dueno@ejemplo.test' } }
flujo.seleccionar(entrada)
const codigoIncorrecto = flujo.confirmar()
await delay(0)
resolverEnvio.reject(new ErrorApi(409, 'SALIDA_MANUAL_NO_DISPONIBLE', 'Conflicto'))
await codigoIncorrecto
assert.equal(flujo.estado(entrada).estado, 'SIN_CONFIRMACION', 'El código solo es definitivo con HTTP 503.')
assert.equal(flujo.puedeSolicitar(entrada), false)

const fuenteDisponibilidad = await readFile(new URL('../app/composables/useDisponibilidadSalidaManual.ts', import.meta.url), 'utf8')
const escuchas = new Map()
const superficie = () => ({
  addEventListener(nombre, funcion) { escuchas.set(nombre, funcion) },
  removeEventListener(nombre) { escuchas.delete(nombre) },
})
const documento = { ...superficie(), visibilityState: 'visible' }
const navegador = { onLine: true }
const vista = ref('DENTRO')
const sesionDisponibilidad = ref({ estado: 'autenticada', identidad: { rol: 'DUENO', correo: 'dueno@ejemplo.test' } })
let montar
let desmontar
let modo = 'vigente'
let resolverLectura
const moduloDisponibilidad = evaluarTypescript(fuenteDisponibilidad.replaceAll('import.meta.client', 'true'), {
  vue: {
    computed, ref, watch,
    onMounted: (funcion) => { montar = funcion },
    onScopeDispose: (funcion) => { desmontar = funcion },
  },
  '~/utils/api': {
    solicitarApi: async () => {
      if (modo === 'demorada') return new Promise((resolve) => { resolverLectura = resolve })
      if (modo === 'invalida') return { disponible: true }
      return { disponible: true, vigenciaRestanteMs: 40 }
    },
  },
}, {
  useRoute: () => ({ path: '/admin/accesos' }),
  useSesion: () => ({ sesion: sesionDisponibilidad }),
  document: documento, window: superficie(), navigator: navegador, performance,
})
const disponibilidad = moduloDisponibilidad.useDisponibilidadSalidaManual(vista)
assert.equal(disponibilidad.disponible.value, false, 'SSR y carga inicial no habilitan la barrera.')
montar()
await delay(5)
assert.equal(disponibilidad.disponible.value, true)
await delay(70)
assert.equal(disponibilidad.disponible.value, false, 'La prueba vence en cliente sin esperar otro sondeo.')
modo = 'invalida'
escuchas.get('focus')()
await delay(5)
assert.equal(disponibilidad.disponible.value, false, 'Una respuesta incompleta falla cerrada.')
modo = 'demorada'
escuchas.get('focus')()
await delay(60)
resolverLectura({ disponible: true, vigenciaRestanteMs: 40 })
await delay(5)
assert.equal(disponibilidad.disponible.value, false, 'El tiempo de la petición se descuenta de la vigencia.')
escuchas.get('focus')()
sesionDisponibilidad.value = { estado: 'anonima' }
resolverLectura({ disponible: true, vigenciaRestanteMs: 8000 })
await delay(5)
assert.equal(disponibilidad.disponible.value, false, 'Una respuesta de la sesión anterior se descarta.')
desmontar()

console.log('PASS: elegibilidad, doble clic, 503 definitivo, 503 genérico, 409, timeout, disponibilidad y aislamiento.')
