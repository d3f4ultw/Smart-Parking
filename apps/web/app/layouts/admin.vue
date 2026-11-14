<script setup lang="ts">
import { ErrorApi } from '~/utils/api'

const route = useRoute()
const { sesion, actualizar } = useSesion()
const autenticacion = useAutenticacion()
const menuMovil = useTemplateRef<HTMLDialogElement>('menuMovil')
const botonMenu = useTemplateRef<HTMLButtonElement>('botonMenu')
const menuMovilAbierto = ref(false)
const cerrando = ref(false)
const errorCierre = ref('')

const esDueno = computed(
  () => sesion.value?.estado === 'autenticada' && sesion.value.identidad.rol === 'DUENO',
)
const esOperador = computed(
  () => sesion.value?.estado === 'autenticada' && sesion.value.identidad.rol === 'OPERADOR',
)
const panelPropietario = esDueno.value ? await usePanelPropietario() : null
const nombreEstacionamiento = computed(() => panelPropietario?.nombreEstacionamiento.value ?? '')

if (panelPropietario) {
  if (
    panelPropietario.panel.value.estado === 'fallo' &&
    panelPropietario.panel.value.sesionVencida &&
    sesion.value.estado === 'autenticada'
  ) {
    await actualizar()
    if (sesion.value.estado !== 'autenticada') await navigateTo('/panel')
  }
}

const rutaMarca = computed(() => (esOperador.value ? '/operador/monitoreo' : '/admin'))
const etiquetaPanel = computed(() =>
  esOperador.value ? 'Panel del operador' : 'Panel del propietario',
)
type EnlaceNavegacionAdmin = {
  etiqueta: string
  ruta: string
  icono: string
  requiereDueno?: boolean
}
type SeccionNavegacionAdmin = { etiqueta: string; enlaces: EnlaceNavegacionAdmin[] }
const seccionesNavegacion = computed<SeccionNavegacionAdmin[]>(() => {
  if (esOperador.value) {
    return [
      {
        etiqueta: 'Operación',
        enlaces: [
          { etiqueta: 'Monitoreo', ruta: '/operador/monitoreo', icono: 'i-lucide-camera' },
          { etiqueta: 'Accesos', ruta: '/operador/accesos', icono: 'i-lucide-history' },
        ],
      },
      {
        etiqueta: 'Gestión',
        enlaces: [
          { etiqueta: 'Clientes', ruta: '/operador/clientes', icono: 'i-lucide-contact-round' },
          { etiqueta: 'Tarjetas', ruta: '/operador/tarjetas', icono: 'i-lucide-radio' },
        ],
      },
    ]
  }

  if (!esDueno.value) return []

  const secciones: SeccionNavegacionAdmin[] = [
    {
      etiqueta: 'Principal',
      enlaces: [{ etiqueta: 'Inicio', ruta: '/admin', icono: 'i-lucide-house' }],
    },
    {
      etiqueta: 'Operación',
      enlaces: [
        {
          etiqueta: 'Monitoreo',
          ruta: '/admin/vision',
          icono: 'i-lucide-camera',
          requiereDueno: true,
        },
        {
          etiqueta: 'Accesos',
          ruta: '/admin/accesos',
          icono: 'i-lucide-history',
          requiereDueno: true,
        },
      ],
    },
    {
      etiqueta: 'Gestión',
      enlaces: [
        {
          etiqueta: 'Clientes',
          ruta: '/admin/clientes',
          icono: 'i-lucide-contact-round',
          requiereDueno: true,
        },
        {
          etiqueta: 'Empleados',
          ruta: '/admin/empleados',
          icono: 'i-lucide-users-round',
        },
        {
          etiqueta: 'Tarjetas',
          ruta: '/admin/tarjetas-rfid',
          icono: 'i-lucide-radio',
          requiereDueno: true,
        },
        {
          etiqueta: 'Operadores',
          ruta: '/admin/operadores',
          icono: 'i-lucide-user-round',
          requiereDueno: true,
        },
      ],
    },
  ]

  return secciones
    .map((seccion) => ({
      ...seccion,
      enlaces: seccion.enlaces.filter((enlace) => !enlace.requiereDueno || esDueno.value),
    }))
    .filter((seccion) => seccion.enlaces.length > 0)
})
const titulo = computed(() => {
  if (route.path === '/operador/monitoreo') return 'Monitoreo'
  if (route.path === '/operador/tarjetas') return 'Tarjetas'
  if (route.path === '/operador/clientes') return 'Clientes'
  if (route.path === '/operador/accesos') return 'Historial de accesos'
  if (route.path === '/admin/vision') return 'Monitoreo'
  if (route.path === '/admin/tarjetas-rfid') return 'Tarjetas'
  if (route.path === '/admin/empleados') return 'Empleados'
  if (route.path === '/admin/clientes') return 'Clientes'
  if (route.path === '/admin/operadores') return 'Operadores'
  if (route.path === '/admin/accesos') return 'Historial de accesos'
  return 'Inicio'
})
const rolVisible = computed(() => {
  if (sesion.value?.estado !== 'autenticada') return ''
  return sesion.value.identidad.rol === 'DUENO' ? 'Propietario' : 'Operador'
})

