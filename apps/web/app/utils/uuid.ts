const FORMATO_UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

/** Genera un identificador aleatorio difícil de repetir para reconocer la misma
 * solicitud si vuelve a enviarse; funciona también en páginas sin conexión cifrada (HTTP).
 */
export function generarUuidV4(): string {
  const fuente = globalThis.crypto
  if (!fuente || typeof fuente.getRandomValues !== 'function') {
    throw new Error('Este navegador no permite generar una clave segura para la solicitud.')
  }

  const bytes = fuente.getRandomValues(new Uint8Array(16))
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80

  const hexadecimal = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  const uuid = [
    hexadecimal.slice(0, 8),
    hexadecimal.slice(8, 12),
    hexadecimal.slice(12, 16),
    hexadecimal.slice(16, 20),
    hexadecimal.slice(20),
  ].join('-')
  if (!FORMATO_UUID_V4.test(uuid))
    throw new Error('No se pudo generar una clave válida para la solicitud.')
  return uuid
}
