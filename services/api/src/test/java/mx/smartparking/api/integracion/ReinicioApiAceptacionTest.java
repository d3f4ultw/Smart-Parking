package mx.smartparking.api.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Arrays;
import java.util.concurrent.TimeUnit;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import org.junit.jupiter.api.Test;

/** Reinicio opt-in del API por ID explícito, solo tras validar sus etiquetas Compose. */
class ReinicioApiAceptacionTest {

    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final HttpClient HTTP = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(2))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();

    @Test
    void reinicioDelApiAisladoConservaEstadoYVuelveASaludUp() throws Exception {
        assumeTrue(Boolean.parseBoolean(System.getProperty("smartparking.integration.disposable", "false")),
                "Reinicio omitido: requiere smartparking.integration.disposable=true.");

        String projectName = System.getProperty("smartparking.integration.project-name", "").strip();
        String containerId = System.getProperty("smartparking.integration.api-container-id", "").strip();
        assertTrue(projectName.matches("[a-z0-9][a-z0-9_.-]{0,62}"),
                "El reinicio requiere el nombre exacto del proyecto de prueba.");
        assertTrue(containerId.matches("(?i)[0-9a-f]{12,64}"),
                "El reinicio requiere el ID explícito del contenedor API.");

        URI api = MailpitApiCliente.localUrlOptIn(
                "smartparking.integration.smtp-failure-api-url", "API de reinicio");
        URI mailpit = MailpitApiCliente.localUrlOptIn(
                "smartparking.integration.smtp-failure-mailpit-url", "Mailpit de reinicio");
        assertHealthUp(api);
        assertEquals("CONFIGURADA", text(getJson(api, "/api/v1/configuracion/estado"), "estado"),
                "El escenario SMTP aislado debe haber confirmado la configuración.");
        assertEquals(0, MailpitApiCliente.cantidadMensajes(mailpit));

        JsonNode labels = inspeccionarEtiquetas(containerId);
        assertEquals(projectName, text(labels, "com.docker.compose.project"),
                "El contenedor debe pertenecer exactamente al proyecto autorizado.");
        assertEquals("api", text(labels, "com.docker.compose.service"),
                "Solo se permite reiniciar el servicio API identificado.");
        assertEquals(projectName, text(labels, "com.smartparking.testing.run"),
                "El contenedor debe llevar la etiqueta del mismo proyecto descartable.");

        ejecutarPodman(30, "restart", "--time", "10", containerId);
        esperarHealthUp(api, Duration.ofSeconds(60));
        assertEquals("CONFIGURADA", text(getJson(api, "/api/v1/configuracion/estado"), "estado"),
                "El reinicio del proceso debe conservar la configuración persistida.");
        assertEquals(0, MailpitApiCliente.cantidadMensajes(mailpit),
                "El reinicio no debe volver a intentar el correo SMTP fallido.");
    }

    private static JsonNode inspeccionarEtiquetas(String containerId) throws Exception {
        String output = ejecutarPodman(15, "inspect", "--format={{json .Config.Labels}}", containerId);
        try {
            return JSON.readTree(output);
        } catch (RuntimeException exception) {
            throw new AssertionError("Podman debe devolver las etiquetas JSON del contenedor indicado.");
        }
    }

    private static String ejecutarPodman(int timeoutSeconds, String... arguments) throws Exception {
        String[] invocation = new String[arguments.length + 1];
        invocation[0] = "podman";
        System.arraycopy(arguments, 0, invocation, 1, arguments.length);
        Process process = new ProcessBuilder(invocation).redirectErrorStream(true).start();
        if (!process.waitFor(timeoutSeconds, TimeUnit.SECONDS)) {
            process.destroyForcibly();
            throw new AssertionError("El comando Podman debe completar dentro del límite.");
        }
        byte[] output = process.getInputStream().readAllBytes();
        assertEquals(0, process.exitValue(), "La operación Podman sobre el ID validado debe completarse.");
        return new String(output, StandardCharsets.UTF_8).strip();
    }

    private static JsonNode getJson(URI base, String path) throws IOException, InterruptedException {
        HttpRequest request = HttpRequest.newBuilder(base.resolve(path))
                .timeout(Duration.ofSeconds(4))
                .header("Accept", "application/json")
                .GET()
                .build();
        HttpResponse<String> response = HTTP.send(request, HttpResponse.BodyHandlers.ofString());
        assertEquals(200, response.statusCode(), "El API aislado debe responder HTTP 200.");
        return JSON.readTree(response.body());
    }

    private static void assertHealthUp(URI api) throws IOException, InterruptedException {
        assertEquals("UP", text(getJson(api, "/actuator/health"), "status"));
    }

    private static void esperarHealthUp(URI api, Duration timeout) throws InterruptedException {
        long deadline = System.nanoTime() + timeout.toNanos();
        while (System.nanoTime() < deadline) {
            try {
                HttpRequest request = HttpRequest.newBuilder(api.resolve("/actuator/health"))
                        .timeout(Duration.ofSeconds(4))
                        .header("Accept", "application/json")
                        .GET()
                        .build();
                HttpResponse<String> response = HTTP.send(request, HttpResponse.BodyHandlers.ofString());
                if (response.statusCode() == 200 && "UP".equals(text(JSON.readTree(response.body()), "status"))) {
                    return;
                }
            } catch (IOException ignored) {
                // La API puede rechazar conexiones mientras Spring vuelve a iniciar.
            }
            Thread.sleep(500);
        }
        throw new AssertionError("La API no volvió a salud UP dentro de 60 segundos.");
    }

    private static String text(JsonNode node, String field) {
        return node.path(field).asText("");
    }
}
