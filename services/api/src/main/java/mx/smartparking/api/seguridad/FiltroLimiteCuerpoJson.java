package mx.smartparking.api.seguridad;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ReadListener;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletInputStream;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import jakarta.servlet.http.HttpServletResponse;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Limita el tamaño de los datos recibidos, incluso si llegan por partes, para evitar que una
 * solicitud demasiado grande ocupe recursos.
 */
public class FiltroLimiteCuerpoJson extends OncePerRequestFilter {

    public static final int MAXIMO_BYTES = 1_048_576;
    @Override
    protected void doFilterInternal(
            HttpServletRequest solicitud,
            HttpServletResponse respuesta,
            FilterChain cadena) throws ServletException, IOException {
        if (!esJson(solicitud.getContentType())) {
            cadena.doFilter(solicitud, respuesta);
            return;
        }
        byte[] cuerpo = solicitud.getInputStream().readNBytes(MAXIMO_BYTES + 1);
        if (cuerpo.length > MAXIMO_BYTES) {
            escribirError(respuesta);
            return;
        }
        cadena.doFilter(new SolicitudConCuerpo(solicitud, cuerpo), respuesta);
    }

    private static boolean esJson(String contentType) {
        return contentType != null && contentType.toLowerCase(java.util.Locale.ROOT)
                .startsWith("application/json");
    }

    private static void escribirError(HttpServletResponse respuesta) throws IOException {
        respuesta.setStatus(HttpServletResponse.SC_REQUEST_ENTITY_TOO_LARGE);
        respuesta.setContentType("application/json");
        respuesta.setCharacterEncoding(StandardCharsets.UTF_8.name());
        respuesta.setHeader("Cache-Control", "no-store");
        respuesta.getWriter().write(
                "{\"codigo\":\"CUERPO_DEMASIADO_GRANDE\",\"error\":\"La información enviada es demasiado extensa.\"}");
    }

    private static final class SolicitudConCuerpo extends HttpServletRequestWrapper {

        private final byte[] cuerpo;

        private SolicitudConCuerpo(HttpServletRequest solicitud, byte[] cuerpo) {
            super(solicitud);
            this.cuerpo = cuerpo;
        }

        @Override
        public ServletInputStream getInputStream() {
            ByteArrayInputStream entrada = new ByteArrayInputStream(cuerpo);
            return new ServletInputStream() {
                @Override
                public int read() {
                    return entrada.read();
                }

                @Override
                public boolean isFinished() {
                    return entrada.available() == 0;
                }

                @Override
                public boolean isReady() {
                    return true;
                }

                @Override
                public void setReadListener(ReadListener listener) {
                    throw new IllegalStateException("No pudimos completar la acción en este momento.");
                }
            };
        }

        @Override
        public int getContentLength() {
            return cuerpo.length;
        }

        @Override
        public long getContentLengthLong() {
            return cuerpo.length;
        }
    }
}
