<script setup lang="ts">
import ResumenPortal from '~/components/clientes/ResumenPortal.vue'
import { ErrorClienteApi, CLAVE_PORTAL_CLIENTE, useClienteApi } from '~/utils/cliente-api'
import type { PortalCliente } from '~/types/cliente'

/** Carga el perfil y la membresía del cliente; también permite cambiar la contraseña
 * y cerrar la sesión.
 */
definePageMeta({ layout: 'cliente', middleware: 'cliente-sesion' })

type SeccionPortal = 'cuenta' | 'membresia' | 'contrasena'

const route = useRoute()
const seccionesPortal: Array<{ id: SeccionPortal; etiqueta: string; icono: string }> = [
  { id: 'cuenta', etiqueta: 'Mi cuenta', icono: 'i-lucide-user-round' },
  { id: 'membresia', etiqueta: 'Membresía', icono: 'i-lucide-wallet-cards' },
  { id: 'contrasena', etiqueta: 'Cambiar contraseña', icono: 'i-lucide-key-round' },
]
const seccionActual = computed<SeccionPortal>(() => {
  const seccion = route.query.seccion
  return seccion === 'membresia' || seccion === 'contrasena' ? seccion : 'cuenta'
})
const tituloSeccion = computed(
  () =>
    seccionesPortal.find((seccion) => seccion.id === seccionActual.value)?.etiqueta ?? 'Mi cuenta',
)
const menuCuenta = useTemplateRef<HTMLDetailsElement>('menuCuenta')

interface PortalVisible {
  cliente: Pick<
    PortalCliente['cliente'],
    'nombres' | 'primerApellido' | 'segundoApellido' | 'correo'
  >
  membresia: Omit<PortalCliente['membresia'], 'plan'> & {
    plan: Pick<
      PortalCliente['membresia']['plan'],
      'nombre' | 'importeMenorUnidad' | 'moneda' | 'intervalo' | 'intervaloCantidad'
    >
  }
}

const api = useClienteApi()
const sesion = useSesionCliente()
const csrf = useCsrfCliente()
const {
  data: portal,
  error: errorPortal,
  pending,
  refresh,
} = await useAsyncData<PortalVisible | null>(
  CLAVE_PORTAL_CLIENTE,
  async () => {
    const respuesta = await api.consultarPortal()
    return {
      cliente: {
        nombres: respuesta.cliente.nombres,
        primerApellido: respuesta.cliente.primerApellido,
        segundoApellido: respuesta.cliente.segundoApellido,
        correo: respuesta.cliente.correo,
      },
      membresia: {
        estado: respuesta.membresia.estado,
        plan: {
          nombre: respuesta.membresia.plan.nombre,
          importeMenorUnidad: respuesta.membresia.plan.importeMenorUnidad,
          moneda: respuesta.membresia.plan.moneda,
          intervalo: respuesta.membresia.plan.intervalo,
          intervaloCantidad: respuesta.membresia.plan.intervaloCantidad ?? 1,
        },
        periodoInicio: respuesta.membresia.periodoInicio,
        periodoFin: respuesta.membresia.periodoFin,
        siguienteCobroEn: respuesta.membresia.siguienteCobroEn,
        cancelacionAlFinal: respuesta.membresia.cancelacionAlFinal,
        puedeComprar: respuesta.membresia.puedeComprar,
        checkoutPendiente: respuesta.membresia.checkoutPendiente
          ? {
              intentoId: respuesta.membresia.checkoutPendiente.intentoId,
              estado: respuesta.membresia.checkoutPendiente.estado,
              expiraEn: respuesta.membresia.checkoutPendiente.expiraEn,
            }
          : null,
      },
    }
  },
  { default: () => null, dedupe: 'defer' },
)

if (errorPortal.value instanceof ErrorClienteApi && errorPortal.value.estado === 401) {
  sesion.limpiar()
  await navigateTo('/clientes/acceso')
}

