import assert from 'node:assert/strict'
import { setTimeout as pause } from 'node:timers/promises'

export async function verificarEventosEmpleados(servidor) {
  const { base, solicitudes } = servidor
  const abortar = new AbortController()
  const flujo = await fetch(`${base}/api/v1/eventos/administracion?despues=epoch-1%3A7`, {
    headers: {
      cookie: 'JSESSIONID=SESION_SINTETICA',
      accept: 'text/event-stream',
      'last-event-id': 'epoch-1:6',
    },
    signal: abortar.signal,
  })
  assert.equal(flujo.status, 200)
  assert.match(flujo.headers.get('content-type') ?? '', /text\/event-stream/)
  assert.equal(flujo.headers.get('x-accel-buffering'), 'no')
  const lector = flujo.body.getReader()
  const primerEvento = await lector.read()
  assert.match(new TextDecoder().decode(primerEvento.value), /empleado\.directorio\.actualizado/)
  const eventoEsperado = new TextEncoder().encode(
    'id: epoch-1:8\nevent: empleado.directorio.actualizado\ndata: {}\n\n',
  )
  assert.deepEqual(
    primerEvento.value.slice(0, eventoEsperado.length),
    eventoEsperado,
    'El BFF debe conservar los bytes SSE upstream sin alterar',
  )
  const solicitudSse = solicitudes.at(-1)
  assert.equal(solicitudSse.search, '?despues=epoch-1%3A7')
  assert.equal(solicitudSse.headers['last-event-id'], 'epoch-1:6')
  abortar.abort()
  await lector.cancel().catch(() => {})
  for (let intento = 0; intento < 30 && servidor.cancelacionesSse === 0; intento += 1)
    await pause(50)
  assert.ok(servidor.cancelacionesSse > 0, 'El cierre del cliente debe cancelar el flujo upstream')

  const flujoInterrumpido = await fetch(`${base}/api/v1/eventos/administracion?despues=fallo`, {
    headers: { cookie: 'JSESSIONID=SESION_SINTETICA', accept: 'text/event-stream' },
  })
  assert.equal(flujoInterrumpido.status, 200)
  const lectorInterrumpido = flujoInterrumpido.body.getReader()
  const eventoInicial = await lectorInterrumpido.read()
  assert.match(new TextDecoder().decode(eventoInicial.value), /empleado\.directorio\.actualizado/)
  const resultadoInterrupcion = await Promise.race([
    lectorInterrumpido.read().then(
      (resultado) => ({ resultado }),
      (fallo) => ({ fallo }),
    ),
    pause(2_000).then(() => ({ vencio: true })),
  ])
  assert.notEqual(
    resultadoInterrupcion.vencio,
    true,
    'El BFF no debe dejar abierto el stream tras el fallo upstream',
  )
  assert.ok(
    resultadoInterrupcion.fallo instanceof Error,
    'El error upstream debe llegar al cliente como error de transporte',
  )

  const cantidadAntes = solicitudes.length
  const heartbeat = await fetch(`${base}/api/v1/eventos/administracion/heartbeat`, {
    method: 'POST',
    headers: {
      cookie: 'JSESSIONID=SESION_DIRECTA',
      'content-type': 'application/json',
      'x-csrf-token': 'csrf-directo',
    },
    body: JSON.stringify({ suscripcionId: '00000000-0000-4000-8000-000000000002', secuencia: 2 }),
  })
  assert.equal(heartbeat.status, 204)
  assert.equal(await heartbeat.text(), '')
  const solicitudHeartbeat = solicitudes.at(-1)
  assert.equal(solicitudHeartbeat.headers.cookie, 'JSESSIONID=SESION_DIRECTA')
  assert.equal(solicitudHeartbeat.headers['x-csrf-token'], 'csrf-directo')
  assert.deepEqual(JSON.parse(solicitudHeartbeat.body), {
    suscripcionId: '00000000-0000-4000-8000-000000000002',
    secuencia: 2,
  })
  return cantidadAntes
}


export async function verificarRutasEventosEmpleados(servidor, cantidadAntes) {
  const { base, solicitudes } = servidor
  const antesRutaNoPermitida = solicitudes.length
  assert.equal(
    (
      await fetch(`${base}/api/v1/eventos/administracion/heartbeat?extra=1`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: '{}',
      })
    ).status,
    404,
  )
  assert.equal(
    solicitudes.length,
    antesRutaNoPermitida,
    'La allowlist debe rechazar query extra en heartbeat',
  )

  const solicitudesAntes = solicitudes.length
  assert.equal((await fetch(`${base}/api/v1/empleados/9223372036854775808`)).status, 404)
  assert.equal((await fetch(`${base}/api/v1/empleados/12/correo-extra`)).status, 404)
  assert.equal((await fetch(`${base}/api/v1/empleados?pagina=1&admin=true`)).status, 404)
  assert.equal(
    solicitudes.length,
    solicitudesAntes,
    'La allowlist debe rechazar localmente rutas y parámetros extra',
  )
  assert.ok(solicitudes.length > cantidadAntes)
}
