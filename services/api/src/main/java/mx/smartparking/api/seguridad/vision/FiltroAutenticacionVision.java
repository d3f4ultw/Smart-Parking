package mx.smartparking.api.seguridad.vision;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Enumeration;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpHeaders;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

/** Comprueba el código de acceso de la cámara sin abrir ni consultar sesiones de usuarios. */
public final class FiltroAutenticacionVision extends OncePerRequestFilter {
    private final byte[] hashToken;
    private final UUID fuenteId;

    public FiltroAutenticacionVision(String hashConfigurado, String fuenteConfigurada, String hashRfid) {
        this.hashToken = hashConfigurado != null && hashConfigurado.matches("[0-9a-fA-F]{64}")
                && !hashConfigurado.equalsIgnoreCase(hashRfid)
                ? HexFormat.of().parseHex(hashConfigurado) : null;
        this.fuenteId = leerFuente(fuenteConfigurada);
    }

    @Override
    protected void doFilterInternal(HttpServletRequest solicitud, HttpServletResponse respuesta, FilterChain cadena)
            throws ServletException, IOException {
        if (hashToken == null || fuenteId == null) {
            rechazar(respuesta, HttpServletResponse.SC_SERVICE_UNAVAILABLE);
            return;
        }
        String token = obtenerToken(solicitud);
        if (token == null || !MessageDigest.isEqual(hashToken, sha256(token))) {
            rechazar(respuesta, HttpServletResponse.SC_UNAUTHORIZED);
            return;
        }
        SecurityContext contexto = SecurityContextHolder.createEmptyContext();
        contexto.setAuthentication(UsernamePasswordAuthenticationToken.authenticated(
                fuenteId, null, List.of(new SimpleGrantedAuthority("DISPOSITIVO_VISION"))));
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

    private static byte[] sha256(String token) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(token.getBytes(StandardCharsets.UTF_8));
        } catch (NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException("SHA-256 no está disponible.", excepcion);
        }
    }

    private static UUID leerFuente(String fuenteConfigurada) {
        try {
            return fuenteConfigurada == null ? null : UUID.fromString(fuenteConfigurada);
        } catch (IllegalArgumentException excepcion) {
            return null;
        }
    }

    private static void rechazar(HttpServletResponse respuesta, int estado) throws IOException {
        respuesta.setStatus(estado);
        respuesta.setContentType("application/json");
        respuesta.setCharacterEncoding("UTF-8");
        respuesta.setHeader(HttpHeaders.CACHE_CONTROL, "no-store");
        respuesta.setHeader(HttpHeaders.VARY, HttpHeaders.AUTHORIZATION);
        if (estado == HttpServletResponse.SC_UNAUTHORIZED) {
            respuesta.setHeader(HttpHeaders.WWW_AUTHENTICATE, "Bearer");
        }
        respuesta.getWriter().write("{\"codigo\":\"VISION_NO_DISPONIBLE\",\"mensaje\":\"Acceso no disponible.\"}");
    }
}
