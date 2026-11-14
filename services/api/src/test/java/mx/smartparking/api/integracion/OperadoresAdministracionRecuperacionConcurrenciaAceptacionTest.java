package mx.smartparking.api.integracion;

import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.clave;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.etag;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.leerJson;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.texto;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.net.URI;
import java.net.http.HttpResponse;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import mx.smartparking.api.integracion.ApiCliente;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** Acepta las guardas del endpoint y una única finalización ante dos solicitudes simultáneas. */
final class OperadoresAdministracionRecuperacionConcurrenciaAceptacionTest {

    private static final String RUTA = "/api/v1/operadores";
    private static final String CSRF = "X-CSRF-TOKEN";
    private static final String ASUNTO_ACTIVACION = "Activa tu cuenta de Smart Parking";
    private static final String ASUNTO_RECUPERACION = "Establece una nueva contraseña de Smart Parking";
    private static final Pattern TOKEN_ACTIVACION =
            Pattern.compile("https?://[^\\s#]+/activar-operador#([A-Za-z0-9_-]{43})");
    private static final Pattern TOKEN_RECUPERACION =
            Pattern.compile("https?://[^\\s#]+/restablecer-contrasena#([A-Za-z0-9_-]{43})");

    private URI apiUrl;
    private URI mailpitUrl;
    private ApiCliente dueno;
    private String csrf;

    @BeforeEach
    void iniciarSesionSintetica() throws Exception {
        apiUrl = OperadoresAdministracionEntornoAceptacion.apiUrl();
        mailpitUrl = OperadoresAdministracionEntornoAceptacion.mailpitUrl();
        String correo = System.getenv("TEST_OWNER_EMAIL");
        String contrasena = System.getenv("TEST_OWNER_PASSWORD");
        assumeTrue(correo != null && correo.endsWith("@example.test")
                        && contrasena != null && !contrasena.isBlank(),
                "La aceptación requiere credenciales sintéticas del propietario.");
        OperadoresAdministracionEntornoAceptacion.prepararCredencialDueno(correo, contrasena);
        dueno = new ApiCliente(apiUrl);
        String csrfInicial = dueno.obtenerCsrf(true);
        HttpResponse<String> login = dueno.postJson("/api/v1/sesion",
                Map.of("correo", correo, "contrasena", contrasena), Map.of(CSRF, csrfInicial));
        assertEquals(200, login.statusCode());
        csrf = texto(leerJson(login.body()), "csrfToken");
        dueno.csrf(csrf);
    }

    @Test
    void dosFinalizacionesConsumenUnaVezYLasGuardasProtegenLaSolicitud() throws Exception {
        String sufijo = UUID.randomUUID().toString();
        String correo = "recuperacion.concurrente." + sufijo + "@example.test";
        UUID operadorId = registrar(correo);
        String tokenActivacion = extraerToken(
                MailpitApiCliente.textoUnico(mailpitUrl, ASUNTO_ACTIVACION, correo), TOKEN_ACTIVACION);
        assertEquals(200, dueno.postJson("/api/v1/operadores/activacion/validar",
                Map.of("token", tokenActivacion), Map.of(CSRF, csrf)).statusCode());
        assertEquals(204, dueno.postJson("/api/v1/operadores/activacion/completar",
                Map.of("token", tokenActivacion, "contrasena", "Inicial-" + sufijo + "-2026!",
                        "confirmarContrasena", "Inicial-" + sufijo + "-2026!"),
                Map.of(CSRF, csrf)).statusCode());

        String etagAntes = etag(detalle(operadorId));
        String hashAntes = hashContrasena(operadorId);
        ApiCliente anonimo = new ApiCliente(apiUrl);
        String csrfAnonimo = anonimo.obtenerCsrf(false);
        HttpResponse<String> sinDueno = anonimo.postJson(RUTA + "/" + operadorId + "/recuperacion", null,
                Map.of(CSRF, csrfAnonimo, "If-Match", etagAntes, "Idempotency-Key", clave("anonimo-" + sufijo)));
        assertEquals(401, sinDueno.statusCode(), "La solicitud debe exigir sesión DUENO.");

        HttpResponse<String> solicitud = dueno.postJson(RUTA + "/" + operadorId + "/recuperacion", null,
                Map.of(CSRF, csrf, "If-Match", etagAntes, "Idempotency-Key", clave("recuperar-" + sufijo)));
        assertEquals(200, solicitud.statusCode());
        assertEquals("ENVIADO", texto(leerJson(solicitud.body()), "estadoEnvio"));
        long minutosRestantes = Duration.between(Instant.now(),
                Instant.parse(texto(leerJson(solicitud.body()), "venceEn"))).toMinutes();
        assertTrue(minutosRestantes >= 29 && minutosRestantes <= 30);
        assertFalse(solicitud.body().contains("token"));
        String tokenRecuperacion = extraerToken(
                MailpitApiCliente.textoUnico(mailpitUrl, ASUNTO_RECUPERACION, correo), TOKEN_RECUPERACION);

        ApiCliente sinCsrf = new ApiCliente(apiUrl);
        String csrfSinCsrf = sinCsrf.obtenerCsrf(false);
        Map<String, String> completar = Map.of(
                "token", tokenRecuperacion,
                "contrasena", "Recuperada-" + sufijo + "-2026!",
                "confirmarContrasena", "Recuperada-" + sufijo + "-2026!");
        assertEquals(403, sinCsrf.postJson("/api/v1/operadores/recuperacion/completar",
                completar, Map.of()).statusCode(), "La recuperación pública también exige CSRF.");
        assertEquals(200, sinCsrf.postJson("/api/v1/operadores/recuperacion/validar",
                Map.of("token", tokenRecuperacion), Map.of(CSRF, csrfSinCsrf)).statusCode(),
                "La solicitud rechazada por CSRF no debe consumir el enlace.");

        ApiCliente primerCliente = new ApiCliente(apiUrl);
        ApiCliente segundoCliente = new ApiCliente(apiUrl);
        String csrfPrimero = primerCliente.obtenerCsrf(false);
        String csrfSegundo = segundoCliente.obtenerCsrf(false);
        CyclicBarrier salida = new CyclicBarrier(2);
        CompletableFuture<HttpResponse<String>> primero = CompletableFuture.supplyAsync(() -> completarConcurrente(
                primerCliente, csrfPrimero, completar, salida));
        CompletableFuture<HttpResponse<String>> segundo = CompletableFuture.supplyAsync(() -> completarConcurrente(
                segundoCliente, csrfSegundo, completar, salida));
        CompletableFuture.allOf(primero, segundo).get(30, TimeUnit.SECONDS);
        List<HttpResponse<String>> respuestas = List.of(primero.join(), segundo.join());
        assertEquals(1, respuestas.stream().filter(respuesta -> respuesta.statusCode() == 204).count());
        assertEquals(1, respuestas.stream().filter(respuesta -> respuesta.statusCode() == 410).count());

        HttpResponse<String> detalleFinal = detalle(operadorId);
        assertTrue(revision(etag(detalleFinal)) > revision(etagAntes));
        assertNotEquals(hashAntes, hashContrasena(operadorId));
        assertEquals(1, recuperacionesConsumidas(operadorId));
        assertEquals(200, dueno.get("/api/v1/panel").statusCode(),
                "La recuperación del operador no debe revocar la sesión del DUENO.");
    }

