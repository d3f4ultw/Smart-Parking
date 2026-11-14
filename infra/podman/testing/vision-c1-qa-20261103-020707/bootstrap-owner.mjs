import { randomUUID } from 'node:crypto'
import { request } from '@playwright/test'

const baseURL = process.env.QA_API_BASE_URL
const correo = process.env.QA_OWNER_EMAIL
const contrasena = process.env.QA_OWNER_PASSWORD
const contrasenaAdministrativa = process.env.QA_ADMIN_PASSWORD
if (!baseURL || !correo || !contrasena || !contrasenaAdministrativa) {
  throw new Error('Faltan parámetros sintéticos privados para el bootstrap DUENO.')
}

const cliente = await request.newContext({ baseURL })
async function leerTokenCsrf() {
  const csrf = await cliente.get('/api/v1/csrf')
  if (csrf.status() !== 200) throw new Error('La lectura CSRF devolvió HTTP ' + csrf.status() + '.')
  const cuerpo = await csrf.json()
  if (typeof cuerpo.token !== 'string' || cuerpo.token.length === 0) {
    throw new Error('La respuesta CSRF no contiene un token utilizable.')
  }
  return cuerpo.token
}

try {
  const estado = await cliente.get('/api/v1/configuracion/estado')
  if (estado.status() !== 200) {
    throw new Error('Estado de configuración HTTP ' + estado.status() + '.')
  }
  const cuerpoEstado = await estado.json()
  if (cuerpoEstado.estado === 'SIN_CONFIGURAR') {
    const respuesta = await cliente.post('/api/v1/configuracion/inicial', {
      headers: {
        'X-CSRF-TOKEN': await leerTokenCsrf(),
        'Idempotency-Key': randomUUID(),
      },
      data: {
        propietario: {
          nombres: 'Cuenta',
          primerApellido: 'Sintética',
          segundoApellido: null,
          correo,
          contrasenaAcceso: contrasena,
          contrasenaAdministrativa,
        },
        estacionamiento: {
          nombre: 'Estacionamiento QA Vision',
          tipo: 'PRIVADO',
          horario: {
            modo: 'CONTINUO_24_7',
            zonaHoraria: 'America/Mexico_City',
            horaApertura: null,
            horaCierre: null,
          },
        },
      },
    })
    if (respuesta.status() !== 201) {
      throw new Error('Bootstrap inicial HTTP ' + respuesta.status() + '.')
    }
    console.log('Bootstrap DUENO sintético: 201; PostgreSQL QA desechable.')
  } else if (cuerpoEstado.estado === 'CONFIGURADA') {
    const sesion = await cliente.post('/api/v1/sesion', {
      headers: { 'X-CSRF-TOKEN': await leerTokenCsrf() },
      data: { correo, contrasena },
    })
    if (sesion.status() !== 200) {
      throw new Error('La sesión sintética devolvió HTTP ' + sesion.status() + '.')
    }
    console.log('DUENO sintético existente validado en PostgreSQL QA desechable.')
  } else {
    throw new Error('Estado inicial inesperado: ' + String(cuerpoEstado.estado) + '.')
  }
} finally {
  await cliente.dispose()
}