const cerrandoSesion = ref(false)
const actualizandoContrasena = ref(false)
const errorAccion = ref('')
const errorContrasena = ref('')
const contrasenaActual = ref('')
const contrasenaNueva = ref('')
const confirmarContrasena = ref('')
const nombreCompleto = computed(() => {
  const cliente = portal.value?.cliente
  if (!cliente) return 'Cuenta cliente'
  return [cliente.nombres, cliente.primerApellido, cliente.segundoApellido]
    .filter(Boolean)
    .join(' ')
})

function rutaSeccion(seccion: SeccionPortal) {
  return seccion === 'cuenta'
    ? '/clientes/portal'
    : { path: '/clientes/portal', query: { seccion } }
}

function cerrarMenuCuenta() {
  const menu = menuCuenta.value
  if (!menu?.open) return
  menu.open = false
  menu.querySelector('summary')?.focus()
}

async function cerrarSesion() {
  if (cerrandoSesion.value) return
  cerrandoSesion.value = true
  errorAccion.value = ''
  try {
    await api.cerrarSesion(await csrf.obtener())
    sesion.limpiar()
    await navigateTo('/clientes/acceso?salida=1')
  } catch (fallo) {
    csrf.manejarFallo(fallo)
    if (fallo instanceof ErrorClienteApi && fallo.estado === 401) {
      sesion.limpiar()
      await navigateTo('/clientes/acceso?salida=1')
    } else {
      errorAccion.value = 'No pudimos cerrar tu sesión. Inténtalo de nuevo.'
    }
  } finally {
    cerrandoSesion.value = false
  }
}

async function cambiarContrasena() {
  errorContrasena.value = ''
  if (actualizandoContrasena.value) return
  if (Array.from(contrasenaNueva.value).length < 10) {
    errorContrasena.value = 'La contraseña nueva debe tener al menos 10 caracteres.'
    return
  }
  if (contrasenaNueva.value !== confirmarContrasena.value) {
    errorContrasena.value = 'Las contraseñas nuevas no coinciden.'
    return
  }

  actualizandoContrasena.value = true
  try {
    await api.cambiarContrasena(
      { contrasenaActual: contrasenaActual.value, nuevaContrasena: contrasenaNueva.value },
      await csrf.obtener(),
    )
    contrasenaActual.value = ''
    contrasenaNueva.value = ''
    confirmarContrasena.value = ''
    sesion.limpiar()
    await navigateTo('/clientes/acceso?contrasena=actualizada')
  } catch (fallo) {
    csrf.manejarFallo(fallo)
    if (fallo instanceof ErrorClienteApi && fallo.estado === 401) {
      sesion.limpiar()
      await navigateTo('/clientes/acceso')
    } else {
      errorContrasena.value =
        fallo instanceof ErrorClienteApi
          ? fallo.message
          : 'No pudimos actualizar la contraseña. Inténtalo de nuevo.'
    }
  } finally {
    actualizandoContrasena.value = false
  }
}

useHead({
  title: computed(() => `${tituloSeccion.value} | Smart Parking`),
  meta: [{ name: 'referrer', content: 'no-referrer' }],
})
</script>

