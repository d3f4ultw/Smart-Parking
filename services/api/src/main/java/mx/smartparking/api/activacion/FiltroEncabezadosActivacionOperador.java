package mx.smartparking.api.activacion;

import java.io.IOException;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Evita que el navegador guarde las respuestas de invitación y que envíe la dirección de origen al
 * abrirlas.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class FiltroEncabezadosActivacionOperador extends OncePerRequestFilter {

    private static final String RUTA_PUBLICA_ACTIVACION = "/api/v1/operadores/activacion/";
    private static final String RUTA_PUBLICA_RECUPERACION = "/api/v1/operadores/recuperacion/";
    private static final String SUFIJO_REEMISION = "/invitacion/reemitir";
    private static final String SUFIJO_RECUPERACION = "/recuperacion";

    @Override
    protected void doFilterInternal(
            HttpServletRequest solicitud,
            HttpServletResponse respuesta,
            FilterChain cadena) throws ServletException, IOException {
        if (esRutaPrivadaOperador(solicitud)) {
            respuesta.setHeader("Cache-Control", "no-store");
            respuesta.setHeader("Referrer-Policy", "no-referrer");
        }
        cadena.doFilter(solicitud, respuesta);
    }

    private static boolean esRutaPrivadaOperador(HttpServletRequest solicitud) {
        String ruta = solicitud.getRequestURI().substring(solicitud.getContextPath().length());
        return ruta.startsWith(RUTA_PUBLICA_ACTIVACION)
                || ruta.startsWith(RUTA_PUBLICA_RECUPERACION)
                || (ruta.startsWith("/api/v1/operadores/")
                        && (ruta.endsWith(SUFIJO_REEMISION) || ruta.endsWith(SUFIJO_RECUPERACION)));
    }
}
