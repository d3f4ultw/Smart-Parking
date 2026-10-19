export type PuntoNormalizado = readonly [number, number]

export type RectanguloImagen = {
  left: number
  top: number
  width: number
  height: number
}

export function calcularRectanguloContenido(
  anchoCaja: number,
  altoCaja: number,
  anchoImagen: number,
  altoImagen: number,
): RectanguloImagen | null {
  if ([anchoCaja, altoCaja, anchoImagen, altoImagen].some((valor) => !Number.isFinite(valor) || valor <= 0)) {
    return null
  }
  const escala = Math.min(anchoCaja / anchoImagen, altoCaja / altoImagen)
  const width = anchoImagen * escala
  const height = altoImagen * escala
  return { left: (anchoCaja - width) / 2, top: (altoCaja - height) / 2, width, height }
}

export type TransformacionVista = {
  escala?: number
  trasladoX?: number
  trasladoY?: number
}

export function puntoDesdePuntero(
  clientX: number,
  clientY: number,
  bounds: DOMRect,
  anchoImagen: number,
  altoImagen: number,
  transformacion: TransformacionVista = {},
): PuntoNormalizado | null {
  const contenido = calcularRectanguloContenido(bounds.width, bounds.height, anchoImagen, altoImagen)
  if (contenido === null) return null
  const escala = transformacion.escala ?? 1
  if (!Number.isFinite(escala) || escala < 1) return null
  const trasladoX = transformacion.trasladoX ?? 0
  const trasladoY = transformacion.trasladoY ?? 0
  if (!Number.isFinite(trasladoX) || !Number.isFinite(trasladoY)) return null

  // El editor aplica la misma transformación CSS a la imagen y al SVG.
  // Invertimos esa transformación antes de convertir a coordenadas normalizadas.
  const vistaX = clientX - bounds.left - bounds.width / 2
  const vistaY = clientY - bounds.top - bounds.height / 2
  const x = (vistaX - trasladoX * bounds.width) / escala + bounds.width / 2 - contenido.left
  const y = (vistaY - trasladoY * bounds.height) / escala + bounds.height / 2 - contenido.top
  if (x < 0 || y < 0 || x > contenido.width || y > contenido.height) return null
  return [Math.min(1, Math.max(0, x / contenido.width)), Math.min(1, Math.max(0, y / contenido.height))]
}

export function motivoPoligonoInvalido(puntos: readonly PuntoNormalizado[]): string | null {
  if (puntos.length < 4) {
    const faltan = 4 - puntos.length
    return `Marca ${faltan === 1 ? 'un punto más' : `${faltan} puntos más`}. El cajón necesita al menos 4 puntos.`
  }
  if (puntos.length > 128) return 'El cajón admite hasta 128 puntos. Deshaz un punto para continuar.'
  if (puntos.some(([x, y]) => !Number.isFinite(x) || !Number.isFinite(y) || x < 0 || x > 1 || y < 0 || y > 1)) {
    return 'Todos los puntos deben quedar dentro de la imagen.'
  }
  if (new Set(puntos.map(([x, y]) => `${x},${y}`)).size !== puntos.length) {
    return 'Hay puntos repetidos. Deshaz el último punto y márcalo de nuevo.'
  }
  const orientación = (a: PuntoNormalizado, b: PuntoNormalizado, c: PuntoNormalizado) =>
    (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
  const enSegmento = (a: PuntoNormalizado, b: PuntoNormalizado, p: PuntoNormalizado) =>
    Math.min(a[0], b[0]) - 1e-10 <= p[0] && p[0] <= Math.max(a[0], b[0]) + 1e-10
    && Math.min(a[1], b[1]) - 1e-10 <= p[1] && p[1] <= Math.max(a[1], b[1]) + 1e-10
  const intersecta = (a: PuntoNormalizado, b: PuntoNormalizado, c: PuntoNormalizado, d: PuntoNormalizado) => {
    const primero = orientación(a, b, c)
    const segundo = orientación(a, b, d)
    const tercero = orientación(c, d, a)
    const cuarto = orientación(c, d, b)
    if (((primero > 1e-10 && segundo < -1e-10) || (primero < -1e-10 && segundo > 1e-10))
      && ((tercero > 1e-10 && cuarto < -1e-10) || (tercero < -1e-10 && cuarto > 1e-10))) return true
    return (Math.abs(primero) <= 1e-10 && enSegmento(a, b, c))
      || (Math.abs(segundo) <= 1e-10 && enSegmento(a, b, d))
      || (Math.abs(tercero) <= 1e-10 && enSegmento(c, d, a))
      || (Math.abs(cuarto) <= 1e-10 && enSegmento(c, d, b))
  }

  for (let primero = 0; primero < puntos.length; primero += 1) {
    const siguientePrimero = (primero + 1) % puntos.length
    if (puntos[primero]![0] === puntos[siguientePrimero]![0]
      && puntos[primero]![1] === puntos[siguientePrimero]![1]) {
      return 'Hay dos puntos seguidos en el mismo lugar. Deshaz uno y vuelve a marcarlo.'
    }
    for (let segundo = primero + 1; segundo < puntos.length; segundo += 1) {
      const siguienteSegundo = (segundo + 1) % puntos.length
      if (siguientePrimero === segundo || siguienteSegundo === primero) continue
      if (intersecta(puntos[primero]!, puntos[siguientePrimero]!, puntos[segundo]!, puntos[siguienteSegundo]!)) {
        return 'Los lados del cajón se cruzan. Mueve o deshaz el punto que los cruza.'
      }
    }
  }
  const area = puntos.reduce((total, [x, y], indice) => {
    const [siguienteX, siguienteY] = puntos[(indice + 1) % puntos.length]!
    return total + x * siguienteY - siguienteX * y
  }, 0)
  if (Math.abs(area) <= 1e-10) return 'Los puntos no delimitan un área. Sepáralos para formar el cajón.'
  return null
}

export function validarPoligono(puntos: readonly PuntoNormalizado[]): boolean {
  return motivoPoligonoInvalido(puntos) === null
}

export function agregarPuntoPoligono(
  puntos: readonly PuntoNormalizado[],
  punto: PuntoNormalizado,
): PuntoNormalizado[] | null {
  if (puntos.length >= 128) return null
  return [...puntos, [punto[0], punto[1]]]
}

export function desplazarPuntoNormalizado(
  punto: PuntoNormalizado,
  deltaX: number,
  deltaY: number,
): PuntoNormalizado {
  const ajusteX = Number.isFinite(deltaX) ? deltaX : 0
  const ajusteY = Number.isFinite(deltaY) ? deltaY : 0
  return [
    Math.min(1, Math.max(0, punto[0] + ajusteX)),
    Math.min(1, Math.max(0, punto[1] + ajusteY)),
  ]
}
