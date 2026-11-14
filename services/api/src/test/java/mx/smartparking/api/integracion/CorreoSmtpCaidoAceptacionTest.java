package mx.smartparking.api.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.io.IOException;
import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.InetAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Arrays;
import java.util.Map;
import java.util.UUID;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import org.junit.jupiter.api.Test;

/** Aceptación opt-in de persistencia cuando no hay transporte SMTP disponible. */
class CorreoSmtpCaidoAceptacionTest {

    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final String CSRF = "X-CSRF-TOKEN";

    @Test
    void smtpRechazadoNoRevierteConfiguracionNiReintentaElRetryIdempotente() throws Exception {
        assumeTrue(Boolean.parseBoolean(System.getProperty("smartparking.integration.disposable", "false")),
                "Aceptación omitida: requiere smartparking.integration.disposable=true.");
        URI apiUrl = localUrl("smartparking.integration.smtp-failure-api-url", "API de SMTP fallido");
        URI mailpitUrl = localUrl(
                "smartparking.integration.smtp-failure-mailpit-url", "Mailpit del proyecto SMTP fallido");
        assertEquals(0, MailpitApiCliente.cantidadMensajes(mailpitUrl),
                "El Mailpit aislado debe iniciar vacío.");

        ClienteApi api = new ClienteApi(apiUrl);
        assertHealthUp(api);
        String suffix = UUID.randomUUID().toString().replace("-", "");
        String email = "smtp.fallido." + suffix + "@example.test";
        String accessPassword = "acceso SMTP aislado 2026 A!";
        String administrativePassword = "admin SMTP aislado 2026 B!";
        String idempotencyKey = "smtp-fallido-" + suffix;

        String csrf = api.obtenerCsrf();
        Map<String, Object> configuration = configuration(
                email, accessPassword, administrativePassword);
        HttpResponse<String> response = api.configurar(configuration, csrf, idempotencyKey);
        assertEquals(201, response.statusCode(), "La escritura debe confirmarse aunque SMTP rechace la conexión.");
        JsonNode result = readJson(response.body());
        assertEquals("CONFIGURADA", text(result, "estado"));
        long revision = number(result, "revision");
        assertEquals("FALLIDO", text(result, "avisoBienvenida"),
                "La conexión rechazada antes de aceptar el correo debe reportar FALLIDO.");
        verifyNoSecrets(response.body(), accessPassword, administrativePassword);

        HttpResponse<String> publicState = api.get("/api/v1/configuracion/estado");
        assertEquals(200, publicState.statusCode());
        assertEquals("CONFIGURADA", text(readJson(publicState.body()), "estado"),
                "El fallo de SMTP debe ocurrir después del commit.");
        assertHealthUp(api);
        assertEquals(0, MailpitApiCliente.cantidadMensajes(mailpitUrl),
                "El Mailpit sin listener SMTP no debe recibir mensajes.");

        HttpResponse<String> retry = api.configurar(configuration, csrf, idempotencyKey);
        assertEquals(201, retry.statusCode(), "El retry idempotente debe devolver la transición confirmada.");
        JsonNode retried = readJson(retry.body());
        assertEquals(revision, number(retried, "revision"));
        assertEquals("FALLIDO", text(retried, "avisoBienvenida"));
        verifyNoSecrets(retry.body(), accessPassword, administrativePassword);
        assertEquals(0, MailpitApiCliente.cantidadMensajes(mailpitUrl),
                "El retry idempotente no debe intentar ni duplicar un envío.");
        assertHealthUp(api);
    }

    private static URI localUrl(String property, String description) throws Exception {
        String configured = System.getProperty(property);
        assertTrue(configured != null && !configured.isBlank(), "Falta la URL loopback para la aceptación.");
        URI base;
        try {
            base = URI.create(configured.strip());
        } catch (IllegalArgumentException exception) {
            throw new AssertionError("La URL de aceptación no es válida.");
        }
        assertTrue("http".equalsIgnoreCase(base.getScheme()) || "https".equalsIgnoreCase(base.getScheme()),
                "El endpoint debe usar HTTP(S).");
        assertTrue(base.getHost() != null && base.getUserInfo() == null
                        && base.getQuery() == null && base.getFragment() == null,
                "La URL no debe contener credenciales, consulta ni fragmento.");
        assertTrue(base.getPath().isEmpty() || "/".equals(base.getPath()),
                "La URL debe apuntar a la raíz del servicio.");
        InetAddress[] addresses = InetAddress.getAllByName(base.getHost());
        assertTrue(addresses.length > 0 && Arrays.stream(addresses).allMatch(InetAddress::isLoopbackAddress),
                description + " solo puede exponerse en loopback.");
        return base;
    }

