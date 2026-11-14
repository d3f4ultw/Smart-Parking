package mx.smartparking.api.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.net.URI;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.UUID;
import java.util.List;
import java.util.function.Supplier;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.security.authorization.AuthorityAuthorizationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.web.access.intercept.RequestAuthorizationContext;
import mx.smartparking.api.integracion.ApiCliente;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;

/** Aceptación aislada de login sin dueño y límites JSON por bytes. */
class ValidacionCierreCuentasTest {

    private static final String CSRF = "X-CSRF-TOKEN";
    private static final int LIMITE_BYTES = 1_048_576;

    @Test
    void rolOperadorNoSatisfaceLaAutoridadDeDueno() {
        AuthorityAuthorizationManager<RequestAuthorizationContext> requisitoDueno =
                AuthorityAuthorizationManager.hasRole("DUENO");
        Authentication operador = UsernamePasswordAuthenticationToken.authenticated(
                "operador-sintetico", null, List.of(new SimpleGrantedAuthority("ROLE_OPERADOR")));
        HttpServletRequest solicitud = new MockHttpServletRequest("GET", "/api/v1/panel");
        var decision = requisitoDueno.authorize(
                (Supplier<Authentication>) () -> operador, new RequestAuthorizationContext(solicitud));

        assertFalse(decision.isGranted(), "Un rol OPERADOR no debe satisfacer las rutas hasRole(DUENO).");
    }

    @Test
    void rechazaLoginSinDuenoEnInstalacionVaciaYPendienteYLimitaPorBytes() throws Exception {
        assumeTrue(Boolean.parseBoolean(System.getProperty("smartparking.integration.disposable", "false")),
                "El cierre requiere smartparking.integration.disposable=true.");
        URI base = PropietarioApiAceptacionSupport.baseUrlOptIn();
        ApiCliente anonimo = new ApiCliente(base);
        String token = anonimo.obtenerCsrf(false);

        HttpResponse<String> primerRechazo = login(anonimo, "ausente@example.test", "clave-sintetica", token);
        assertRechazoGenericoSinEstado(primerRechazo);
        afirmarSesionAnonima(anonimo);

        String cuerpoExacto = cuerpoUtf8DeTamano(LIMITE_BYTES);
        HttpResponse<String> enLimite = anonimo.postCuerpoJson("/api/v1/sesion",
                HttpRequest.BodyPublishers.ofString(cuerpoExacto, StandardCharsets.UTF_8), token);
        assertEquals(LIMITE_BYTES, cuerpoExacto.getBytes(StandardCharsets.UTF_8).length);
        assertEquals(401, enLimite.statusCode(), "El cuerpo de exactamente 1 MiB debe llegar al login normal.");
        assertEquals("CREDENCIALES_NO_VALIDAS", PropietarioApiAceptacionSupport.texto(
                PropietarioApiAceptacionSupport.leerJson(enLimite.body()), "codigo"));

        String cuerpoGrande = cuerpoUtf8DeTamano(LIMITE_BYTES + 1);
        HttpRequest.BodyPublisher flujo = HttpRequest.BodyPublishers.ofInputStream(
                () -> new java.io.ByteArrayInputStream(cuerpoGrande.getBytes(StandardCharsets.UTF_8)));
        assertEquals(-1, flujo.contentLength(), "El cuerpo debe enviarse en streaming sin longitud conocida.");
        HttpResponse<String> sobreLimite = anonimo.postCuerpoJson("/api/v1/sesion", flujo, token);
        assertEquals(413, sobreLimite.statusCode(), "El exceso en streaming debe rechazarse por tamaño.");
        assertEquals("CUERPO_DEMASIADO_GRANDE", PropietarioApiAceptacionSupport.texto(
                PropietarioApiAceptacionSupport.leerJson(sobreLimite.body()), "codigo"));

        String correo = "cierre." + UUID.randomUUID().toString().replace("-", "") + "@example.test";
        String acceso = "acceso sintetico validado 2026 A!";
        String administrativa = "administrativa sintetica validada 2026 B!";
        HttpResponse<String> configurada = anonimo.post(
                "/api/v1/configuracion/inicial",
                PropietarioApiAceptacionSupport.configuracion(correo, acceso, administrativa, "Estacionamiento sintético"),
                PropietarioApiAceptacionSupport.clave("cierre-setup"), token);
        assertEquals(201, configurada.statusCode(), "El fixture solo modifica la base descartable.");
        HttpResponse<String> autenticada = login(anonimo, correo, acceso, token);
        assertEquals(200, autenticada.statusCode());
        JsonNode respuestaLogin = PropietarioApiAceptacionSupport.leerJson(autenticada.body());
        assertTrue(respuestaLogin.path("autenticada").asBoolean());
        token = PropietarioApiAceptacionSupport.texto(respuestaLogin, "csrfToken");
        anonimo.csrf(token);
        HttpResponse<String> claveIncorrecta = login(anonimo, correo, "clave incorrecta sintética", token);
        assertRechazoGenericoSinEstado(claveIncorrecta);
        assertEquals(primerRechazo.body(), claveIncorrecta.body(),
                "La ausencia de dueño y la contraseña incorrecta deben ser indistinguibles.");
        String csrfAutenticado = PropietarioApiAceptacionSupport.texto(respuestaLogin, "csrfToken");
        String etag = PropietarioApiAceptacionSupport.etag(anonimo.get("/api/v1/panel"));
        HttpResponse<String> transferencia = anonimo.postConCsrf(
                "/api/v1/transferencia/iniciar",
                Map.of("contrasenaAdministrativa", administrativa),
                Map.of("If-Match", etag,
                        "Idempotency-Key", PropietarioApiAceptacionSupport.clave("cierre-transferencia"),
                        CSRF, csrfAutenticado));
        assertEquals(200, transferencia.statusCode());
        assertEquals("TRANSFERENCIA_PENDIENTE", PropietarioApiAceptacionSupport.texto(
                PropietarioApiAceptacionSupport.leerJson(transferencia.body()), "estado"));

        ApiCliente anonimoPendiente = new ApiCliente(base);
        String csrfPendiente = anonimoPendiente.obtenerCsrf(false);
        HttpResponse<String> rechazoPendiente = login(anonimoPendiente, correo, acceso, csrfPendiente);
        assertRechazoGenericoSinEstado(rechazoPendiente);
        assertEquals(primerRechazo.body(), rechazoPendiente.body(),
                "La transferencia pendiente debe conservar el rechazo genérico sin estado.");
        afirmarSesionAnonima(anonimoPendiente);
    }

