import { appendResponseHeader, type H3Event } from 'h3'

type TipoSesionBff = 'cliente' | 'administrativa'

/** Toma del navegador el dato que mantiene abierta la sesión y lo prepara con el nombre
 * que espera el servidor. Distingue el acceso del cliente del administrativo; quien llama
 * agrega el dato a la solicitud, porque esta función no lo envía por sí sola.
 */
export function cookieSesionParaUpstream(
  encabezadoCookie: string | undefined,
  tipoSesion: TipoSesionBff,
): string | undefined {
  const nombre = tipoSesion === 'cliente' ? 'CLIENTSESSIONID' : 'JSESSIONID'
  const par = encabezadoCookie
    ?.split(';')
    .map((parte) => parte.trim())
    .find((parte) => parte.slice(0, parte.indexOf('=')) === nombre)
  if (!par) return undefined

  return `JSESSIONID=${par.slice(par.indexOf('=') + 1).trim()}`
}

/** Devuelve al navegador los datos válidos que envía el servidor, incluido el dato
 * que mantiene abierta la sesión. Para el cliente cambia su nombre y lo mantiene
 * separado del acceso administrativo.
 */
export function reenviarCookiesSesion(
  evento: H3Event,
  cookies: string[],
  tipoSesion: TipoSesionBff,
) {
  for (const cookie of cookies) {
    const separador = cookie.indexOf('=')
    if (separador < 1) continue

    const nombre = cookie.slice(0, separador).trim()
    if (nombre === 'CLIENTSESSIONID') continue

    const traducida =
      tipoSesion === 'cliente' && nombre === 'JSESSIONID'
        ? `CLIENTSESSIONID${cookie.slice(separador)}`
        : cookie
    const global = /;\s*path=/i.test(traducida)
      ? traducida.replace(/;\s*path=[^;]*/i, '; Path=/')
      : `${traducida}; Path=/`
    appendResponseHeader(evento, 'set-cookie', global)
  }
}