    private static Map<String, Object> configuration(String email, String access, String administrative) {
        Map<String, Object> owner = Map.of(
                "nombres", "Propietaria SMTP",
                "primerApellido", "Prueba",
                "segundoApellido", "Aislada",
                "correo", email,
                "contrasenaAcceso", access,
                "contrasenaAdministrativa", administrative);
        Map<String, Object> schedule = Map.of(
                "modo", "INTERVALO_DIARIO",
                "zonaHoraria", "America/Mexico_City",
                "horaApertura", "22:00",
                "horaCierre", "06:00");
        Map<String, Object> parking = Map.of(
                "nombre", "Estacionamiento SMTP de prueba",
                "tipo", "PUBLICO",
                "horario", schedule);
        return Map.of("propietario", owner, "estacionamiento", parking);
    }

    private static void assertHealthUp(ClienteApi api) throws Exception {
        HttpResponse<String> health = api.get("/actuator/health");
        assertEquals(200, health.statusCode(), "La API debe permanecer sana tras un fallo SMTP.");
        assertEquals("UP", text(readJson(health.body()), "status"));
    }

    private static JsonNode readJson(String body) {
        return JSON.readTree(body);
    }

    private static String text(JsonNode node, String field) {
        return node.path(field).asText("");
    }

    private static long number(JsonNode node, String field) {
        return node.path(field).asLong(-1);
    }

    private static void verifyNoSecrets(String body, String... secrets) {
        boolean exposed = Arrays.stream(secrets)
                .filter(secret -> secret != null && !secret.isBlank())
                .anyMatch(body::contains);
        assertFalse(exposed, "La respuesta no debe devolver credenciales ni grants.");
    }

    private static final class ClienteApi {

        private final URI base;
        private final CookieManager cookies = new CookieManager(null, CookiePolicy.ACCEPT_ALL);
        private final HttpClient client = HttpClient.newBuilder()
                .cookieHandler(cookies)
                .connectTimeout(Duration.ofSeconds(4))
                .followRedirects(HttpClient.Redirect.NEVER)
                .build();

        private ClienteApi(URI base) {
            this.base = base;
        }

        private String obtenerCsrf() throws Exception {
            HttpResponse<String> response = get("/api/v1/csrf");
            assertEquals(200, response.statusCode(), "La API debe entregar CSRF para la sesión local.");
            String csrf = text(readJson(response.body()), "token");
            assertTrue(!csrf.isBlank(), "La sesión debe entregar un token CSRF.");
            return csrf;
        }

        private HttpResponse<String> configurar(Map<String, Object> configuration, String csrf, String key)
                throws IOException, InterruptedException {
            return send("POST", "/api/v1/configuracion/inicial", configuration,
                    Map.of(CSRF, csrf, "Idempotency-Key", key));
        }

        private HttpResponse<String> get(String path) throws IOException, InterruptedException {
            return send("GET", path, null, Map.of());
        }

        private HttpResponse<String> send(
                String method,
                String path,
                Object body,
                Map<String, String> headers) throws IOException, InterruptedException {
            HttpRequest.Builder request = HttpRequest.newBuilder(base.resolve(path))
                    .timeout(Duration.ofSeconds(12))
                    .header("Accept", "application/json");
            headers.forEach(request::header);
            if (body == null) {
                request.method(method, HttpRequest.BodyPublishers.noBody());
            } else {
                request.header("Content-Type", "application/json")
                        .method(method, HttpRequest.BodyPublishers.ofString(JSON.writeValueAsString(body)));
            }
            return client.send(request.build(), HttpResponse.BodyHandlers.ofString());
        }
    }
}
