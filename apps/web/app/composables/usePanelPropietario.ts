import { appendResponseHeader, getRequestHeader, setResponseHeader } from 'h3'

interface PanelApi {
  propietario: {
    nombres: string
    primerApellido?: string
    segundoApellido?: string | null
    apellidoPaterno?: string
    apellidoMaterno?: string | null
    correo: string
  }
  estacionamiento: {
    nombre: string
    tipo: string
    horario: {
      modo: string
      zonaHoraria: string
      horaApertura: string | null
      horaCierre: string | null
    }
  }
}

interface PanelWeb {
  propietario: { nombre: string; correo: string }
  estacionamiento: { nombre: string; tipo: string; horario: string }
}

export type ResultadoPanel =
  | { estado: 'listo'; datos: PanelWeb }
  | { estado: 'fallo'; sesionVencida: boolean }

/** Carga los datos del dueño y del estacionamiento usando la sesión de esta solicitud;
 * al preparar la página en el servidor, pide que la respuesta no se guarde ni se reutilice.
 */
export async function usePanelPropietario() {
  const fetchPanel = useRequestFetch()
  const {
    data: resultadoPanel,
    pending,
    refresh,
  } = await useAsyncData<ResultadoPanel>(
    'panel-dueno-web',
    async () => {
      try {
        const evento = import.meta.server ? useRequestEvent() : undefined
        const cookie = evento ? getRequestHeader(evento, 'cookie') : undefined
        if (evento) {
          setResponseHeader(evento, 'cache-control', 'no-store, private')
          setResponseHeader(evento, 'vary', 'Cookie')
        }
        const respuesta = await fetchPanel<PanelApi>('/api/v1/panel', {
          headers: cookie ? { cookie } : undefined,
          onResponse({ response }) {
            if (!evento) return
            for (const valor of response.headers.getSetCookie())
              appendResponseHeader(evento, 'set-cookie', valor)
          },
        })
        if (!respuesta) return { estado: 'fallo', sesionVencida: false }

        const { propietario, estacionamiento } = respuesta
        const { horario } = estacionamiento
        const primerApellido = propietario.primerApellido ?? propietario.apellidoPaterno
        const segundoApellido =
          propietario.segundoApellido !== undefined
            ? propietario.segundoApellido
            : propietario.apellidoMaterno
        const textoHorario =
          horario.modo === 'CONTINUO_24_7'
            ? 'Abierto las 24 horas'
            : `${horario.horaApertura ?? ''} a ${horario.horaCierre ?? ''} (hora local)`
        const tipoEstacionamiento =
          (
            {
              PUBLICO: 'Público',
              PRIVADO: 'Privado',
              MIXTO: 'Mixto',
            } as Record<string, string>
          )[estacionamiento.tipo] ?? 'No especificado'

        return {
          estado: 'listo',
          datos: {
            propietario: {
              nombre: [propietario.nombres, primerApellido, segundoApellido]
                .filter(Boolean)
                .join(' '),
              correo: propietario.correo,
            },
            estacionamiento: {
              nombre: estacionamiento.nombre,
              tipo: tipoEstacionamiento,
              horario: textoHorario,
            },
          },
        }
      } catch (fallo) {
        const codigo = (fallo as { statusCode?: number }).statusCode
        return { estado: 'fallo', sesionVencida: codigo === 401 }
      }
    },
    { default: () => ({ estado: 'fallo', sesionVencida: false }) as ResultadoPanel },
  )

  const panel = computed(() => resultadoPanel.value as ResultadoPanel)
  const nombreEstacionamiento = computed(() =>
    panel.value.estado === 'listo' ? panel.value.datos.estacionamiento.nombre : '',
  )

  return { panel, pending, refresh, nombreEstacionamiento }
}
