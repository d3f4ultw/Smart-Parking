import { computed } from 'vue'

import type { ClienteIdentidad, RespuestaSesionCliente } from '~/utils/sesion-cliente'
import { obtenerEstadoErrorSesionCliente } from '~/utils/sesion-cliente'

const CLAVE_SESION_CLIENTE = 'sesion-cliente-actual'

function esRespuestaSesionCliente(valor: unknown): valor is RespuestaSesionCliente {
  if (valor === null || typeof valor !== 'object' || Array.isArray(valor)) {
    return false
  }

  const respuesta = valor as Record<string, unknown>
  const cliente = respuesta.cliente
  if (
    respuesta.autenticado !== true
    || cliente === null
    || typeof cliente !== 'object'
    || Array.isArray(cliente)
  ) {
    return false
  }

  const identidad = cliente as Record<string, unknown>
  return typeof identidad.nombre === 'string'
    && typeof identidad.apellido_paterno === 'string'
    && (identidad.apellido_materno === null || typeof identidad.apellido_materno === 'string')
    && typeof identidad.correo === 'string'
    && typeof identidad.correo_verificado === 'boolean'
}

export function useSesionCliente() {
  const fetchConCookies = useRequestFetch()
  const estadoSesion = useAsyncData<RespuestaSesionCliente | null>(
    CLAVE_SESION_CLIENTE,
    async () => {
      try {
        const respuesta: unknown = await fetchConCookies('/api/clientes/autenticacion/me', {
          credentials: 'same-origin',
          cache: 'no-store',
        })
        if (!esRespuestaSesionCliente(respuesta)) {
          throw createError({ statusCode: 502, statusMessage: 'Respuesta de sesión no válida' })
        }
        return respuesta
      } catch (error: unknown) {
        if (obtenerEstadoErrorSesionCliente(error) === 401) {
          return null
        }
        throw error
      }
    },
    {
      default: () => null,
      dedupe: 'defer',
      immediate: false,
    },
  )

  const cliente = computed<ClienteIdentidad | null>(
    () => estadoSesion.data.value?.cliente ?? null,
  )
  const autenticado = computed(() => estadoSesion.data.value?.autenticado === true)
  const cargando = computed(() => estadoSesion.status.value === 'pending')

  async function resolverSesion(opciones: { forzar?: boolean } = {}) {
    if (opciones.forzar) {
      await estadoSesion.refresh()
    } else if (estadoSesion.status.value === 'idle') {
      await estadoSesion.execute()
    }

    return autenticado.value && cliente.value !== null
  }

  async function refrescarSesion() {
    await estadoSesion.refresh()
    return autenticado.value && cliente.value !== null
  }

  function limpiarSesion() {
    estadoSesion.clear()
  }

  async function iniciarSesion(correo: string, contrasena: string) {
    await $fetch('/api/clientes/autenticacion/login', {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      body: { correo, contrasena },
    })
    return refrescarSesion()
  }

  async function cerrarSesion() {
    await $fetch('/api/clientes/autenticacion/logout', {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
    })
    limpiarSesion()
  }

  return {
    autenticado,
    cargando,
    cliente,
    cerrarSesion,
    iniciarSesion,
    limpiarSesion,
    refrescarSesion,
    resolverSesion,
  }
}
