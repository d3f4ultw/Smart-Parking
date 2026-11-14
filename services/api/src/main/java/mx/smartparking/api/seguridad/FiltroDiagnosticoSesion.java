package mx.smartparking.api.seguridad;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Anota si las solicitudes de sesión se completaron sin registrar nombres, contraseñas ni otros datos
 * de acceso.
 */
final class FiltroDiagnosticoSesion extends OncePerRequestFilter {

    private static final Logger LOG = LoggerFactory.getLogger(FiltroDiagnosticoSesion.class);
    private static final String RUTA_SESION = "/api/v1/sesion";
    private static final String ENCABEZADO_CORRELACION = "X-Request-ID";
    private static final Pattern FORMATO_CORRELACION = Pattern.compile(
            "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}");

    @Override
    protected boolean shouldNotFilter(HttpServletRequest solicitud) {
        String metodo = solicitud.getMethod();
        return !RUTA_SESION.equals(solicitud.getServletPath())
                || !("GET".equals(metodo) || "POST".equals(metodo));
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest solicitud,
            HttpServletResponse respuesta,
            FilterChain cadena) throws ServletException, IOException {
        String metodo = solicitud.getMethod();
        String correlacion = obtenerCorrelacion(solicitud.getHeader(ENCABEZADO_CORRELACION));
        long inicioNanos = System.nanoTime();
        String categoria = "error_procesamiento";
        boolean verificacionExitosa = false;
        int estadoObservado = 0;
        respuesta.setHeader(ENCABEZADO_CORRELACION, correlacion);

        try {
            cadena.doFilter(solicitud, respuesta);
            estadoObservado = respuesta.getStatus();
            if ("GET".equals(metodo)) {
                verificacionExitosa = estadoObservado == HttpServletResponse.SC_OK && hayIdentidadPropietario();
            }
            categoria = clasificar(metodo, estadoObservado, verificacionExitosa);
        } catch (IOException | ServletException | RuntimeException excepcion) {
            categoria = "error_procesamiento";
            throw excepcion;
        } finally {
            long duracionMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - inicioNanos);
            if ("GET".equals(metodo)) {
                LOG.info("session_diagnostic layer=java_api method={} path={} requestId={} status={} "
                                + "durationMs={} category={} verificationSucceeded={}",
                        metodo, RUTA_SESION, correlacion, estadoObservado, duracionMs, categoria, verificacionExitosa);
            } else {
                LOG.info("session_diagnostic layer=java_api method={} path={} requestId={} status={} "
                                + "durationMs={} category={}",
                        metodo, RUTA_SESION, correlacion, estadoObservado, duracionMs, categoria);
            }
        }
    }

    private static String obtenerCorrelacion(String valor) {
        return valor != null && FORMATO_CORRELACION.matcher(valor).matches()
                ? valor.toLowerCase(java.util.Locale.ROOT)
                : UUID.randomUUID().toString();
    }

    private static boolean hayIdentidadPropietario() {
        Authentication autenticacion = SecurityContextHolder.getContext().getAuthentication();
        return autenticacion != null && autenticacion.isAuthenticated()
                && autenticacion.getPrincipal() instanceof PrincipalPropietario;
    }

    private static String clasificar(String metodo, int estado, boolean verificacionExitosa) {
        if ("GET".equals(metodo)) {
            if (estado == HttpServletResponse.SC_SERVICE_UNAVAILABLE) return "verificacion_no_disponible";
            if (estado == HttpServletResponse.SC_UNAUTHORIZED) return "sesion_no_vigente";
            if (estado == HttpServletResponse.SC_OK) return verificacionExitosa ? "sesion_autenticada" : "sesion_anonima";
            return "respuesta_http";
        }
        if (estado == HttpServletResponse.SC_OK) return "autenticacion_aceptada";
        if (estado == HttpServletResponse.SC_UNAUTHORIZED) return "credenciales_rechazadas";
        if (estado == HttpServletResponse.SC_FORBIDDEN) return "csrf_rechazado";
        if (estado == HttpServletResponse.SC_SERVICE_UNAVAILABLE) return "api_no_disponible";
        return "respuesta_http";
    }
}
