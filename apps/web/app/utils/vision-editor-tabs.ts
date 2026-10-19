export type ReservaEditorVision = {
  instanceId: string
  updatedAt: number
}

const PREFIJO_RESERVA_EDITOR = 'smart-parking:vision:editor:'
export const VIGENCIA_RESERVA_EDITOR_MS = 15_000

export function claveReservaEditorVision(zoneId?: string): string {
  return `${PREFIJO_RESERVA_EDITOR}${zoneId ?? 'nuevo'}`
}

export function editorVisionYaAbierto(
  storage: Pick<Storage, 'getItem' | 'removeItem'>,
  key: string,
  now = Date.now(),
): boolean {
  const serializado = storage.getItem(key)
  if (serializado === null) return false
  try {
    const reserva = JSON.parse(serializado) as Partial<ReservaEditorVision>
    if (
      typeof reserva.instanceId === 'string'
      && typeof reserva.updatedAt === 'number'
      && now - reserva.updatedAt >= 0
      && now - reserva.updatedAt < VIGENCIA_RESERVA_EDITOR_MS
    ) return true
  } catch {
    // Una reserva malformada no debe impedir que el usuario vuelva a abrir el editor.
  }
  storage.removeItem(key)
  return false
}

export function guardarReservaEditorVision(
  storage: Pick<Storage, 'setItem'>,
  key: string,
  instanceId: string,
  now = Date.now(),
): void {
  storage.setItem(key, JSON.stringify({ instanceId, updatedAt: now } satisfies ReservaEditorVision))
}

export function liberarReservaEditorVision(
  storage: Pick<Storage, 'getItem' | 'removeItem'>,
  key: string,
  instanceId: string,
): void {
  const serializado = storage.getItem(key)
  if (serializado === null) return
  try {
    const reserva = JSON.parse(serializado) as Partial<ReservaEditorVision>
    if (reserva.instanceId === instanceId) storage.removeItem(key)
  } catch {
    storage.removeItem(key)
  }
}
