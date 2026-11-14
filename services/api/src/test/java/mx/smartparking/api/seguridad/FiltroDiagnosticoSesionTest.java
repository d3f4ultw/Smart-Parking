package mx.smartparking.api.seguridad;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import jakarta.servlet.http.HttpServletResponse;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

class FiltroDiagnosticoSesionTest {

    private static final String ENCABEZADO_CORRELACION = "X-Request-ID";
    private static final String CORRELACION = "d01f7f89-bd82-4a90-b332-342f3667de10";

    private final FiltroDiagnosticoSesion filtro = new FiltroDiagnosticoSesion();

    @AfterEach
    void limpiarContexto() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void conservaCorrelacionUuidYRegistraSoloGetSesion() throws Exception {
        MockHttpServletRequest solicitud = solicitud("GET", "/api/v1/sesion");
        solicitud.addHeader(ENCABEZADO_CORRELACION, CORRELACION);
        MockHttpServletResponse respuesta = new MockHttpServletResponse();
        AtomicBoolean cadenaEjecutada = new AtomicBoolean();

        filtro.doFilter(solicitud, respuesta, (peticion, salida) -> {
            cadenaEjecutada.set(true);
            ((HttpServletResponse) salida).setStatus(200);
        });

        assertTrue(cadenaEjecutada.get());
        assertEquals(200, respuesta.getStatus());
        assertEquals(CORRELACION, respuesta.getHeader(ENCABEZADO_CORRELACION));
    }

    @Test
    void soloMarcaVerificacionExitosaCuandoLaSesionTieneIdentidadPropietario() throws Exception {
        MockHttpServletRequest solicitud = solicitud("GET", "/api/v1/sesion");
        solicitud.addHeader(ENCABEZADO_CORRELACION, CORRELACION);
        MockHttpServletResponse respuesta = new MockHttpServletResponse();
        Logger logger = (Logger) LoggerFactory.getLogger(FiltroDiagnosticoSesion.class);
        ListAppender<ILoggingEvent> appender = new ListAppender<>();
        appender.start();
        logger.addAppender(appender);
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        new PrincipalPropietario(14L, "correo-secreto@example.test"), null, List.of()));

        try {
            filtro.doFilter(solicitud, respuesta,
                    (peticion, salida) -> ((HttpServletResponse) salida).setStatus(200));
        } finally {
            logger.detachAppender(appender);
            appender.stop();
        }

        assertEquals(200, respuesta.getStatus());
        assertEquals(CORRELACION, respuesta.getHeader(ENCABEZADO_CORRELACION));
        String registro = appender.list.get(0).getFormattedMessage();
        assertTrue(registro.contains("layer=java_api"));
        assertTrue(registro.contains("method=GET"));
        assertTrue(registro.contains("path=/api/v1/sesion"));
        assertTrue(registro.contains("requestId=" + CORRELACION));
        assertTrue(registro.contains("status=200"));
        assertTrue(registro.contains("verificationSucceeded=true"));
        assertFalse(registro.contains("correo-secreto@example.test"));
    }

    @Test
    void reemplazaCorrelacionConFormatoInvalidoSinDevolverSuValor() throws Exception {
        MockHttpServletRequest solicitud = solicitud("GET", "/api/v1/sesion");
        solicitud.addHeader(ENCABEZADO_CORRELACION, "valor-invalido");
        MockHttpServletResponse respuesta = new MockHttpServletResponse();

        filtro.doFilter(solicitud, respuesta,
                (peticion, salida) -> ((HttpServletResponse) salida).setStatus(200));

        String correlacion = respuesta.getHeader(ENCABEZADO_CORRELACION);
        assertNotEquals("valor-invalido", correlacion);
        assertEquals(UUID.fromString(correlacion).toString(), correlacion);
    }

    @Test
    void noModificaOtrasRutasNiMetodos() throws Exception {
        MockHttpServletRequest solicitud = solicitud("GET", "/api/v1/clientes/sesion");
        MockHttpServletResponse respuesta = new MockHttpServletResponse();
        AtomicBoolean cadenaEjecutada = new AtomicBoolean();

        filtro.doFilter(solicitud, respuesta, (peticion, salida) -> cadenaEjecutada.set(true));

        assertTrue(cadenaEjecutada.get());
        assertNull(respuesta.getHeader(ENCABEZADO_CORRELACION));
    }

    private static MockHttpServletRequest solicitud(String metodo, String ruta) {
        MockHttpServletRequest solicitud = new MockHttpServletRequest();
        solicitud.setMethod(metodo);
        solicitud.setRequestURI(ruta);
        solicitud.setServletPath(ruta);
        return solicitud;
    }
}
