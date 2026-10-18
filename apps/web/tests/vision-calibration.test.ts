import assert from 'node:assert/strict'
import test from 'node:test'

import {
  agregarPuntoPoligono,
  calcularRectanguloContenido,
  desplazarPuntoNormalizado,
  motivoPoligonoInvalido,
  puntoDesdePuntero,
  validarPoligono,
} from '../app/utils/vision-calibracion.ts'
import {
  LIMITE_SIN_AVANCE_RAW_VISION_MS,
  RETRASOS_RECONEXION_RAW_VISION_MS,
  estadoTrasConfirmarGuardado,
  puedeMantenerStreamCrudoVision,
  puedeNavegarDuranteGuardado,
  retrasoReconexionRawVision,
  sincronizacionTrasGuardadoResuelta,
  streamRawVisionSinProgreso,
} from '../app/utils/vision-calibration-recovery.ts'
import { readFileSync } from 'node:fs'
import { colorVisionZona, matizVisionZona } from '../app/utils/vision-zone-colors.ts'
import { crearActualizadorCoalescido, puedeAplicarRevisionVision } from '../app/utils/vision-config-refresh.ts'
import {
  escucharCambioConfiguracionVision,
  esCambioConfiguracionRemoto,
  notificarCambioConfiguracionVision,
} from '../app/utils/vision-config-sync.ts'
import {
  abrirEditorVision,
  urlEditorVision,
} from '../app/utils/vision-zone-actions.ts'
import {
  VIGENCIA_RESERVA_EDITOR_MS,
  claveReservaEditorVision,
  editorVisionYaAbierto,
  guardarReservaEditorVision,
  liberarReservaEditorVision,
} from '../app/utils/vision-editor-tabs.ts'

test('maps normalized points inside a letterboxed image and rejects clicks in the bars', () => {
  const bounds = { left: 20, top: 10, width: 800, height: 800 } as DOMRect
  const content = calcularRectanguloContenido(800, 800, 1600, 900)
  assert.deepEqual(content, { left: 0, top: 175, width: 800, height: 450 })
  assert.deepEqual(puntoDesdePuntero(420, 410, bounds, 1600, 900), [0.5, 0.5])
  assert.equal(puntoDesdePuntero(420, 100, bounds, 1600, 900), null)
  assert.equal(puntoDesdePuntero(900, 410, bounds, 1600, 900), null)
})

test('keeps created, dragged, edited, and reloaded polygons aligned across responsive 16:9 frames', () => {
  const puntoEnImagen = (x: number, y: number, ancho: number, alto: number) =>
    puntoDesdePuntero(
      ancho * x,
      alto * y,
      { left: 0, top: 0, width: ancho, height: alto } as DOMRect,
      ancho,
      alto,
    )
  const tamanos = [
    [1280, 720],
    [960, 540],
    [640, 360],
  ] as const
  const esperado = [0.72, 0.68]
  const mapeados = tamanos.map(([ancho, alto]) =>
    puntoEnImagen(0.72, 0.68, ancho, alto),
  )
  assert.deepEqual(mapeados, [esperado, esperado, esperado])

  const poligonoCreado = [
    puntoEnImagen(0.15, 0.2, 1280, 720),
    puntoEnImagen(0.8, 0.2, 1280, 720),
    puntoEnImagen(0.8, 0.75, 1280, 720),
    puntoEnImagen(0.15, 0.75, 1280, 720),
  ]
  assert.ok(poligonoCreado.every((punto): punto is NonNullable<typeof punto> => punto !== null))
  assert.equal(validarPoligono(poligonoCreado), true)

  const poligonoEditado = poligonoCreado.map((punto) => [...punto] as [number, number])
  poligonoEditado[2] = puntoEnImagen(0.72, 0.68, 1280, 720)!
  poligonoEditado[1] = puntoEnImagen(0.78, 0.24, 1280, 720)!
  assert.equal(validarPoligono(poligonoEditado), true)

  const guardado = JSON.stringify({ polygon: poligonoEditado })
  const recargado = JSON.parse(guardado) as { polygon: [number, number][] }
  assert.deepEqual(recargado.polygon, poligonoEditado)
  assert.deepEqual(
    puntoEnImagen(recargado.polygon[2]![0], recargado.polygon[2]![1], 640, 360),
    esperado,
  )
  assert.equal(1280 / 720, 960 / 540)
})