<template>
  <main class="layout-portal-cliente">
    <aside class="barra-lateral-portal" aria-label="Navegación del portal cliente">
      <NuxtLink class="marca-portal" to="/clientes/portal" aria-label="Smart Parking, Mi cuenta">
        <span class="simbolo-marca-portal" aria-hidden="true">
          <UIcon name="i-lucide-square-parking" />
        </span>
        <span>SMART PARKING</span>
      </NuxtLink>

      <nav class="navegacion-portal" aria-label="Secciones del portal">
        <NuxtLink
          v-for="seccion in seccionesPortal"
          :key="seccion.id"
          :to="rutaSeccion(seccion.id)"
          class="enlace-portal"
          :aria-current="seccionActual === seccion.id ? 'page' : undefined"
        >
          <UIcon :name="seccion.icono" aria-hidden="true" />
          <span>{{ seccion.etiqueta }}</span>
        </NuxtLink>
      </nav>

      <details ref="menuCuenta" class="perfil-portal" @keydown.esc.prevent="cerrarMenuCuenta">
        <summary class="activador-perfil-portal">
          <span class="avatar-perfil-portal" aria-hidden="true">
            <UIcon name="i-lucide-user-round" />
          </span>
          <span class="datos-perfil-portal">
            <span class="nombre-perfil-portal">{{ nombreCompleto }}</span>
            <span class="correo-perfil-portal">{{
              portal?.cliente.correo || 'Cuenta cliente'
            }}</span>
          </span>
          <UIcon name="i-lucide-chevron-up" class="indicador-perfil-portal" aria-hidden="true" />
        </summary>
        <div class="acciones-perfil-portal">
          <button
            type="button"
            class="accion-cierre-portal"
            :disabled="cerrandoSesion"
            :aria-busy="cerrandoSesion"
            @click="cerrarSesion"
          >
            <UIcon name="i-lucide-log-out" aria-hidden="true" />
            <span>{{ cerrandoSesion ? 'Cerrando sesión…' : 'Cerrar sesión' }}</span>
          </button>
        </div>
      </details>
    </aside>

    <div class="contenido-portal">
      <header class="encabezado-portal-cliente">
        <p class="sobrelinea-portal">Portal personal</p>
        <h1>{{ tituloSeccion }}</h1>
      </header>

      <p v-if="errorAccion" class="error-portal" role="alert">{{ errorAccion }}</p>
      <p v-if="pending" class="estado-portal" role="status">Cargando tu información…</p>
      <section v-else-if="!portal" class="panel-portal error-lectura" role="alert">
        <h2>No pudimos cargar tu información</h2>
        <p>Revisa tu conexión e inténtalo de nuevo.</p>
        <UButton :loading="pending" :disabled="pending" @click="refresh()">
          Volver a intentar
        </UButton>
      </section>
      <template v-else>
        <ResumenPortal
          v-if="seccionActual !== 'contrasena'"
          :portal="portal"
          :seccion="seccionActual"
        />

        <section
          v-else
          class="panel-portal panel-contrasena"
          aria-labelledby="titulo-formulario-contrasena"
        >
          <div>
            <h2 id="titulo-formulario-contrasena">Actualiza tu contraseña</h2>
            <p class="texto-seguridad">
              Después del cambio, inicia sesión de nuevo en tus dispositivos.
            </p>
          </div>
          <form
            class="formulario-contrasena"
            :aria-busy="actualizandoContrasena"
            @submit.prevent="cambiarContrasena"
          >
            <div class="campo-portal">
              <label for="contrasena-actual">Contraseña actual</label>
              <UInput
                id="contrasena-actual"
                v-model="contrasenaActual"
                type="password"
                autocomplete="current-password"
                required
                :disabled="actualizandoContrasena"
              />
            </div>
            <div class="campo-portal">
              <label for="contrasena-nueva">Contraseña nueva</label>
              <UInput
                id="contrasena-nueva"
                v-model="contrasenaNueva"
                type="password"
                autocomplete="new-password"
                required
                :disabled="actualizandoContrasena"
                aria-describedby="ayuda-contrasena-nueva"
              />
              <p id="ayuda-contrasena-nueva">Usa al menos 10 caracteres.</p>
            </div>
            <div class="campo-portal">
              <label for="confirmar-contrasena-nueva">Confirmar contraseña nueva</label>
              <UInput
                id="confirmar-contrasena-nueva"
                v-model="confirmarContrasena"
                type="password"
                autocomplete="new-password"
                required
                :disabled="actualizandoContrasena"
                :aria-invalid="Boolean(errorContrasena)"
                :aria-describedby="errorContrasena ? 'error-contrasena-nueva' : undefined"
              />
            </div>
            <p v-if="errorContrasena" id="error-contrasena-nueva" class="error-portal" role="alert">
              {{ errorContrasena }}
            </p>
            <UButton
              type="submit"
              :loading="actualizandoContrasena"
              :disabled="actualizandoContrasena"
            >
              Actualizar contraseña
            </UButton>
          </form>
        </section>
      </template>
    </div>
  </main>
</template>

<style src="~/assets/css/cliente-portal.css"></style>
