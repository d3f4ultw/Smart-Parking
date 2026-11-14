import { once } from 'node:events'
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { setTimeout as pause } from 'node:timers/promises'

export async function iniciarCierreBff() {
  const maximoBytes = 1_048_576
  let solicitudesPanel = 0
  let solicitudesSesion = 0
  let solicitudesPost = 0
  let bytesPost = []
  const solicitudesPorRuta = new Map()
  const cookiesSesionUpstream = []

  function escribirJson(respuesta, estado, datos, cookies = []) {
    respuesta.writeHead(estado, {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      ...(cookies.length ? { 'set-cookie': cookies } : {}),
    })
    respuesta.end(JSON.stringify(datos))
  }

  const servidorApi = createServer(async (solicitud, respuesta) => {
    const ruta = new URL(solicitud.url ?? '/', 'http://127.0.0.1').pathname
    const cookie = solicitud.headers.cookie ?? ''
    solicitudesPorRuta.set(ruta, (solicitudesPorRuta.get(ruta) ?? 0) + 1)

    if (ruta === '/api/v1/csrf' && solicitud.method === 'GET') {
      escribirJson(respuesta, 200, { csrfToken: 'csrf-sintetico' })
      return
    }

    if (ruta === '/api/v1/sesion' && solicitud.method === 'GET') {
      solicitudesSesion += 1
      cookiesSesionUpstream.push(cookie)
      const cookies = cookie.includes('JSESSIONID=TEST_MULTI')
        ? [
            'JSESSIONID=valor-sintetico; Path=/api/v1; HttpOnly; SameSite=Strict',
            'CSRF-TOKEN=otro-valor; Expires=Wed, 21 Oct 2037 07:28:00 GMT; Path=/api/v1; SameSite=Strict',
          ]
        : []
      if (cookie.includes('JSESSIONID=SESSION_A') || cookie.includes('JSESSIONID=SESSION_B')) {
        const sufijo = cookie.includes('JSESSIONID=SESSION_A') ? 'A' : 'B'
        escribirJson(
          respuesta,
          200,
          {
            autenticada: true,
            correo: `dueno-${sufijo}@example.test`,
            rol: 'DUENO',
            cuentaId: `uuid-interno-${sufijo}`,
            revisionPropietario: 7,
            csrfToken: `csrf-privado-${sufijo}`,
            hashContrasena: `hash-privado-${sufijo}`,
          },
          cookies,
        )
        return
      }
      if (cookie.includes('JSESSIONID=SESSION_REVOKED')) {
        escribirJson(respuesta, 401, { codigo: 'SESION_NO_VIGENTE' }, [
          'JSESSIONID=; Max-Age=0; Path=/api/v1; HttpOnly; SameSite=Strict',
        ])
        return
      }
      if (cookie.includes('JSESSIONID=API_DOWN')) {
        escribirJson(respuesta, 503, { codigo: 'API_NO_DISPONIBLE' })
        return
      }
      escribirJson(respuesta, 200, { autenticada: false }, cookies)
      return
    }

    if (ruta === '/api/v1/panel' && solicitud.method === 'GET') {
      solicitudesPanel += 1
      if (cookie.includes('JSESSIONID=SESSION_REVOKED')) {
        escribirJson(respuesta, 401, { codigo: 'SESION_NO_VIGENTE' }, [
          'JSESSIONID=; Max-Age=0; Path=/api/v1; HttpOnly; SameSite=Strict',
        ])
        return
      }
      if (cookie.includes('JSESSIONID=SESSION_OPERATOR')) {
        escribirJson(respuesta, 403, { codigo: 'PERMISO_INSUFICIENTE' })
        return
      }
      if (cookie.includes('JSESSIONID=API_DOWN')) {
        escribirJson(respuesta, 503, { codigo: 'API_NO_DISPONIBLE' })
        return
      }
      const sufijo = cookie.includes('JSESSIONID=SESSION_A') ? 'A' : 'B'
      escribirJson(respuesta, 200, {
        propietario: {
          nombres: `Nombre-${sufijo}`,
          primerApellido: 'Sintetico',
          segundoApellido: null,
          correo: `dueno-${sufijo}@example.test`,
          cuentaId: `uuid-interno-${sufijo}`,
          hashContrasena: `hash-privado-${sufijo}`,
        },
        estacionamiento: {
          id: `estacionamiento-privado-${sufijo}`,
          nombre: `Estacionamiento-${sufijo}`,
          tipo: 'PUBLICO',
          horario: { modo: 'CONTINUO_24_7', zonaHoraria: 'America/Mexico_City' },
        },
        materialAdministrativo: `secreto-admin-${sufijo}`,
      })
      return
    }

    if (ruta === '/api/v1/vision/cajones' && solicitud.method === 'GET') {
      if (!cookie.includes('JSESSIONID=SESSION_A') && !cookie.includes('JSESSIONID=SESSION_B')) {
        escribirJson(respuesta, 401, { codigo: 'SESION_NO_VIGENTE' })
        return
      }
      const sufijo = cookie.includes('JSESSIONID=SESSION_A') ? 'A' : 'B'
      respuesta.writeHead(200, {
        'content-type': 'application/json; charset=utf-8',
        'cache-control': 'no-store, private',
        'x-eventos-cursor': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa:0',
      })
      respuesta.end(
        JSON.stringify([
          {
            cajonId: `00000000-0000-4000-8000-00000000000${sufijo === 'A' ? 1 : 2}`,
            etiqueta: `C-VISION-${sufijo}`,
            estado: 'NO_VERIFICABLE',
            ultimoEstadoConfirmado: null,
            observadoEn: null,
          },
        ]),
      )
      return
    }

    if (ruta === '/api/v1/sesion' && solicitud.method === 'POST') {
      const partes = []
      for await (const parte of solicitud) partes.push(parte)
      const cuerpo = Buffer.concat(partes)
      solicitudesPost += 1
      bytesPost.push(cuerpo.byteLength)
      if (solicitud.headers['x-csrf-token'] !== 'csrf-valido-sintetico') {
        escribirJson(respuesta, 403, {
          codigo: 'CSRF_RECHAZADO',
          error: 'La solicitud no es válida.',
        })
        return
      }
      escribirJson(respuesta, 401, {
        codigo: 'CREDENCIALES_NO_VALIDAS',
        error: 'Correo o contraseña no válidos.',
      })
      return
    }

    if (ruta === '/api/v1/sesion' && solicitud.method === 'DELETE') {
      escribirJson(respuesta, 200, { autenticada: false, csrfToken: 'csrf-renovado' }, [
        'JSESSIONID=; Max-Age=0; Path=/api/v1; HttpOnly; SameSite=Strict',
      ])
      return
    }

    respuesta.writeHead(404)
    respuesta.end()
  })

  await new Promise((resolve) => servidorApi.listen(0, '127.0.0.1', resolve))
  const puertoApi = servidorApi.address().port
  const servidorNitro = createServer()
  await new Promise((resolve) => servidorNitro.listen(0, '127.0.0.1', resolve))
  const puertoNitro = servidorNitro.address().port
  await new Promise((resolve) => servidorNitro.close(resolve))

  const salida = []
  const proceso = spawn('node', ['.output/server/index.mjs'], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      NUXT_API_INTERNAL_BASE: `http://127.0.0.1:${puertoApi}`,
      NITRO_HOST: '127.0.0.1',
      NITRO_PORT: String(puertoNitro),
      HOST: '127.0.0.1',
      PORT: String(puertoNitro),
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  proceso.stdout.on('data', (chunk) => salida.push(String(chunk)))
  proceso.stderr.on('data', (chunk) => salida.push(String(chunk)))

  const base = `http://127.0.0.1:${puertoNitro}`
  let listo = false
  for (let intento = 0; intento < 100; intento += 1) {
    if (proceso.exitCode !== null) break
    try {
      const respuesta = await fetch(`${base}/panel`)
      if (respuesta.status < 500) {
        listo = true
        break
      }
    } catch {}
    await pause(200)
  }

  return {
    base,
    listo,
    salida,
    puertoApi,
    proceso,
    maximoBytes,
    cookiesSesionUpstream,
    solicitudesPorRuta,
    get solicitudesPanel() {
      return solicitudesPanel
    },
    get solicitudesSesion() {
      return solicitudesSesion
    },
    get solicitudesPost() {
      return solicitudesPost
    },
    get bytesPost() {
      return bytesPost
    },
    async cerrar() {
      proceso.kill('SIGTERM')
      await Promise.race([once(proceso, 'exit'), pause(3000)])
      await new Promise((resolve) => servidorApi.close(resolve))
    },
  }
}