test('keeps polygon validation within normalized coordinates and the vertex limit', () => {
  assert.equal(validarPoligono([[0.1, 0.1], [0.8, 0.1], [0.8, 0.8], [0.1, 0.8]]), true)
  assert.equal(validarPoligono([[0, 0], [0.5, 0.5], [1, 1]]), false)
  assert.equal(validarPoligono([[0, 0], [1.1, 0], [1, 1]]), false)
  assert.equal(validarPoligono([[0, 0], [1, 1], [0, 1], [1, 0]]), false)
  const muchosVertices = Array.from({ length: 129 }, (_, index) => [0.5 + Math.cos(index) * 0.4, 0.5 + Math.sin(index) * 0.4] as [number, number])
  assert.equal(validarPoligono(muchosVertices), false)
})

test('explains incomplete, repeated, crossed, and area-free drawings', () => {
  assert.match(motivoPoligonoInvalido([[0.1, 0.1], [0.8, 0.2], [0.5, 0.8]]) ?? '', /Marca un punto más/)
  assert.match(motivoPoligonoInvalido([[0.1, 0.1], [0.8, 0.1], [0.8, 0.8], [0.1, 0.1]]) ?? '', /puntos repetidos/)
  assert.match(motivoPoligonoInvalido([[0.1, 0.1], [0.9, 0.9], [0.1, 0.9], [0.9, 0.1]]) ?? '', /lados del cajón se cruzan/)
  assert.match(motivoPoligonoInvalido([[0.1, 0.1], [0.1000001, 0.1], [0.1000001, 0.1000001], [0.1, 0.1000001]]) ?? '', /no delimitan un área/)
  assert.equal(motivoPoligonoInvalido([[0.1, 0.1], [0.8, 0.1], [0.8, 0.8], [0.1, 0.8]]), null)
})

