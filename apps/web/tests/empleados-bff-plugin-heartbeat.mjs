import assert from 'node:assert/strict'
import { lstat, readdir, rm, symlink } from 'node:fs/promises'
import { setTimeout as pause } from 'node:timers/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { FuenteEventosSimulada, esperar } from './soporte-empleados-eventos.mjs'

export async function verificarPluginHeartbeat(servidor) {
  const { base, solicitudes } = servidor
  const directorioPrueba = dirname(fileURLToPath(import.meta.url))
  const rutaVue = resolve(directorioPrueba, '../node_modules/vue')
  const rutaPaquetes = resolve(directorioPrueba, '../node_modules/.pnpm')
  let enlaceVueCreado = false
  try {
    await lstat(rutaVue)
  } catch (fallo) {
    if (fallo.code !== 'ENOENT') throw fallo
    const entradas = await readdir(rutaPaquetes)
    const paqueteVue = entradas.find((entrada) => entrada.startsWith('vue@'))
    assert.ok(paqueteVue, 'Vue debe estar instalado como dependencia transitiva de Nuxt UI')
    await symlink(resolve(rutaPaquetes, paqueteVue, 'node_modules/vue'), rutaVue, 'dir')
    enlaceVueCreado = true
  }

  const { effectScope, ref } = await import('vue')
  const scope = effectScope()
  const sesion = ref({ estado: 'autenticada', identidad: { rol: 'DUENO' } })
  const fuentes = []
  const llamadasActualizar = { total: 0 }
  const propiedadesAnteriores = new Map()
  const nombresGlobales = [
    'defineNuxtPlugin',
    'useSesion',
    'useCsrf',
    'useRoute',
    'navigateTo',
    'EventSource',
    'fetch',
  ]
  for (const nombre of nombresGlobales) propiedadesAnteriores.set(nombre, globalThis[nombre])
  const fetchOriginal = globalThis.fetch
  let dejarDeEscuchar = () => {}
  let estadoRespuestaAck

  globalThis.defineNuxtPlugin = (configurar) => configurar
  globalThis.useSesion = () => ({
    sesion,
    actualizar: async () => {
      llamadasActualizar.total += 1
    },
  })
  globalThis.useCsrf = () => ({ obtener: async () => 'csrf-heartbeat' })
  globalThis.useRoute = () => ({ path: '/admin/empleados' })
  globalThis.navigateTo = async () => {}
  globalThis.EventSource = class extends FuenteEventosSimulada {
    constructor(url) {
      super(url)
      fuentes.push(this)
    }
  }
  globalThis.fetch = async (entrada, opciones = {}) => {
    const url = new URL(String(entrada), base)
    const encabezados = new Headers(opciones.headers)
    encabezados.set('cookie', 'JSESSIONID=SESION_HEARTBEAT')
    const respuesta = await fetchOriginal(url, { ...opciones, headers: encabezados })
    if (url.pathname === '/api/v1/eventos/administracion/heartbeat')
      estadoRespuestaAck = respuesta.status
    return respuesta
  }

  try {
    const plugin = await import(
      `../app/plugins/eventos-administracion.client.ts?prueba=${Date.now()}`
    )
    let cliente
    scope.run(() => {
      cliente = plugin.default().provide.eventosAdministracion
    })
    let actualizaciones = 0
    dejarDeEscuchar = cliente.suscribir(() => {
      actualizaciones += 1
    }, 'epoch-1:7')
    assert.equal(fuentes.length, 1)
    assert.match(fuentes[0].url, /despues=epoch-1%3A7/)
    fuentes[0].emitir('empleado.directorio.actualizado', { lastEventId: 'epoch-1:8', data: '{}' })
    assert.equal(actualizaciones, 1)

    const cantidadGetDirectorio = solicitudes.filter(
      (solicitud) => solicitud.method === 'GET' && solicitud.path === '/api/v1/empleados',
    ).length
    const acksAntesInvalidos = solicitudes.filter((solicitud) =>
      solicitud.path.endsWith('/heartbeat'),
    ).length
    for (const datos of [
      { suscripcionId: '00000000-0000-3000-8000-000000000001', secuencia: 1 },
      { suscripcionId: '00000000-0000-4000-8000-000000000001', secuencia: 0 },
      {
        suscripcionId: '00000000-0000-4000-8000-000000000001',
        secuencia: Number.MAX_SAFE_INTEGER + 1,
      },
    ]) {
      fuentes[0].emitir('empleado.heartbeat', {
        lastEventId: 'cursor-que-no-debe-usarse',
        data: JSON.stringify(datos),
      })
      await pause(15)
    }
    assert.equal(
      solicitudes.filter((solicitud) => solicitud.path.endsWith('/heartbeat')).length,
      acksAntesInvalidos,
      'Debe ignorar UUID y secuencias inválidas',
    )

    const cantidadAcks = solicitudes.filter((solicitud) =>
      solicitud.path.endsWith('/heartbeat'),
    ).length
    fuentes[0].emitir('empleado.heartbeat', {
      lastEventId: 'cursor-que-no-debe-usarse',
      data: JSON.stringify({ suscripcionId: '00000000-0000-4000-8000-000000000001', secuencia: 1 }),
    })
    await esperar(
      () =>
        solicitudes.filter((solicitud) => solicitud.path.endsWith('/heartbeat')).length >
        cantidadAcks,
      'El heartbeat válido no produjo ACK por el BFF',
    )

    const solicitudAck = solicitudes.findLast(
      (solicitud) => solicitud.path === '/api/v1/eventos/administracion/heartbeat',
    )
    assert.equal(solicitudAck.method, 'POST')
    assert.equal(solicitudAck.headers.cookie, 'JSESSIONID=SESION_HEARTBEAT')
    assert.equal(solicitudAck.headers['x-csrf-token'], 'csrf-heartbeat')
    assert.deepEqual(JSON.parse(solicitudAck.body), {
      suscripcionId: '00000000-0000-4000-8000-000000000001',
      secuencia: 1,
    })
    assert.equal(estadoRespuestaAck, 204)
    assert.equal(actualizaciones, 1, 'El ACK no debe invocar la reacción del directorio')
    assert.equal(llamadasActualizar.total, 0, 'El ACK no debe validar ni refrescar la sesión')
    assert.equal(
      solicitudes.filter(
        (solicitud) => solicitud.method === 'GET' && solicitud.path === '/api/v1/empleados',
      ).length,
      cantidadGetDirectorio,
    )

    fuentes[0].onerror()
    await esperar(() => fuentes.length > 1, 'El EventSource simulado no reconectó', 2_500)
    assert.match(
      fuentes[1].url,
      /despues=epoch-1%3A8/,
      'El heartbeat no debe mover el cursor de negocio',
    )
    assert.doesNotMatch(fuentes[1].url, /cursor-que-no-debe-usarse/)
    dejarDeEscuchar()
    assert.equal(fuentes[1].closed, true)
    return [
      'plugin ACK con cookie/CSRF/body',
      'sin refresh del directorio',
      'cursor SSE de negocio sin cambios',
    ]
  } finally {
    dejarDeEscuchar()
    scope.stop()
    for (const nombre of nombresGlobales) {
      const anterior = propiedadesAnteriores.get(nombre)
      if (anterior === undefined) delete globalThis[nombre]
      else globalThis[nombre] = anterior
    }
    if (enlaceVueCreado) await rm(rutaVue)
  }
}
