import { createError } from 'h3'

const RUTA_CAPTURAS = '/api/v1/rfid-1/capturas'
const RUTA_TARJETAS = '/api/v1/tarjetas-rfid'
const RUTA_ESTADO_CONEXION = '/api/v1/rfid-1/estado-conexion'
const FORMATO_CAPTURA = /^[0-9a-f]{32}$/
const FORMATO_ASOCIACION = /^[1-9]\d*$/
const TIPOS_ENTIDAD = new Set(['CLIENTE', 'EMPLEADO'])
const FILTROS_TIPO_ENTIDAD = new Set(['CLIENTE', 'EMPLEADO', 'MIXTO'])
const ESTADOS_TARJETA = new Set(['TODAS', 'ACTIVA', 'CANCELADA'])

const RUTAS_EXACTAS = new Map([
  [`POST ${RUTA_CAPTURAS}`, 'rfid1-crear'],
  [`GET ${RUTA_CAPTURAS}/activa`, 'rfid1-activa'],
  [`GET ${RUTA_ESTADO_CONEXION}`, 'rfid1-estado-conexion'],
  [`GET ${RUTA_TARJETAS}/personas`, 'rfid1-personas'],
  [`GET ${RUTA_TARJETAS}/modalidad`, 'rfid1-modalidad'],
  [`GET ${RUTA_TARJETAS}`, 'rfid1-listar'],
])

function asociacionValida(valor: string) {
  return FORMATO_ASOCIACION.test(valor) && Number.isSafeInteger(Number(valor))
}

/** Acepta solo las rutas RFID1 previstas, con el método correcto y números
 * de asociación dentro del rango admitido.
 */
export function operacionRfid1Permitida(metodo: string, ruta: string): string | undefined {
  const exacta = RUTAS_EXACTAS.get(`${metodo} ${ruta}`)
  if (exacta) return exacta

  const asociacionDetalle = ruta.match(/^\/api\/v1\/tarjetas-rfid\/([1-9]\d*)$/)?.[1]
  if (asociacionDetalle && asociacionValida(asociacionDetalle) && metodo === 'GET') {
    return 'rfid1-detalle'
  }

  const asociacionCancelada = ruta.match(/^\/api\/v1\/tarjetas-rfid\/([1-9]\d*)\/cancelacion$/)?.[1]
  if (asociacionCancelada && asociacionValida(asociacionCancelada) && metodo === 'POST') {
    return 'rfid1-cancelar-tarjeta'
  }

  const subrutaCaptura = ruta.match(
    /^\/api\/v1\/rfid-1\/capturas\/([0-9a-f]{32})\/(vista-previa|confirmacion)$/,
  )
  const capturaDeSubruta = subrutaCaptura?.[1]
  const nombreSubruta = subrutaCaptura?.[2]
  if (capturaDeSubruta && nombreSubruta && FORMATO_CAPTURA.test(capturaDeSubruta)) {
    if (nombreSubruta === 'vista-previa' && metodo === 'GET') return 'rfid1-vista-previa'
    if (nombreSubruta === 'confirmacion' && metodo === 'POST') return 'rfid1-confirmar'
    return undefined
  }

  const capturaId = ruta.match(/^\/api\/v1\/rfid-1\/capturas\/([0-9a-f]{32})$/)?.[1]
  if (!capturaId || !FORMATO_CAPTURA.test(capturaId)) return undefined
  if (metodo === 'GET') return 'rfid1-consultar'
  if (metodo === 'DELETE') return 'rfid1-cancelar'
  return undefined
}

function parametrosExactos(url: URL, obligatorios: string[], opcionales: string[]) {
  const permitidos = new Set([...obligatorios, ...opcionales])
  for (const nombre of new Set(url.searchParams.keys())) {
    if (!permitidos.has(nombre) || url.searchParams.getAll(nombre).length !== 1) return false
  }
  return obligatorios.every((nombre) => url.searchParams.getAll(nombre).length === 1)
}

