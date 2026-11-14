import assert from 'node:assert/strict'

export async function verificarRutasEmpleados({ base, solicitudes }) {
  const directorio = await fetch(`${base}/api/v1/empleados?pagina=2`, {
    headers: { cookie: 'JSESSIONID=SESION_SINTETICA', accept: 'application/json' },
  })
  assert.equal(directorio.status, 200)
  assert.equal((await directorio.json()).cursorEventos, 'epoch-1:7')
  assert.match(directorio.headers.get('cache-control') ?? '', /no-store, private/)
  assert.match(directorio.headers.get('vary') ?? '', /Cookie/i)
  assert.equal(solicitudes.at(-1).search, '?pagina=2')
  assert.equal(solicitudes.at(-1).headers.cookie, 'JSESSIONID=SESION_SINTETICA')

  const elegibles = await fetch(
    `${base}/api/v1/empleados?pagina=1&busqueda=E-0042&soloElegiblesOperador=true`,
    { headers: { cookie: 'JSESSIONID=SESION_SINTETICA', accept: 'application/json' } },
  )
  assert.equal(elegibles.status, 200)
  assert.equal(solicitudes.at(-1).search, '?pagina=1&busqueda=E-0042&soloElegiblesOperador=true')
  assert.equal(solicitudes.at(-1).headers.cookie, 'JSESSIONID=SESION_SINTETICA')

  const registro = await fetch(`${base}/api/v1/empleados`, {
    method: 'POST',
    headers: {
      cookie: 'JSESSIONID=SESION_SINTETICA',
      'content-type': 'application/json',
      'x-csrf-token': 'csrf-sintetico',
      'idempotency-key': 'uuid-sintetico',
    },
    body: JSON.stringify({ nombres: 'Ana', primerApellido: 'Luz', segundoApellido: null }),
  })
  assert.equal(registro.status, 201)
  assert.deepEqual(await registro.json(), { id: 12, codigo: 'E-0012' })
  const solicitudRegistro = solicitudes.at(-1)
  assert.equal(solicitudRegistro.headers['x-csrf-token'], 'csrf-sintetico')
  assert.equal(solicitudRegistro.headers['idempotency-key'], 'uuid-sintetico')
  assert.deepEqual(JSON.parse(solicitudRegistro.body), {
    nombres: 'Ana',
    primerApellido: 'Luz',
    segundoApellido: null,
  })

  const registroConCorreo = await fetch(`${base}/api/v1/empleados`, {
    method: 'POST',
    headers: {
      cookie: 'JSESSIONID=SESION_SINTETICA',
      'content-type': 'application/json',
      'x-csrf-token': 'csrf-correo-alta',
      'idempotency-key': 'uuid-correo-alta',
    },
    body: JSON.stringify({
      nombres: 'Luz',
      primerApellido: 'Sol',
      segundoApellido: null,
      correo: 'luz@example.test',
    }),
  })
  assert.equal(registroConCorreo.status, 201)
  assert.deepEqual(JSON.parse(solicitudes.at(-1).body), {
    nombres: 'Luz',
    primerApellido: 'Sol',
    segundoApellido: null,
    correo: 'luz@example.test',
  })

  const cambio = await fetch(`${base}/api/v1/empleados/12/estado`, {
    method: 'PATCH',
    headers: {
      cookie: 'JSESSIONID=SESION_SINTETICA',
      'content-type': 'application/json',
      'x-csrf-token': 'csrf-sintetico',
      'if-match': '"1"',
    },
    body: JSON.stringify({ estado: 'INACTIVO' }),
  })
  assert.equal(cambio.status, 200)
  assert.equal(solicitudes.at(-1).headers['if-match'], '"1"')

  const idTexto = '9223372036854775807'
  const detalleExacto = await fetch(`${base}/api/v1/empleados/${idTexto}`, {
    headers: { cookie: 'JSESSIONID=SESION_SINTETICA', accept: 'application/json' },
  })
  assert.equal(detalleExacto.status, 200)
  assert.equal(detalleExacto.headers.get('etag'), '"9007199254740993"')
  assert.match(detalleExacto.headers.get('cache-control') ?? '', /no-store, private/)
  assert.equal((await detalleExacto.json()).idTexto, idTexto)
  assert.equal(solicitudes.at(-1).path, `/api/v1/empleados/${idTexto}`)
  assert.equal(solicitudes.at(-1).headers.cookie, 'JSESSIONID=SESION_SINTETICA')

  const correo = await fetch(`${base}/api/v1/empleados/${idTexto}/correo`, {
    method: 'PATCH',
    headers: {
      cookie: 'JSESSIONID=SESION_SINTETICA',
      'content-type': 'application/json',
      'x-csrf-token': 'csrf-correo',
      'if-match': '"9007199254740993"',
      'idempotency-key': 'clave-correo',
    },
    body: JSON.stringify({ correo: null }),
  })
  assert.equal(correo.status, 200)
  assert.equal(solicitudes.at(-1).headers['x-csrf-token'], 'csrf-correo')
  assert.equal(solicitudes.at(-1).headers['if-match'], '"9007199254740993"')
  assert.equal(solicitudes.at(-1).headers['idempotency-key'], 'clave-correo')
  assert.deepEqual(JSON.parse(solicitudes.at(-1).body), { correo: null })

  for (const sufijo of ['promocion', 'desactivacion']) {
    const respuesta = await fetch(`${base}/api/v1/empleados/${idTexto}/operador/${sufijo}`, {
      method: 'POST',
      headers: {
        cookie: 'JSESSIONID=SESION_SINTETICA',
        'content-type': 'application/json',
        'x-csrf-token': `csrf-${sufijo}`,
        'if-match': '"9007199254740993"',
        'idempotency-key': `clave-${sufijo}`,
      },
      body: '{}',
    })
    assert.equal(respuesta.status, 200)
    assert.equal(solicitudes.at(-1).headers['if-match'], '"9007199254740993"')
    assert.equal(solicitudes.at(-1).headers['idempotency-key'], `clave-${sufijo}`)
    assert.equal(solicitudes.at(-1).headers['x-csrf-token'], `csrf-${sufijo}`)
    assert.equal(solicitudes.at(-1).headers.cookie, 'JSESSIONID=SESION_SINTETICA')
  }

  const promocionConCorreo = await fetch(`${base}/api/v1/empleados/${idTexto}/operador/promocion`, {
    method: 'POST',
    headers: {
      cookie: 'JSESSIONID=SESION_SINTETICA',
      'content-type': 'application/json',
      'x-csrf-token': 'csrf-promocion-correo',
      'if-match': '"9007199254740993"',
      'idempotency-key': 'clave-promocion-correo',
    },
    body: JSON.stringify({ correo: 'nuevo@example.test' }),
  })
  assert.equal(promocionConCorreo.status, 200)
  assert.equal(solicitudes.at(-1).headers['if-match'], '"9007199254740993"')
  assert.equal(solicitudes.at(-1).headers['idempotency-key'], 'clave-promocion-correo')
  assert.equal(solicitudes.at(-1).headers['x-csrf-token'], 'csrf-promocion-correo')
  assert.deepEqual(JSON.parse(solicitudes.at(-1).body), { correo: 'nuevo@example.test' })

  const vinculacion = await fetch(`${base}/api/v1/empleados/${idTexto}/operador/vinculacion`, {
    method: 'POST',
    headers: {
      cookie: 'JSESSIONID=SESION_SINTETICA',
      'content-type': 'application/json',
      'x-csrf-token': 'csrf-vinculo',
      'if-match': '"9007199254740993"',
      'idempotency-key': 'clave-vinculo',
    },
    body: JSON.stringify({
      operadorId: '00000000-0000-4000-8000-000000000009',
      revisionOperador: '9223372036854775806',
      copiarCorreoOperador: true,
    }),
  })
  assert.equal(vinculacion.status, 200)
  assert.equal(solicitudes.at(-1).headers['if-match'], '"9007199254740993"')
  assert.equal(solicitudes.at(-1).headers['idempotency-key'], 'clave-vinculo')
  assert.equal(solicitudes.at(-1).headers['x-csrf-token'], 'csrf-vinculo')
  assert.equal(solicitudes.at(-1).headers.cookie, 'JSESSIONID=SESION_SINTETICA')
  assert.deepEqual(JSON.parse(solicitudes.at(-1).body), {
    operadorId: '00000000-0000-4000-8000-000000000009',
    revisionOperador: '9223372036854775806',
    copiarCorreoOperador: true,
  })

  const vinculacionSinCopia = await fetch(
    `${base}/api/v1/empleados/${idTexto}/operador/vinculacion`,
    {
      method: 'POST',
      headers: {
        cookie: 'JSESSIONID=SESION_SINTETICA',
        'content-type': 'application/json',
        'x-csrf-token': 'csrf-vinculo',
        'if-match': '"9007199254740993"',
        'idempotency-key': 'clave-vinculo-sin-copia',
      },
      body: JSON.stringify({
        operadorId: '00000000-0000-4000-8000-000000000009',
        revisionOperador: '9223372036854775806',
        copiarCorreoOperador: false,
      }),
    },
  )
  assert.equal(vinculacionSinCopia.status, 200)
  assert.equal(JSON.parse(solicitudes.at(-1).body).copiarCorreoOperador, false)

}
