type ObjetivoEventosPagina = Pick<EventTarget, 'addEventListener' | 'removeEventListener'>

export function crearCicloVidaVisor(
  objetivo: ObjetivoEventosPagina,
  alOcultar: () => void,
  alRestaurar: () => void,
) {
  let registrado = false

  const manejarOcultamiento = () => alOcultar()
  const manejarRestauracion = (evento: Event) => {
    if (!('persisted' in evento) || evento.persisted !== true) return
    alRestaurar()
  }

  function registrar() {
    if (registrado) return
    registrado = true
    objetivo.addEventListener('pagehide', manejarOcultamiento)
    objetivo.addEventListener('pageshow', manejarRestauracion)
  }

  function liberar() {
    if (!registrado) return
    registrado = false
    objetivo.removeEventListener('pagehide', manejarOcultamiento)
    objetivo.removeEventListener('pageshow', manejarRestauracion)
  }

  return { registrar, liberar }
}