function paginaValida(valor: string | null) {
  if (valor === null) return true
  if (!/^[1-9]\d*$/.test(valor)) return false
  const pagina = Number(valor)
  return Number.isSafeInteger(pagina) && pagina <= 2_147_483_647
}

function contieneControl(valor: string, incluirControlesExtendidos = false) {
  return [...valor].some((caracter) => {
    const codigo = caracter.codePointAt(0) ?? 0
    return (
      codigo <= 0x1f ||
      codigo === 0x7f ||
      (incluirControlesExtendidos && codigo >= 0x80 && codigo <= 0x9f)
    )
  })
}

/** Comprueba que cada consulta RFID1 use solo los filtros esperados,
 * con un valor válido para cada uno y sin nombres repetidos.
 */
export function consultaRfid1Permitida(url: URL, operacion: string): boolean {
  if (operacion === 'rfid1-personas') {
    if (!parametrosExactos(url, ['tipoEntidad', 'busqueda'], [])) return false
    const tipo = url.searchParams.get('tipoEntidad')
    const busqueda = url.searchParams.get('busqueda')?.trim() ?? ''
    return Boolean(
      tipo &&
      FILTROS_TIPO_ENTIDAD.has(tipo) &&
      [...busqueda].length >= 2 &&
      busqueda.length <= 100 &&
      !contieneControl(busqueda),
    )
  }

  if (operacion === 'rfid1-listar') {
    if (!parametrosExactos(url, ['tipoEntidad'], ['estado', 'pagina', 'busqueda'])) return false
    const tipo = url.searchParams.get('tipoEntidad')
    const estado = url.searchParams.get('estado')
    const busqueda = url.searchParams.get('busqueda')
    return Boolean(
      tipo &&
      FILTROS_TIPO_ENTIDAD.has(tipo) &&
      (estado === null || ESTADOS_TARJETA.has(estado)) &&
      (busqueda === null || (busqueda.length <= 100 && !contieneControl(busqueda, true))) &&
      paginaValida(url.searchParams.get('pagina')),
    )
  }

  return url.searchParams.size === 0
}

function solicitudNoValida(): never {
  throw createError({
    statusCode: 400,
    statusMessage: 'La solicitud RFID no es válida.',
    data: { codigo: 'SOLICITUD_NO_VALIDA' },
  })
}

function codigoPersonaValido(tipoEntidad: string, codigo: string) {
  const formato = tipoEntidad === 'CLIENTE' ? /^CLI-\d{4,}$/ : /^E-\d{4,}$/
  return codigo.length <= 32 && formato.test(codigo)
}

/** Al iniciar una lectura, acepta solo el tipo y el código de la persona;
 * rechaza otros datos, incluido el identificador de tarjeta que aporta el lector.
 */
export function validarCuerpoRfid1(
  operacion: string,
  cuerpo: ArrayBuffer | undefined,
  tipoContenido: string | undefined,
) {
  if (operacion !== 'rfid1-crear') {
    if ((cuerpo?.byteLength ?? 0) !== 0) solicitudNoValida()
    return
  }
  const tipoBase = tipoContenido?.split(';', 1)[0]
  if (
    !cuerpo ||
    cuerpo.byteLength === 0 ||
    !tipoBase ||
    tipoBase.trim().toLowerCase() !== 'application/json'
  ) {
    solicitudNoValida()
  }

  let valor: unknown
  try {
    valor = JSON.parse(new TextDecoder().decode(cuerpo))
  } catch {
    return solicitudNoValida()
  }
  if (typeof valor !== 'object' || valor === null || Array.isArray(valor)) solicitudNoValida()

  const datos = valor as Record<string, unknown>
  const campos = Object.keys(datos).sort()
  if (
    campos.length !== 2 ||
    campos[0] !== 'codigoPersona' ||
    campos[1] !== 'tipoEntidad' ||
    typeof datos.tipoEntidad !== 'string' ||
    !TIPOS_ENTIDAD.has(datos.tipoEntidad) ||
    typeof datos.codigoPersona !== 'string' ||
    !codigoPersonaValido(datos.tipoEntidad, datos.codigoPersona)
  ) {
    solicitudNoValida()
  }
}
