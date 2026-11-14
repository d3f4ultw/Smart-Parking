package mx.smartparking.api.integracion;

import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.clave;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.etag;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.leerJson;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.numero;
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
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import mx.smartparking.api.integracion.ApiCliente;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;

/** Acepta la reemisión HTTP, su replay, el reemplazo del token y la cuota horaria. */
final class OperadoresAdministracionReemisionAceptacionTest {

    private static final String RUTA = "/api/v1/operadores";
    private static final String CSRF = "X-CSRF-TOKEN";
    private static final String ASUNTO_INVITACION = "Activa tu cuenta de Smart Parking";
    private static final Pattern TOKEN_ACTIVACION =
            Pattern.compile("https?://[^\\s#]+/activar-operador#([A-Za-z0-9_-]{43})");

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
    void replayNoDuplicaCorreoYLaReemisionInvalidaElTokenAnterior() throws Exception {
        String sufijo = UUID.randomUUID().toString();
        String correo = "reemision." + sufijo + "@example.test";
        UUID operadorId = registrar(correo);
        String mensajeInicial = MailpitApiCliente.textoUnico(mailpitUrl, ASUNTO_INVITACION, correo);
        String tokenInicial = extraerToken(mensajeInicial);
        String revision = etag(detalle(operadorId));
        volverDisponibleLaInvitacion(operadorId);
        String claveReemision = clave("reemitir-" + sufijo);

        HttpResponse<String> respuesta = reemitir(operadorId, revision, claveReemision);
        assertEquals(200, respuesta.statusCode());
        assertEquals("ENVIADO", texto(leerJson(respuesta.body()), "estadoInvitacion"));
        assertFalse(respuesta.body().contains(tokenInicial));
        List<String> mensajes = MailpitApiCliente.textosPorAsunto(mailpitUrl, ASUNTO_INVITACION, correo);
        assertEquals(2, mensajes.size());
        String mensajeNuevo = mensajes.stream()
                .filter(mensaje -> !mensaje.equals(mensajeInicial))
                .findFirst()
                .orElseThrow(() -> new AssertionError("La reemisión debe entregar un único mensaje nuevo."));
        String tokenNuevo = extraerToken(mensajeNuevo);
        assertNotEquals(tokenInicial, tokenNuevo);
        assertEquals(410, validarToken(tokenInicial).statusCode());
        assertEquals(200, validarToken(tokenNuevo).statusCode());

        HttpResponse<String> replay = reemitir(operadorId, revision, claveReemision);
        assertEquals(200, replay.statusCode());
        assertEquals("ENVIADO", texto(leerJson(replay.body()), "estadoInvitacion"));
        assertEquals(2, MailpitApiCliente.textosPorAsunto(mailpitUrl, ASUNTO_INVITACION, correo).size(),
                "Repetir la clave no debe enviar otra invitación.");
    }

    @Test
    void cuotaCuentaReemisionesYReactivacionesDeLaUltimaHora() throws Exception {
        String sufijo = UUID.randomUUID().toString();
        String correo = "cuota.reemision." + sufijo + "@example.test";
        UUID operadorId = registrar(correo);
        String mensajeInicial = MailpitApiCliente.textoUnico(mailpitUrl, ASUNTO_INVITACION, correo);
        String tokenInicial = extraerToken(mensajeInicial);
        String revision = etag(detalle(operadorId));
        volverDisponibleLaInvitacion(operadorId);
        insertarAccionesHorarias(operadorId, Long.parseLong(revision.replace("\"", "")));

        JsonNode detalleConCuota = leerJson(detalle(operadorId).body());
        assertEquals(0, numero(detalleConCuota, "reemisionesRestantes"));
        assertFalse(detalleConCuota.path("puedeReemitirInvitacion").asBoolean());
        HttpResponse<String> limitada = reemitir(operadorId, revision, clave("cuota-" + sufijo));
        assertEquals(429, limitada.statusCode());
        assertEquals("REENVIO_LIMITE_ALCANZADO", texto(leerJson(limitada.body()), "codigo"));
        assertTrue(limitada.headers().firstValue("Retry-After").isPresent());
        assertEquals(1, MailpitApiCliente.textosPorAsunto(mailpitUrl, ASUNTO_INVITACION, correo).size());
        assertEquals(200, validarToken(tokenInicial).statusCode(),
                "La solicitud limitada debe conservar vigente la invitación anterior.");
    }