test('keeps rapid successive drawing clicks and accepts four or more points', () => {
  let vertices: readonly [number, number][] = []
  const puntos = [
    [0.15, 0.2],
    [0.8, 0.2],
    [0.85, 0.55],
    [0.7, 0.8],
    [0.2, 0.75],
  ] as const
  for (const punto of puntos) {
    const siguiente = agregarPuntoPoligono(vertices, punto)
    assert.ok(siguiente)
    vertices = siguiente
  }
  assert.equal(validarPoligono(vertices), true)
  assert.equal(vertices.length, 5)
  assert.equal(agregarPuntoPoligono(Array.from({ length: 128 }, () => [0.5, 0.5] as [number, number]), [0.4, 0.4]), null)

  const editor = readFileSync(new URL('../app/pages/admin/vision/calibracion/editor.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(editor, /evento\.detail\s*>\s*1/)
})

test('moves keyboard-adjusted points in normalized coordinates and keeps them in the image', () => {
  assert.deepEqual(desplazarPuntoNormalizado([0.5, 0.5], 1 / 1280, -1 / 720), [0.50078125, 0.4986111111111111])
  assert.deepEqual(desplazarPuntoNormalizado([0.001, 0.999], -0.01, 0.01), [0, 1])
  assert.deepEqual(desplazarPuntoNormalizado([0.5, 0.5], Number.NaN, Number.POSITIVE_INFINITY), [0.5, 0.5])
})

test('shows connection recovery only after a raw stream stops delivering frames', () => {
  assert.equal(streamRawVisionSinProgreso({
    ahora: 10_000,
    ultimoFrameMostrado: 3_000,
    inicioStream: 1_000,
    streamSolicitado: true,
    limiteSinAvance: LIMITE_SIN_AVANCE_RAW_VISION_MS,
  }), true)
  assert.equal(streamRawVisionSinProgreso({
    ahora: 10_000,
    ultimoFrameMostrado: 9_000,
    inicioStream: 1_000,
    streamSolicitado: true,
    limiteSinAvance: LIMITE_SIN_AVANCE_RAW_VISION_MS,
  }), false)
  assert.equal(streamRawVisionSinProgreso({
    ahora: 10_000,
    ultimoFrameMostrado: 0,
    inicioStream: 9_500,
    streamSolicitado: false,
    limiteSinAvance: LIMITE_SIN_AVANCE_RAW_VISION_MS,
  }), false)
})

test('keeps the raw MJPEG subscription while source freshness catches up after a mutation', () => {
  assert.equal(puedeMantenerStreamCrudoVision({
    mode: 'camera',
    source_connected: false,
    frame_fresh: false,
  }), true)
  assert.equal(puedeMantenerStreamCrudoVision({
    mode: 'simulation',
    source_connected: true,
    frame_fresh: true,
  }), false)

  const editor = readFileSync(new URL('../app/pages/admin/vision/calibracion/editor.vue', import.meta.url), 'utf8')
  assert.match(editor, /const camaraVigente = puedeMantenerStreamCrudoVision\(estado\)/)
  assert.match(editor, /camaraConfigurada\.value = camaraVigente/)
  assert.match(editor, /frameFuenteFresco\.value = camaraVigente && estado\.frame_fresh/)
  assert.match(editor, /watch\(\[\(\) => vision\.autorizado\.value, camaraConfigurada\]/)
  assert.doesNotMatch(editor, /watch\(\[\(\) => vision\.autorizado\.value, fuenteConectada\]/)
})

test('bounds calibration stream retries and navigation only during a write', () => {
  assert.deepEqual(
    RETRASOS_RECONEXION_RAW_VISION_MS.map((_, intento) => retrasoReconexionRawVision(intento)),
    [500, 1000, 2000, 4000, 8000],
  )
  assert.equal(retrasoReconexionRawVision(99), 8000)
  assert.equal(puedeNavegarDuranteGuardado('guardando'), false)
  assert.equal(puedeNavegarDuranteGuardado('eliminando'), false)
  assert.equal(puedeNavegarDuranteGuardado('aplicando'), true)
})

test('waits for the saved revision and fresh source frames without fake timers', () => {
  assert.equal(estadoTrasConfirmarGuardado(4, 3, true), 'aplicando')
  assert.equal(estadoTrasConfirmarGuardado(4, null, false), 'aplicando')
  assert.equal(estadoTrasConfirmarGuardado(4, 4, false), 'recuperando')
  assert.equal(estadoTrasConfirmarGuardado(4, 4, true), 'listo')
  assert.equal(sincronizacionTrasGuardadoResuelta('aplicando', 4, 3, true, true), false)
  assert.equal(sincronizacionTrasGuardadoResuelta('aplicando', 4, 4, false, false), false)
  assert.equal(sincronizacionTrasGuardadoResuelta('recuperando', 4, 4, true, true), true)
  assert.equal(sincronizacionTrasGuardadoResuelta('listo', 4, 4, true, true), false)
})


test('keeps normalized pointer mapping accurate across responsive zoom and pan', () => {
  const esperado = [0.38, 0.58] as const
  const transformacion = { escala: 2.25, trasladoX: 0.15, trasladoY: -0.12 }
  const tamanos = [[1280, 720], [960, 540], [480, 270]] as const
  for (const [width, height] of tamanos) {
    const bounds = { left: 29, top: 47, width, height } as DOMRect
    const clientX = bounds.left + (((esperado[0] - 0.5) * transformacion.escala + 0.5 + transformacion.trasladoX) * width)
    const clientY = bounds.top + (((esperado[1] - 0.5) * transformacion.escala + 0.5 + transformacion.trasladoY) * height)
    const mapped = puntoDesdePuntero(clientX, clientY, bounds, 1280, 720, transformacion)
    assert.ok(mapped)
    assert.ok(Math.abs(mapped[0] - esperado[0]) < 1e-12)
    assert.ok(Math.abs(mapped[1] - esperado[1]) < 1e-12)
  }

  const bounds = { left: 0, top: 0, width: 1280, height: 720 } as DOMRect
  assert.deepEqual(
    puntoDesdePuntero(20, 360, bounds, 1280, 720, { escala: 2 }),
    [0.2578125, 0.5],
  )
})

test('assigns stable high-contrast zone colors independently of order and occupancy', () => {
  assert.equal(colorVisionZona(1), 'hsl(0 78% 56%)')
  assert.equal(colorVisionZona(2), 'hsl(137.508 78% 56%)')
  assert.equal(colorVisionZona(1), colorVisionZona(1))
  assert.notEqual(colorVisionZona(1), colorVisionZona(2))
  assert.notEqual(colorVisionZona(2), colorVisionZona(3))
  assert.notEqual(colorVisionZona(1), colorVisionZona(12))
  assert.equal(matizVisionZona(0), 0)
})

test('opens create/edit editors in a new protected-route tab', () => {
  assert.equal(urlEditorVision('nuevo'), '/admin/vision/calibracion/editor?mode=create')
  assert.equal(urlEditorVision('editar', 'zone-1'), '/admin/vision/calibracion/editor?mode=edit&zoneId=zone-1')
  const calls: unknown[][] = []
  abrirEditorVision((...args) => calls.push(args), 'editar', 'zone-1')
  assert.deepEqual(calls, [[
    '/admin/vision/calibracion/editor?mode=edit&zoneId=zone-1',
    '_blank',
    'noopener,noreferrer',
  ]])
})

test('prevents duplicate editor tabs with a short, instance-owned lease', () => {
  const records = new Map<string, string>()
  const storage = {
    getItem: (key: string) => records.get(key) ?? null,
    setItem: (key: string, value: string) => { records.set(key, value) },
    removeItem: (key: string) => { records.delete(key) },
  }
  const key = claveReservaEditorVision('zone-1')
  assert.equal(editorVisionYaAbierto(storage, key, 1000), false)
  guardarReservaEditorVision(storage, key, 'editor-one', 1000)
  assert.equal(editorVisionYaAbierto(storage, key, 1001), true)
  liberarReservaEditorVision(storage, key, 'different-editor')
  assert.equal(editorVisionYaAbierto(storage, key, 1002), true)
  liberarReservaEditorVision(storage, key, 'editor-one')
  assert.equal(editorVisionYaAbierto(storage, key, 1003), false)
  guardarReservaEditorVision(storage, key, 'stale-editor', 1000)
  assert.equal(editorVisionYaAbierto(storage, key, 1000 + VIGENCIA_RESERVA_EDITOR_MS), false)
})

test('keeps administration stream-free and protects the fullscreen editor lifecycle', () => {
  const administration = readFileSync(new URL('../app/pages/admin/vision/zonas.vue', import.meta.url), 'utf8')
  const editor = readFileSync(new URL('../app/pages/admin/vision/calibracion/editor.vue', import.meta.url), 'utf8')
  assert.equal(administration.includes('useVisionMjpegStream'), false); assert.equal(administration.includes('/monitor/stream'), false)
  assert.match(administration, /role="alertdialog"/)
  assert.match(administration, /expected_revision/)
  assert.match(administration, /abrirEditorVision/)
  assert.match(editor, /layout: 'vision-editor'/)
  assert.match(editor, /middleware: 'sesion-owner'/)
  assert.match(editor, /AdminVisionAuthorizationGate/)
  assert.equal(editor.includes('monitor/stream?tipo=raw'), true)
  assert.equal(editor.includes('await streamMjpeg.detener()'), true)
  assert.equal(editor.includes('onBeforeUnmount(() =>'), true)
})

test('uses in-app confirmations and notifications in calibration without browser popups', () => {
  const editor = readFileSync(new URL('../app/pages/admin/vision/calibracion/editor.vue', import.meta.url), 'utf8')
  assert.match(editor, /role="alertdialog"/)
  assert.match(editor, /AdminToastNotifications/)
  assert.match(editor, /mostrarToast\(/)
  assert.doesNotMatch(editor, /window\.(confirm|alert)|new Notification\(|Notification\.requestPermission|showNotification/)
})

test('keeps finish and save together and lets save finalize a valid drawing', () => {
  const editor = readFileSync(new URL('../app/pages/admin/vision/calibracion/editor.vue', import.meta.url), 'utf8')
  const administration = readFileSync(new URL('../app/pages/admin/vision/zonas.vue', import.meta.url), 'utf8')
  assert.match(editor, /Terminar área/)
  assert.match(editor, /Guardar cajón/)
  assert.match(editor, /if \(dibujando\.value && !incorporarDibujo\(\)\) return/)
  assert.doesNotMatch(editor, /!poligonosValidos\.value \|\| guardando\.value \|\| dibujando\.value/)
  assert.match(editor, /id="editor-guidance"/)
  assert.match(administration, /Cajones registrados/)
  assert.match(administration, /Cámara solo al editar/)
  assert.match(administration, /Nuevo cajón/)
  assert.doesNotMatch(administration, /revisión \{\{ configuracion\?\.revision/)
})

test('makes existing vertices keyboard-adjustable with accessible names and safe focus return', () => {
  const editor = readFileSync(new URL('../app/pages/admin/vision/calibracion/editor.vue', import.meta.url), 'utf8')
  const administration = readFileSync(new URL('../app/pages/admin/vision/zonas.vue', import.meta.url), 'utf8')
  assert.match(editor, /role="button"[\s\S]*?tabindex="0"[\s\S]*?@keydown="moverVerticeConTeclado/)
  assert.match(editor, /aria-label="'Punto '/)
  assert.match(administration, /@keydown\.tab="mantenerFocoEnDialogo"/)
  assert.match(administration, /focoAnteriorRetiro\?\.isConnected/)
})

test('cross-tab invalidation carries only a configuration-change hint', () => {
  const sync = readFileSync(new URL('../app/utils/vision-config-sync.ts', import.meta.url), 'utf8')
  assert.match(sync, /configuration-changed/)
  assert.equal(sync.includes('postMessage({ type:'), true)
  assert.doesNotMatch(sync, /polygon|cookie|credential|token/i)
  assert.equal(typeof escucharCambioConfiguracionVision, 'function')
  assert.equal(typeof notificarCambioConfiguracionVision, 'function')
})

test('coalesces simultaneous refresh hints into one trailing canonical read', async () => {
  let llamadas = 0
  let liberarPrimera!: () => void
  const primeraLectura = new Promise<void>((resolve) => {
    liberarPrimera = resolve
  })
  const solicitar = crearActualizadorCoalescido(async () => {
    llamadas += 1
    if (llamadas === 1) await primeraLectura
  })

  const primera = solicitar()
  const segunda = solicitar()
  const tercera = solicitar()
  assert.equal(llamadas, 1)

  liberarPrimera()
  await Promise.all([primera, segunda, tercera])
  assert.equal(llamadas, 2)
})

test('never applies a stale configuration revision over the canonical revision', () => {
  assert.equal(puedeAplicarRevisionVision(null, 1), true)
  assert.equal(puedeAplicarRevisionVision(7, 7), true)
  assert.equal(puedeAplicarRevisionVision(8, 9), true)
  assert.equal(puedeAplicarRevisionVision(9, 8), false)
})

test('bounds Vision authorization checks and exposes a retryable error state', () => {
  const authorization = readFileSync(new URL('../app/composables/useVisionAuthorization.ts', import.meta.url), 'utf8')
  const gate = readFileSync(new URL('../app/components/admin/VisionAuthorizationGate.vue', import.meta.url), 'utf8')
  assert.match(authorization, /timeout:\s*10_000/)
  assert.match(authorization, /state:\s*'error'/)
  assert.match(authorization, /codigoHttp\(error\) === 401[\s\S]*?navigateTo\('\/login'/)
  assert.match(gate, /Reintentar verificación/)
  assert.match(gate, /state === 'error'/)
})

test('ignores a configuration hint sent by the same editor instance', () => {
  assert.equal(esCambioConfiguracionRemoto('editor-a', 'editor-a'), false)
  assert.equal(esCambioConfiguracionRemoto('editor-a', 'editor-b'), true)
  assert.equal(esCambioConfiguracionRemoto('editor-a', null), true)
})

test('synchronizes administration when a hidden tab becomes visible without using window focus', () => {
  const administration = readFileSync(new URL('../app/pages/admin/vision/zonas.vue', import.meta.url), 'utf8')
  assert.match(administration, /document\.addEventListener\('visibilitychange',\s*manejadorVisibilidad\)/)
  assert.match(administration, /document\.removeEventListener\('visibilitychange',\s*manejadorVisibilidad\)/)
  assert.match(administration, /if \(document\.visibilityState === 'visible'\) void actualizarDatos\(\)/)
  assert.doesNotMatch(administration, /window\.addEventListener\('focus'/)
})
