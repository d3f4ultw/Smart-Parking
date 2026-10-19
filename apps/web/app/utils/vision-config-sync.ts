const CANAL_CONFIGURACION_VISION = 'smart-parking:vision:configuration'
const MENSAJE_CONFIGURACION_CAMBIADA = 'configuration-changed'

export function notificarCambioConfiguracionVision(origenId: string): void {
  if (typeof BroadcastChannel === 'undefined') return
  const canal = new BroadcastChannel(CANAL_CONFIGURACION_VISION)
  canal.postMessage({ type: MENSAJE_CONFIGURACION_CAMBIADA, originId: origenId })
  globalThis.setTimeout(() => canal.close(), 0)
}

export function escucharCambioConfiguracionVision(
  callback: (origenId: string | null) => void,
): () => void {
  if (typeof BroadcastChannel === 'undefined') return () => undefined
  const canal = new BroadcastChannel(CANAL_CONFIGURACION_VISION)
  const recibir = (evento: MessageEvent<unknown>) => {
    const mensaje = evento.data
    if (
      mensaje !== null
      && typeof mensaje === 'object'
      && 'type' in mensaje
      && mensaje.type === MENSAJE_CONFIGURACION_CAMBIADA
    ) {
      const origenId = 'originId' in mensaje && typeof mensaje.originId === 'string'
        ? mensaje.originId
        : null
      callback(origenId)
    }
  }
  canal.addEventListener('message', recibir)
  return () => {
    canal.removeEventListener('message', recibir)
    canal.close()
  }
}

export function esCambioConfiguracionRemoto(
  origenLocal: string,
  origenMensaje: string | null,
): boolean {
  return origenMensaje !== origenLocal
}
