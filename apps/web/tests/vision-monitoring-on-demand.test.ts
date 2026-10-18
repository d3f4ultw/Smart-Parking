import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const monitoringPage = readFileSync(
  new URL('../app/pages/admin/vision/monitoreo.vue', import.meta.url),
  'utf8',
)
const adminLayout = readFileSync(
  new URL('../app/layouts/admin.vue', import.meta.url),
  'utf8',
)
const cameraPage = readFileSync(
  new URL('../app/pages/admin/vision/monitoreo/camara.vue', import.meta.url),
  'utf8',
)
const streamComposable = readFileSync(
  new URL('../app/composables/useVisionMjpegStream.ts', import.meta.url),
  'utf8',
)

test('keeps the Monitoring overview and opens the camera from its action in a new tab', () => {
  assert.match(monitoringPage, /layout:\s*'admin'/)
  assert.match(monitoringPage, /middleware:\s*'sesion-owner'/)
  assert.doesNotMatch(monitoringPage, /redirect:/)
  assert.match(
    monitoringPage,
    /<NuxtPage v-if="route\.path === '\/admin\/vision\/monitoreo\/camara'" \/>/,
  )
  assert.match(monitoringPage, /Monitoreo Vision/)
  assert.match(
    monitoringPage,
    /Visualiza las detecciones de vehículos y los cajones desde la cámara\./,
  )
  assert.match(
    monitoringPage,
    /href="\/admin\/vision\/monitoreo\/camara"\s+target="_blank"\s+rel="noopener"/,
  )
  assert.match(monitoringPage, /Abrir cámara en vivo/)
  assert.doesNotMatch(monitoringPage, /useVisionMjpegStream|\/monitor\/stream/)
  assert.doesNotMatch(
    monitoringPage,
    /vision-status-grid|vision-zone-list|LIBRE|OCUPADO|active_viewers/,
  )
  assert.match(
    adminLayout,
    /<NuxtLink[\s\S]*?to="\/admin\/vision\/monitoreo"[\s\S]*?<span>Monitoreo<\/span>[\s\S]*?<\/NuxtLink>/,
  )
  assert.doesNotMatch(
    adminLayout.match(/<NuxtLink[\s\S]*?to="\/admin\/vision\/monitoreo"[\s\S]*?<\/NuxtLink>/)?.[0] ?? '',
    /target="_blank"/,
  )
})

test('protects one read-only annotated camera stream in the existing fullscreen layout', () => {
  assert.match(cameraPage, /layout:\s*'vision-editor'/)
  assert.match(cameraPage, /middleware:\s*'sesion-owner'/)
  assert.match(cameraPage, /<AdminVisionAuthorizationGate/)
  assert.equal((cameraPage.match(/useVisionMjpegStream\(/g) ?? []).length, 1)
  assert.match(cameraPage, /\/api\/admin\/vision\/monitor\/stream\?tipo=annotated/)
  assert.match(cameraPage, /\/api\/admin\/vision\/monitor\/status/)
  assert.match(cameraPage, /object-fit:\s*contain/)
  assert.match(cameraPage, /naturalWidth/)
  assert.match(cameraPage, /naturalHeight/)
  assert.match(cameraPage, /Cerrar vista/)
  assert.match(cameraPage, /navigateTo\('\/admin\/vision\/zonas'\)/)
  assert.doesNotMatch(cameraPage, /camera-waiting/)
  assert.match(
    cameraPage,
    /<section\s+class="camera-stage"[\s\S]*?<img[\s\S]*?v-if="vision\.autorizado\.value && camaraDisponible && streamMjpeg\.frameUrl\.value"/,
  )
  assert.match(cameraPage, /v-if="!streamEnVivo \|\| anchoFrame === 0"/)
  assert.match(cameraPage, /watch\(\[\(\) => vision\.autorizado\.value, puedeMantenerStream\]/)
  assert.match(cameraPage, /puedeMostrarFrameAnotadoVision\(estadoFuente\.value\)/)
  assert.doesNotMatch(
    cameraPage,
    /calibracion|\/configuration|method:\s*'(?:POST|PUT|DELETE)'|guardar|eliminar zona/i,
  )
})

test('keeps the stream lifecycle independent from annotated revision readiness', () => {
  const condicionStream = cameraPage.match(
    /const puedeMantenerStream = computed\(\(\) =>([\s\S]*?)\n\)/,
  )?.[1] ?? ''

  assert.match(cameraPage, /const puedeMantenerStream = computed\(/)
  assert.doesNotMatch(condicionStream, /annotated_frame_fresh|applied_revision/)
})

test('cleans the viewer on navigation and tab exit using the shared stream lifecycle', () => {
  assert.match(cameraPage, /onBeforeRouteLeave/)
  assert.match(cameraPage, /onBeforeUnmount/)
  assert.match(cameraPage, /addEventListener\('pagehide'/)
  assert.match(cameraPage, /removeEventListener\('pagehide'/)
  assert.match(cameraPage, /detenerActualizaciones/)
  assert.match(cameraPage, /streamMjpeg\.detener\(\)/)
  assert.match(streamComposable, /controladorCiclo\?\.abort\(\)/)
  assert.match(streamComposable, /controladorPeticion\?\.abort\(\)/)
  assert.match(streamComposable, /await lector\.cancel\(\)/)
  assert.match(streamComposable, /URL\.revokeObjectURL/)
})
