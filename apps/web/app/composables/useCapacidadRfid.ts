import { computed } from 'vue'
import { useClienteAccesos } from '~/utils/capacidad-rfid-api'

/** Muestra los espacios disponibles calculados a partir de las entradas registradas,
 * no de las imágenes de Vision, y actualiza el dato ante avisos de cambios de acceso o Vision.
 */
export function useCapacidadRfid() {
  const ruta = useRoute()
  const { sesion } = useSesion()
  const cliente = useClienteAccesos()
  const criterio = computed(() => {
    const actual = sesion.value
    if (actual.estado !== 'autenticada') return null
    const { rol, correo } = actual.identidad
    const rutaDueno = ruta.path === '/admin' || ruta.path === '/admin/vision'
    const rutaOperador = ruta.path === '/operador/monitoreo'
    return (rol === 'DUENO' && rutaDueno) || (rol === 'OPERADOR' && rutaOperador)
      ? rol + ':' + correo
      : null
  })

  return useConsultaAccesos({
    clave: 'capacidad-rfid:' + ruta.path,
    criterio,
    consultar: (signal) => cliente.capacidad(signal),
    temas: ['acceso.historial.actualizado', 'vision.ocupacion.actualizada'],
    inmediata: true,
  })
}