    private UUID registrar(String correo) throws Exception {
        HttpResponse<String> respuesta = dueno.post(RUTA,
                Map.of("nombres", "Recuperacion", "primerApellido", "Concurrente",
                        "segundoApellido", "FaseDos", "correo", correo),
                clave("registro-" + correo), csrf);
        assertEquals(201, respuesta.statusCode());
        return UUID.fromString(texto(leerJson(respuesta.body()), "id"));
    }

    private HttpResponse<String> detalle(UUID operadorId) throws Exception {
        HttpResponse<String> respuesta = dueno.get(RUTA + "/" + operadorId);
        assertEquals(200, respuesta.statusCode());
        return respuesta;
    }

    private static HttpResponse<String> completarConcurrente(
            ApiCliente cliente, String tokenCsrf, Map<String, String> solicitud, CyclicBarrier salida) {
        try {
            salida.await(10, TimeUnit.SECONDS);
            return cliente.postJson("/api/v1/operadores/recuperacion/completar",
                    solicitud, Map.of(CSRF, tokenCsrf));
        } catch (Exception excepcion) {
            throw new CompletionException(excepcion);
        }
    }

    private static String extraerToken(String mensaje, Pattern formato) {
        Matcher matcher = formato.matcher(mensaje);
        assertTrue(matcher.find(), "El correo sintético debe incluir el token de propósito esperado.");
        return matcher.group(1);
    }

    private static long revision(String etag) {
        return Long.parseLong(etag.replace("\"", ""));
    }

    private static String hashContrasena(UUID operadorId) throws Exception {
        try (Connection conexion = conexion();
                PreparedStatement consulta = conexion.prepareStatement(
                        "SELECT hash_contrasena_acceso FROM cuenta WHERE id = ? AND rol = 'OPERADOR'")) {
            consulta.setObject(1, operadorId);
            try (ResultSet resultado = consulta.executeQuery()) {
                assertTrue(resultado.next());
                return resultado.getString(1);
            }
        }
    }

    private static int recuperacionesConsumidas(UUID operadorId) throws Exception {
        try (Connection conexion = conexion();
                PreparedStatement consulta = conexion.prepareStatement(
                        "SELECT count(*) FROM recuperacion_contrasena_operador "
                                + "WHERE operador_id = ? AND consumido_en IS NOT NULL")) {
            consulta.setObject(1, operadorId);
            try (ResultSet resultado = consulta.executeQuery()) {
                assertTrue(resultado.next());
                return resultado.getInt(1);
            }
        }
    }

    private static Connection conexion() throws Exception {
        return DriverManager.getConnection(System.getenv("TEST_DATABASE_URL"),
                System.getenv("TEST_DATABASE_USER"), System.getenv("TEST_DATABASE_PASSWORD"));
    }
}