    private static HttpResponse<String> login(ApiCliente api, String correo, String contrasena, String csrf)
            throws Exception {
        return api.postJson("/api/v1/sesion", Map.of("correo", correo, "contrasena", contrasena),
                Map.of(CSRF, csrf));
    }

    private static void assertRechazoGenericoSinEstado(HttpResponse<String> respuesta) throws Exception {
        assertEquals(401, respuesta.statusCode());
        JsonNode cuerpo = PropietarioApiAceptacionSupport.leerJson(respuesta.body());
        assertEquals("CREDENCIALES_NO_VALIDAS", PropietarioApiAceptacionSupport.texto(cuerpo, "codigo"));
        assertTrue(respuesta.body().contains("Correo o contraseña no válidos."));
        assertFalse(cuerpo.has("estado"));
        assertFalse(respuesta.body().contains("SIN_CONFIGURAR"));
        assertFalse(respuesta.body().contains("TRANSFERENCIA_PENDIENTE"));
    }

    private static void afirmarSesionAnonima(ApiCliente api) throws Exception {
        HttpResponse<String> sesion = api.get("/api/v1/sesion");
        assertEquals(200, sesion.statusCode());
        JsonNode cuerpo = PropietarioApiAceptacionSupport.leerJson(sesion.body());
        assertFalse(cuerpo.path("autenticada").asBoolean());
        assertFalse(cuerpo.has("estado"));
        assertFalse(cuerpo.has("cuentaId"));
    }

    private static String cuerpoUtf8DeTamano(int bytes) {
        String prefijo = "{\"correo\":\"";
        String sufijo = "\",\"contrasena\":\"x\"}";
        int restante = bytes - prefijo.getBytes(StandardCharsets.UTF_8).length
                - sufijo.getBytes(StandardCharsets.UTF_8).length;
        String relleno = "é".repeat(restante / 2) + (restante % 2 == 0 ? "" : "x");
        String cuerpo = prefijo + relleno + sufijo;
        if (cuerpo.getBytes(StandardCharsets.UTF_8).length != bytes) {
            throw new AssertionError("El cuerpo UTF-8 debe tener el tamaño solicitado.");
        }
        return cuerpo;
    }
}
