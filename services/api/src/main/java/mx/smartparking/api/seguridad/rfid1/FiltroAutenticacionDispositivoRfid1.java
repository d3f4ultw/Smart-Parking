package mx.smartparking.api.seguridad.rfid1;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.Enumeration;
import java.util.List;
import mx.smartparking.api.seguridad.FiltroLimiteCuerpoJson;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

/** Comprueba el acceso del lector sin abrir ni utilizar sesiones de usuarios. */
public final class FiltroAutenticacionDispositivoRfid1 extends OncePerRequestFilter {

    private static final String AUTORIDAD_RFID1 = "DISPOSITIVO_RFID1";
    private static final String ERROR_CREDENCIAL =
            "{\"codigo\":\"DISPOSITIVO_NO_AUTORIZADO\",\"mensaje\":\"Credencial no válida.\"}";
    private static final String ERROR_DESHABILITADO =
            "{\"codigo\":\"DISPOSITIVO_NO_DISPONIBLE\",\"mensaje\":\"El lector RFID 1 no está disponible.\"}";

    private final AutenticadorDispositivoRfid1 autenticador;

    public FiltroAutenticacionDispositivoRfid1(AutenticadorDispositivoRfid1 autenticador) {
        this.autenticador = autenticador;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest solicitud,
            HttpServletResponse respuesta,
            FilterChain cadena) throws ServletException, IOException {
        if (!autenticador.estaHabilitado()) {
            escribirError(respuesta, HttpStatus.SERVICE_UNAVAILABLE, ERROR_DESHABILITADO);
            return;
        }

        String token = obtenerToken(solicitud);
        if (!autenticador.autenticar(token)) {
            escribirError(respuesta, HttpStatus.UNAUTHORIZED, ERROR_CREDENCIAL);
            return;
        }

        SecurityContext contexto = SecurityContextHolder.createEmptyContext();
        contexto.setAuthentication(UsernamePasswordAuthenticationToken.authenticated(
                "rfid1", null, List.of(new SimpleGrantedAuthority(AUTORIDAD_RFID1))));
        SecurityContextHolder.setContext(contexto);
        cadena.doFilter(solicitud, respuesta);
    }

    private static String obtenerToken(HttpServletRequest solicitud) {
        Enumeration<String> encabezados = solicitud.getHeaders(HttpHeaders.AUTHORIZATION);
        if (encabezados == null || !encabezados.hasMoreElements()) {
            return null;
        }
        String encabezado = encabezados.nextElement();
        if (encabezados.hasMoreElements() || encabezado.length() <= 7
                || !encabezado.regionMatches(true, 0, "Bearer ", 0, 7)) {
            return null;
        }
        String token = encabezado.substring(7);
        return token.isBlank() || token.indexOf(' ') >= 0 || token.indexOf('\t') >= 0 ? null : token;
    }

    private static void escribirError(
            HttpServletResponse respuesta, HttpStatus estado, String cuerpo) throws IOException {
        respuesta.setStatus(estado.value());
        respuesta.setContentType("application/json");
        respuesta.setCharacterEncoding("UTF-8");
        respuesta.setHeader(HttpHeaders.CACHE_CONTROL, "no-store");
        respuesta.setHeader(HttpHeaders.VARY, HttpHeaders.AUTHORIZATION);
        if (estado == HttpStatus.UNAUTHORIZED) {
            respuesta.setHeader(HttpHeaders.WWW_AUTHENTICATE, "Bearer");
        }
        respuesta.getWriter().write(cuerpo);
    }
}
