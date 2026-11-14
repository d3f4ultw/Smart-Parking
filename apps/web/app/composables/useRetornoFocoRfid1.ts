export function crearRetornoFocoRfid1(buscarDestino: () => HTMLElement | null) {
  return (evento: Event) => {
    if (!import.meta.client) return
    const destino = buscarDestino()
    if (!destino) return
    evento.preventDefault()
    destino.focus()
  }
}