    @Test
    void rechazaCambioDeEstadoSinCsrfYConservaLaCuentaPendiente() throws Exception {
        UUID operadorId = registrar("csrf.operador." + UUID.randomUUID() + "@example.test");
        String revision = etag(detalle(operadorId));
        HttpResponse<String> respuesta = dueno.patchSinCsrf(
                RUTA + "/" + operadorId + "/estado", Map.of("estado", "INACTIVA"),
                revision, clave("sin-csrf-" + operadorId));

        assertEquals(403, respuesta.statusCode());
        assertEquals("PENDIENTE", texto(leerJson(detalle(operadorId).body()), "estado"));
    }

    private UUID registrar(String correo) throws Exception {
        HttpResponse<String> respuesta = dueno.post(RUTA,
                Map.of("nombres", "Reemision", "primerApellido", "Aceptacion",
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

    private HttpResponse<String> reemitir(UUID operadorId, String revision, String claveIdempotencia)
            throws Exception {
        return dueno.postJson(RUTA + "/" + operadorId + "/invitacion/reemitir", null,
                Map.of(CSRF, csrf, "If-Match", revision, "Idempotency-Key", claveIdempotencia));
    }

    private HttpResponse<String> validarToken(String token) throws Exception {
        return dueno.postJson("/api/v1/operadores/activacion/validar", Map.of("token", token), Map.of(CSRF, csrf));
    }

    private static String extraerToken(String mensaje) {
        Matcher matcher = TOKEN_ACTIVACION.matcher(mensaje);
        assertTrue(matcher.find(), "El correo sintético debe contener el token de activación.");
        return matcher.group(1);
    }

    private void volverDisponibleLaInvitacion(UUID operadorId) throws Exception {
        Instant generado = Instant.now().minus(Duration.ofSeconds(90));
        try (Connection conexion = conexion();
                PreparedStatement actualizacion = conexion.prepareStatement(
                        "UPDATE invitacion_operador SET generado_en = ?, vence_en = ?, intento_iniciado_en = ? "
                                + "WHERE operador_id = ? AND consumido_en IS NULL")) {
            actualizacion.setTimestamp(1, Timestamp.from(generado));
            actualizacion.setTimestamp(2, Timestamp.from(generado.plus(Duration.ofHours(2))));
            actualizacion.setTimestamp(3, Timestamp.from(generado));
            actualizacion.setObject(4, operadorId);
            assertEquals(1, actualizacion.executeUpdate());
        }
    }

    private void insertarAccionesHorarias(UUID operadorId, long revision) throws Exception {
        String sql = "INSERT INTO idempotencia_accion_operador "
                + "(operador_id, operacion, clave_hash, creada_en, estado_envio, revision_acceso, vence_en) "
                + "VALUES (?, ?, ?, ?, 'ENVIADO', ?, NULL)";
        try (Connection conexion = conexion(); PreparedStatement insercion = conexion.prepareStatement(sql)) {
            for (int indice = 0; indice < 3; indice++) {
                insercion.setObject(1, operadorId);
                insercion.setString(2, indice == 2 ? "REACTIVAR" : "REEMITIR_INVITACION");
                insercion.setString(3, String.format(java.util.Locale.ROOT, "%064x", indice + 1));
                insercion.setTimestamp(4, Timestamp.from(Instant.now().minus(Duration.ofMinutes(55 - 15 * indice))));
                insercion.setLong(5, revision);
                assertEquals(1, insercion.executeUpdate());
            }
        }
    }

    private static Connection conexion() throws Exception {
        return DriverManager.getConnection(System.getenv("TEST_DATABASE_URL"),
                System.getenv("TEST_DATABASE_USER"), System.getenv("TEST_DATABASE_PASSWORD"));
    }
}