function abrirMenuMovil() {
  if (!menuMovil.value || menuMovil.value.open) return
  menuMovil.value.showModal()
  menuMovilAbierto.value = true
}

function cerrarMenuMovil() {
  if (menuMovil.value?.open) menuMovil.value.close()
  menuMovilAbierto.value = false
  botonMenu.value?.focus()
}

function sincronizarMenuMovil() {
  menuMovilAbierto.value = false
}

async function cerrarSesion() {
  cerrando.value = true
  errorCierre.value = ''
  try {
    await autenticacion.cerrar()
  } catch (fallo) {
    errorCierre.value =
      fallo instanceof ErrorApi && fallo.codigo === 'CSRF_RECHAZADO'
        ? 'Tu acceso venció. Inicia sesión de nuevo.'
        : 'No pudimos cerrar tu acceso. Revisa tu conexión e inténtalo de nuevo.'
  } finally {
    cerrando.value = false
  }
}

async function cerrarSesionDesdeMenuMovil() {
  cerrarMenuMovil()
  await cerrarSesion()
}
</script>

<template>
  <main class="layout-admin">
    <aside class="barra-lateral-admin" aria-label="Navegación principal">
      <div class="identidad-estacionamiento-admin">
        <NuxtLink
          :to="rutaMarca"
          class="marca-admin"
          :aria-label="esOperador ? 'Smart Parking, Monitoreo' : 'Smart Parking, Inicio'"
        >
          <UIcon name="i-lucide-square-parking" class="icono-marca-admin" aria-hidden="true" />
          <span>SMART PARKING</span>
        </NuxtLink>
        <p v-if="nombreEstacionamiento" class="nombre-estacionamiento-admin">
          {{ nombreEstacionamiento }}
        </p>
      </div>

      <nav class="navegacion-admin" aria-label="Principal">
        <section
          v-for="seccion in seccionesNavegacion"
          :key="seccion.etiqueta"
          class="grupo-nav-admin"
          :aria-label="seccion.etiqueta"
        >
          <h2 class="etiqueta-grupo-nav-admin">{{ seccion.etiqueta }}</h2>
          <NuxtLink
            v-for="enlace in seccion.enlaces"
            :key="enlace.ruta"
            :to="enlace.ruta"
            class="enlace-nav-admin"
            :aria-current="route.path === enlace.ruta ? 'page' : undefined"
          >
            <UIcon :name="enlace.icono" aria-hidden="true" />
            <span>{{ enlace.etiqueta }}</span>
          </NuxtLink>
        </section>
      </nav>

      <details v-if="sesion?.estado === 'autenticada'" class="menu-perfil-admin">
        <summary class="perfil-admin">
          <span class="avatar-perfil-admin" aria-hidden="true">
            <UIcon name="i-lucide-user-round" />
          </span>
          <span class="datos-perfil-admin">
            <span class="rol-perfil-admin">{{ rolVisible }}</span>
            <span class="correo-perfil-admin">{{ sesion.identidad.correo }}</span>
          </span>
          <UIcon name="i-lucide-chevron-up" class="indicador-perfil-admin" aria-hidden="true" />
        </summary>
        <div class="acciones-perfil-admin">
          <button
            type="button"
            class="accion-cierre-admin"
            :disabled="cerrando"
            aria-label="Cerrar sesión"
            :aria-busy="cerrando"
            @click="cerrarSesion"
          >
            <UIcon name="i-lucide-log-out" aria-hidden="true" />
            <span>{{ cerrando ? 'Cerrando sesión…' : 'Cerrar sesión' }}</span>
          </button>
        </div>
      </details>
    </aside>

    <div class="contenido-admin">
      <header class="encabezado-admin">
        <button
          ref="botonMenu"
          class="boton-menu-admin"
          type="button"
          aria-label="Abrir navegación"
          aria-haspopup="dialog"
          :aria-expanded="menuMovilAbierto"
          aria-controls="menu-movil-admin"
          @click="abrirMenuMovil"
        >
          <UIcon name="i-lucide-menu" aria-hidden="true" />
        </button>
        <div class="titulo-encabezado-admin">
          <p class="sobrelinea">{{ etiquetaPanel }}</p>
          <h1>{{ titulo }}</h1>
        </div>
      </header>
      <p v-if="errorCierre" class="mensaje-error" role="alert">{{ errorCierre }}</p>
      <slot />
    </div>

    <dialog
      id="menu-movil-admin"
      ref="menuMovil"
      class="drawer-admin"
      aria-labelledby="titulo-menu-movil"
      @cancel.prevent="cerrarMenuMovil"
      @click.self="cerrarMenuMovil"
      @close="sincronizarMenuMovil"
    >
      <div class="contenido-drawer-admin">
        <header class="cabecera-drawer-admin">
          <div id="titulo-menu-movil" class="identidad-estacionamiento-admin">
            <NuxtLink
              :to="rutaMarca"
              class="marca-admin"
              :aria-label="esOperador ? 'Smart Parking, Monitoreo' : 'Smart Parking, Inicio'"
            >
              <UIcon name="i-lucide-square-parking" class="icono-marca-admin" aria-hidden="true" />
              <span>SMART PARKING</span>
            </NuxtLink>
            <p v-if="nombreEstacionamiento" class="nombre-estacionamiento-admin">
              {{ nombreEstacionamiento }}
            </p>
          </div>
          <UButton
            color="neutral"
            variant="ghost"
            icon="i-lucide-x"
            aria-label="Cerrar navegación"
            autofocus
            @click="cerrarMenuMovil"
          />
        </header>
        <nav class="navegacion-admin" aria-label="Principal">
          <section
            v-for="seccion in seccionesNavegacion"
            :key="seccion.etiqueta"
            class="grupo-nav-admin"
            :aria-label="seccion.etiqueta"
          >
            <h2 class="etiqueta-grupo-nav-admin">{{ seccion.etiqueta }}</h2>
            <NuxtLink
              v-for="enlace in seccion.enlaces"
              :key="enlace.ruta"
              :to="enlace.ruta"
              class="enlace-nav-admin"
              :aria-current="route.path === enlace.ruta ? 'page' : undefined"
              @click="cerrarMenuMovil"
            >
              <UIcon :name="enlace.icono" aria-hidden="true" />
              <span>{{ enlace.etiqueta }}</span>
            </NuxtLink>
          </section>
        </nav>
        <details v-if="sesion?.estado === 'autenticada'" class="menu-perfil-admin">
          <summary class="perfil-admin">
            <span class="avatar-perfil-admin" aria-hidden="true">
              <UIcon name="i-lucide-user-round" />
            </span>
            <span class="datos-perfil-admin">
              <span class="rol-perfil-admin">{{ rolVisible }}</span>
              <span class="correo-perfil-admin">{{ sesion.identidad.correo }}</span>
            </span>
            <UIcon name="i-lucide-chevron-up" class="indicador-perfil-admin" aria-hidden="true" />
          </summary>
          <div class="acciones-perfil-admin">
            <button
              type="button"
              class="accion-cierre-admin"
              :disabled="cerrando"
              aria-label="Cerrar sesión"
              :aria-busy="cerrando"
              @click="cerrarSesionDesdeMenuMovil"
            >
              <UIcon name="i-lucide-log-out" aria-hidden="true" />
              <span>{{ cerrando ? 'Cerrando sesión…' : 'Cerrar sesión' }}</span>
            </button>
          </div>
        </details>
      </div>
    </dialog>
  </main>
</template>
