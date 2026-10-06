export function crearDebounceBusquedaOperadores(
  confirmar: (consulta: string) => void,
  demoraMs = 300,
) {
  let temporizador: ReturnType<typeof setTimeout> | undefined

  function cancelar() {
    if (temporizador !== undefined) {
      clearTimeout(temporizador)
      temporizador = undefined
    }
  }

  return {
    programar(consulta: string) {
      cancelar()
      temporizador = setTimeout(() => {
        temporizador = undefined
        confirmar(consulta)
      }, demoraMs)
    },
    cancelar,
  }
}
