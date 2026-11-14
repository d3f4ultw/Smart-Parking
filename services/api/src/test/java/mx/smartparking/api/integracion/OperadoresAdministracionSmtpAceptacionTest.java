package mx.smartparking.api.integracion;

import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.leerJson;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.texto;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.time.Duration;
import java.util.Map;
import java.util.UUID;
import mx.smartparking.api.integracion.ApiCliente;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Comprueba por HTTP y PostgreSQL que un fallo SMTP no cambia la credencial activa. */
final class OperadoresAdministracionSmtpAceptacionTest {

    private static final String CSRF = "X-CSRF-TOKEN";
    private static final UUID OPERADOR_FIXTURE = UUID.fromString("10000000-0000-4000-8000-000000000001");
    private static final HttpClient HTTP = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(4))
            .build();
    private static final JsonMapper JSON = JsonMapper.builder().build();

    @Test
    void correoDeRecuperacionFallidoConservaHashYNoEntregaMensaje() throws Exception {
        assumeTrue(Boolean.parseBoolean(System.getProperty("smartparking.integration.disposable", "false")),
                "Aceptación omitida: requiere la base desechable de Fase 2.");
        URI apiUrl = OperadoresAdministracionEntornoAceptacion.apiSmtpFallidoUrl();
        URI mailpitUrl = OperadoresAdministracionEntornoAceptacion.mailpitUrl();
        String correoDueno = System.getenv("TEST_OWNER_EMAIL");
        String contrasenaDueno = System.getenv("TEST_OWNER_PASSWORD");
        assumeTrue(correoDueno != null && correoDueno.endsWith("@example.test")
                        && contrasenaDueno != null && !contrasenaDueno.isBlank(),
                "La aceptación requiere credenciales sintéticas del propietario.");
        OperadoresAdministracionEntornoAceptacion.prepararCredencialDueno(correoDueno, contrasenaDueno);
        String correoOperador = "activa.v6@example.test";
        assertEquals(0, contarMensajes(mailpitUrl, correoOperador));

        ApiCliente api = new ApiCliente(apiUrl);
        String csrf = api.obtenerCsrf(true);
        HttpResponse<String> login = api.postJson("/api/v1/sesion",
                Map.of("correo", correoDueno, "contrasena", contrasenaDueno), Map.of(CSRF, csrf));
        assertEquals(200, login.statusCode());
        String csrfRenovado = texto(leerJson(login.body()), "csrfToken");
        api.csrf(csrfRenovado);
        String hashAntes = hashContrasena(OPERADOR_FIXTURE);

        HttpResponse<String> detalle = api.get("/api/v1/operadores/" + OPERADOR_FIXTURE);
        assertEquals(200, detalle.statusCode());
        String etag = detalle.headers().firstValue("ETag")
                .orElseThrow(() -> new AssertionError("El detalle debe exponer ETag."));
        HttpResponse<String> solicitud = api.postJson("/api/v1/operadores/" + OPERADOR_FIXTURE + "/recuperacion",
                null, Map.of(CSRF, csrfRenovado, "If-Match", etag, "Idempotency-Key", UUID.randomUUID().toString()));

        assertEquals(200, solicitud.statusCode());
        JsonNode respuesta = leerJson(solicitud.body());
        assertEquals("FALLIDO", texto(respuesta, "estadoEnvio"));
        assertTrue(respuesta.hasNonNull("venceEn"));
        assertFalse(solicitud.body().contains("token"));
        assertEquals(hashAntes, hashContrasena(OPERADOR_FIXTURE),
                "Un fallo de correo no debe cambiar la contraseña vigente.");
        assertEquals(0, contarMensajes(mailpitUrl, correoOperador));
    }

    private static String hashContrasena(UUID cuentaId) throws Exception {
        String url = System.getenv("TEST_DATABASE_URL");
        String usuario = System.getenv("TEST_DATABASE_USER");
        String contrasena = System.getenv("TEST_DATABASE_PASSWORD");
        assumeTrue(url != null && usuario != null && contrasena != null,
                "La aceptación SMTP requiere acceso a la base desechable para comparar hashes.");
        try (Connection conexion = DriverManager.getConnection(url, usuario, contrasena);
                PreparedStatement consulta = conexion.prepareStatement(
                        "SELECT hash_contrasena_acceso FROM cuenta WHERE id = ? AND rol = 'OPERADOR' AND estado = 'ACTIVA'")) {
            consulta.setObject(1, cuentaId);
            try (ResultSet resultado = consulta.executeQuery()) {
                assertTrue(resultado.next(), "La fixture V6 debe conservar la cuenta activa.");
                return resultado.getString(1);
            }
        }
    }

    private static int contarMensajes(URI mailpitUrl, String destinatario) throws Exception {
        HttpRequest solicitud = HttpRequest.newBuilder(mailpitUrl.resolve("/api/v1/messages?limit=100"))
                .timeout(Duration.ofSeconds(8))
                .GET()
                .build();
        JsonNode mensajes = JSON.readTree(HTTP.send(solicitud, HttpResponse.BodyHandlers.ofString()).body());
        int cantidad = 0;
        for (JsonNode mensaje : mensajes.path("messages")) {
            for (JsonNode direccion : mensaje.path("To")) {
                if (destinatario.equals(direccion.path("Address").asText())) {
                    cantidad++;
                    break;
                }
            }
        }
        return cantidad;
    }
}
