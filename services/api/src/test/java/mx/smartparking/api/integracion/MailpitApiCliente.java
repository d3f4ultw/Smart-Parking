package mx.smartparking.api.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.io.IOException;
import java.net.InetAddress;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Cliente HTTP mínimo para observar solo los mensajes de Mailpit del proyecto descartable. */
final class MailpitApiCliente {

    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final HttpClient HTTP = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(3))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();

    private MailpitApiCliente() {
    }

    static URI baseUrlOptIn(String property) throws Exception {
        assumeTrue(Boolean.parseBoolean(System.getProperty("smartparking.integration.disposable", "false")),
                "La aceptación HTTP requiere smartparking.integration.disposable=true.");
        return localUrlOptIn(property, "Mailpit");
    }

    static URI localUrlOptIn(String property, String serviceName) throws Exception {
        String configured = System.getProperty(property);
        assertTrue(configured != null && !configured.isBlank(),
                "Falta la URL local requerida para la aceptación.");

        URI base;
        try {
            base = URI.create(configured.strip());
        } catch (IllegalArgumentException exception) {
            throw new AssertionError("La URL local configurada no es válida.");
        }
        assertTrue("http".equalsIgnoreCase(base.getScheme()) || "https".equalsIgnoreCase(base.getScheme()),
                "El endpoint local debe usar HTTP(S) loopback.");
        assertTrue(base.getHost() != null, "La URL local debe tener host.");
        assertTrue(base.getUserInfo() == null && base.getQuery() == null && base.getFragment() == null,
                "La URL local no debe contener credenciales, consulta ni fragmento.");
        assertTrue(base.getPath().isEmpty() || "/".equals(base.getPath()),
                "La URL local debe apuntar a la raíz.");
        InetAddress[] addresses = InetAddress.getAllByName(base.getHost());
        assertTrue(addresses.length > 0 && Arrays.stream(addresses).allMatch(InetAddress::isLoopbackAddress),
                serviceName + " de aceptación solo puede estar expuesto en loopback.");
        return base;
    }

    static int cantidadMensajes(URI base) throws IOException, InterruptedException {
        JsonNode raiz = getJson(base.resolve("/api/v1/messages?limit=100"));
        return raiz.path("total").asInt(-1);
    }

    static int cantidadPorAsunto(URI base, String subject) throws IOException, InterruptedException {
        JsonNode raiz = getJson(base.resolve("/api/v1/messages?limit=100"));
        int count = 0;
        for (JsonNode message : raiz.path("messages")) {
            if (subject.equals(message.path("Subject").asText())) {
                count++;
            }
        }
        return count;
    }

    static String textoUnico(URI base, String subject, String recipient)
            throws IOException, InterruptedException {
        List<String> texts = textosPorAsunto(base, subject, recipient);
        assertEquals(1, texts.size(), "Mailpit debe contener exactamente el mensaje esperado.");
        return texts.getFirst();
    }

    static List<String> textosPorAsunto(URI base, String subject, String recipient)
            throws IOException, InterruptedException {
        JsonNode raiz = getJson(base.resolve("/api/v1/messages?limit=100"));
        List<String> ids = new ArrayList<>();
        for (JsonNode message : raiz.path("messages")) {
            if (subject.equals(message.path("Subject").asText()) && tieneDestinatario(message, recipient)) {
                String id = message.path("ID").asText("");
                if (!id.isBlank()) {
                    ids.add(id);
                }
            }
        }
        List<String> texts = new ArrayList<>();
        for (String id : ids) {
            String encodedId = URLEncoder.encode(id, StandardCharsets.UTF_8).replace("+", "%20");
            JsonNode detalle = getJson(base.resolve("/api/v1/message/" + encodedId));
            texts.add(detalle.path("Text").asText(""));
        }
        return List.copyOf(texts);
    }

    private static boolean tieneDestinatario(JsonNode message, String recipient) {
        JsonNode recipients = message.path("To");
        if (recipients.isArray()) {
            for (JsonNode address : recipients) {
                if (recipient.equals(address.path("Address").asText())) {
                    return true;
                }
            }
        }
        return false;
    }

    private static JsonNode getJson(URI uri) throws IOException, InterruptedException {
        HttpRequest request = HttpRequest.newBuilder(uri)
                .timeout(Duration.ofSeconds(5))
                .header("Accept", "application/json")
                .GET()
                .build();
        HttpResponse<String> response = HTTP.send(request, HttpResponse.BodyHandlers.ofString());
        assertEquals(200, response.statusCode(), "El endpoint de Mailpit local debe responder HTTP 200.");
        return JSON.readTree(response.body());
    }
}
