export function crearActualizadorCoalescido(actualizar: () => Promise<void>) {
  let actualizacionEnCurso: Promise<void> | null = null
  let actualizacionPendiente = false

  return function solicitarActualizacion(): Promise<void> {
    if (actualizacionEnCurso !== null) {
      actualizacionPendiente = true
      return actualizacionEnCurso
    }

    const ejecutar = async () => {
      do {
        actualizacionPendiente = false
        await actualizar()
      } while (actualizacionPendiente)
    }

    const promesa = ejecutar().finally(() => {
      if (actualizacionEnCurso === promesa) actualizacionEnCurso = null
    })
    actualizacionEnCurso = promesa
    return promesa
  }
}

export function puedeAplicarRevisionVision(
  revisionActual: number | null,
  revisionRecibida: number,
): boolean {
  return revisionActual === null || revisionRecibida >= revisionActual
}
