package mx.smartparking.api.integracion.clientes.membresia;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.InetAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.time.Duration;
import java.time.Instant;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.Map;
import java.util.UUID;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

/** Comprueba los contratos HTTP de membresía solo contra la API desechable. */
class ClientesMembresiaApiAceptacionTest {

    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final String CSRF = "X-CSRF-TOKEN";
    private static final String REGISTRO = "/api/v1/clientes/registro";
    private static final String SESION = "/api/v1/clientes/sesion";
    private static final String PORTAL = "/api/v1/clientes/portal";
    private static final String CHECKOUT = "/api/v1/clientes/membresia/checkout";
    private static final String WEBHOOK = "/api/v1/webhooks/stripe";

    private static URI base;

    @BeforeAll
    static void configurarApiDesechable() throws Exception {
        assumeTrue(Boolean.getBoolean("smartparking.integration.disposable"),
                "La aceptación requiere una API desechable explícita.");
        String baseConfigurada = System.getProperty("smartparking.api-url", "").strip();
        assertFalse(baseConfigurada.isEmpty(), "La aceptación requiere smartparking.api-url.");
        base = URI.create(baseConfigurada);
        assertTrue("http".equalsIgnoreCase(base.getScheme()) || "https".equalsIgnoreCase(base.getScheme()));
        assertTrue(base.getHost() != null && base.getUserInfo() == null && base.getQuery() == null);
        assertTrue(Arrays.stream(InetAddress.getAllByName(base.getHost()))
                .allMatch(InetAddress::isLoopbackAddress), "La API debe estar en loopback.");
    }

    @Test
    void registroConUnaContrasenaYPortalSinMembresia() throws Exception {
        ClienteApi cliente = crearCliente();
        HttpResponse<String> respuesta = cliente.get(PORTAL);
        assertEquals(200, respuesta.statusCode());
        JsonNode cuerpo = JSON.readTree(respuesta.body());
        JsonNode membresia = cuerpo.path("membresia");
        assertEquals("SIN_MEMBRESIA", membresia.path("estado").asText());
        assertEquals(39_900, membresia.path("plan").path("importeMenorUnidad").asInt());
        assertEquals("MXN", membresia.path("plan").path("moneda").asText());
        assertEquals("month", membresia.path("plan").path("intervalo").asText());
        assertTrue(membresia.path("puedeComprar").asBoolean());
        assertNoContieneSecretoConfigurado(respuesta.body(), "STRIPE_API_KEY");
    }

    @Test
    void checkoutExigeCsrfYRepiteElMismoIntentoConLaMismaClave() throws Exception {
        ClienteApi cliente = crearCliente();
        String clave = UUID.randomUUID().toString();

        HttpResponse<String> sinCsrf = cliente.post(CHECKOUT, null, Map.of("Idempotency-Key", clave));
        assertEquals(403, sinCsrf.statusCode());

        Map<String, String> encabezados = Map.of(CSRF, cliente.tokenCsrf, "Idempotency-Key", clave);
        HttpResponse<String> primera = cliente.post(CHECKOUT, null, encabezados);
        assertEquals(201, primera.statusCode());
        JsonNode intento = JSON.readTree(primera.body());
        String intentoId = intento.path("intentoId").asText();
        String checkoutUrl = intento.path("checkoutUrl").asText();
        URI url = URI.create(checkoutUrl);
        assertFalse(intentoId.isBlank());
        assertTrue("https".equalsIgnoreCase(url.getScheme()));
        assertEquals("checkout.stripe.com", url.getHost());
        assertFalse(intento.has("customerId"));
        assertFalse(intento.has("priceId"));
        assertNoContieneSecretoConfigurado(primera.body(), "STRIPE_API_KEY");
        assertNoContieneSecretoConfigurado(primera.body(), "STRIPE_WEBHOOK_SECRET");

        HttpResponse<String> repetida = cliente.post(CHECKOUT, null, encabezados);
        assertEquals(200, repetida.statusCode());
        JsonNode replay = JSON.readTree(repetida.body());
        assertEquals(intentoId, replay.path("intentoId").asText());
        assertEquals(checkoutUrl, replay.path("checkoutUrl").asText());
    }

    @Test
    void clavesDistintasNoAbrenDosCheckoutConcurrentes() throws Exception {
        ClienteApi cliente = crearCliente();
        HttpResponse<String> sinCsrf = cliente.post(CHECKOUT, null, Map.of(
                CSRF, cliente.tokenCsrf,
                "Idempotency-Key", UUID.randomUUID().toString()));
        assertEquals(201, sinCsrf.statusCode());
        JsonNode intento = JSON.readTree(sinCsrf.body());
        assertFalse(intento.path("intentoId").asText().isBlank());

        HttpResponse<String> otroIntento = cliente.post(CHECKOUT, null, Map.of(
                CSRF, cliente.tokenCsrf,
                "Idempotency-Key", UUID.randomUUID().toString()));
        assertEquals(409, otroIntento.statusCode());
        assertEquals("CHECKOUT_PENDIENTE", JSON.readTree(otroIntento.body()).path("codigo").asText());
    }

    @Test
    void webhookNoRequiereSesionPeroRechazaFirmaAusenteInvalidaYModoLive() throws Exception {
        ClienteApi anonimo = new ClienteApi(base);
        String evento = eventoStripe(true);
        String secretoWebhook = valorSecreto("STRIPE_WEBHOOK_SECRET");
        assertFalse(secretoWebhook.isBlank(), "El webhook desechable requiere un secreto local.");
        String firmaValida = firmar(evento, secretoWebhook);

        HttpResponse<String> sinFirma = anonimo.postRaw(WEBHOOK, evento, Map.of());
        assertEquals(400, sinFirma.statusCode());

        HttpResponse<String> firmaInvalida = anonimo.postRaw(WEBHOOK, evento,
                Map.of("Stripe-Signature", "t=" + Instant.now().getEpochSecond() + ",v1=deadbeef"));
        assertEquals(400, firmaInvalida.statusCode());

        HttpResponse<String> eventoLive = anonimo.postRaw(WEBHOOK, evento,
                Map.of("Stripe-Signature", firmaValida));
        assertEquals(400, eventoLive.statusCode());
        assertNoContieneSecretoConfigurado(eventoLive.body(), "STRIPE_WEBHOOK_SECRET");
    }

    @Test
    void unClienteNoPuedeConsultarElIntentoDeOtro() throws Exception {
        ClienteApi primera = crearCliente();
        ClienteApi segunda = crearCliente();
        HttpResponse<String> respuestaCheckout = primera.post(CHECKOUT, null, Map.of(
                CSRF, primera.tokenCsrf,
                "Idempotency-Key", UUID.randomUUID().toString()));
        assertEquals(201, respuestaCheckout.statusCode());
        String intentoId = JSON.readTree(respuestaCheckout.body()).path("intentoId").asText();

        HttpResponse<String> ajena = segunda.get(CHECKOUT + "/" + intentoId);
        assertEquals(404, ajena.statusCode());
        assertEquals("CHECKOUT_NO_ENCONTRADO", JSON.readTree(ajena.body()).path("codigo").asText());
    }

    private static ClienteApi crearCliente() throws Exception {
        ClienteApi api = new ClienteApi(base);
        String correo = "cliente-" + UUID.randomUUID() + "@example.test";
        String contrasena = "Prueba-" + UUID.randomUUID() + "-26!";
        String csrf = api.obtenerCsrf();
        Map<String, Object> registro = Map.of(
                "nombres", "Cliente Sandbox",
                "primerApellido", "Prueba",
                "correo", correo,
                "contrasena", contrasena);
        HttpResponse<String> respuestaRegistro = api.post(REGISTRO, registro, Map.of(CSRF, csrf));
        assertEquals(201, respuestaRegistro.statusCode());
        assertFalse(respuestaRegistro.body().contains(contrasena));

        String csrfAcceso = api.obtenerCsrf();
        HttpResponse<String> respuestaSesion = api.post(SESION,
                Map.of("correo", correo, "contrasena", contrasena), Map.of(CSRF, csrfAcceso));
        assertEquals(200, respuestaSesion.statusCode());
        api.tokenCsrf = JSON.readTree(respuestaSesion.body()).path("csrfToken").asText();
        assertFalse(api.tokenCsrf.isBlank());
        return api;
    }

    private static String eventoStripe(boolean modoLive) throws Exception {
        Map<String, Object> suscripcion = Map.of(
                "id", "sub_test_unowned_" + UUID.randomUUID(),
                "object", "subscription",
                "customer", "cus_test_unowned",
                "status", "active");
        Map<String, Object> datos = Map.of("object", suscripcion);
        Map<String, Object> evento = Map.of(
                "id", "evt_test_guard_" + UUID.randomUUID(),
                "object", "event",
                "created", Instant.now().getEpochSecond(),
                "type", "customer.subscription.updated",
                "livemode", modoLive,
                "data", datos);
        return JSON.writeValueAsString(evento);
    }

    private static String firmar(String cuerpo, String secreto) throws GeneralSecurityException {
        long instante = Instant.now().getEpochSecond();
        Mac hmac = Mac.getInstance("HmacSHA256");
        hmac.init(new SecretKeySpec(secreto.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        String mensaje = instante + "." + cuerpo;
        String digest = HexFormat.of().formatHex(hmac.doFinal(mensaje.getBytes(StandardCharsets.UTF_8)));
        return "t=" + instante + ",v1=" + digest;
    }

    private static String valorSecreto(String nombre) {
        return System.getenv().getOrDefault(nombre, "");
    }

    private static void assertNoContieneSecretoConfigurado(String cuerpo, String nombre) {
        String secreto = valorSecreto(nombre);
        if (!secreto.isBlank()) {
            assertFalse(cuerpo.contains(secreto), "La respuesta no debe exponer " + nombre + ".");
        }
    }

    private static final class ClienteApi {

        private final CookieManager cookies = new CookieManager(null, CookiePolicy.ACCEPT_ALL);
        private final HttpClient http = HttpClient.newBuilder()
                .cookieHandler(cookies)
                .connectTimeout(Duration.ofSeconds(5))
                .followRedirects(HttpClient.Redirect.NEVER)
                .build();
        private final URI urlBase;
        private String tokenCsrf;

        private ClienteApi(URI urlBase) {
            this.urlBase = urlBase;
        }

        private String obtenerCsrf() throws Exception {
            HttpResponse<String> respuesta = get("/api/v1/clientes/csrf");
            assertEquals(200, respuesta.statusCode());
            String token = JSON.readTree(respuesta.body()).path("token").asText();
            assertFalse(token.isBlank());
            return token;
        }

        private HttpResponse<String> get(String ruta) throws Exception {
            HttpRequest solicitud = HttpRequest.newBuilder(urlBase.resolve(ruta))
                    .timeout(Duration.ofSeconds(20))
                    .header("Accept", "application/json")
                    .GET()
                    .build();
            return http.send(solicitud, HttpResponse.BodyHandlers.ofString());
        }

        private HttpResponse<String> post(
                String ruta,
                Object cuerpo,
                Map<String, String> encabezados) throws Exception {
            return enviar("POST", ruta, cuerpo, encabezados);
        }

        private HttpResponse<String> postRaw(
                String ruta,
                String cuerpo,
                Map<String, String> encabezados) throws Exception {
            HttpRequest.Builder solicitud = HttpRequest.newBuilder(urlBase.resolve(ruta))
                    .timeout(Duration.ofSeconds(20))
                    .header("Content-Type", "application/json")
                    .header("Accept", "application/json");
            encabezados.forEach(solicitud::header);
            return http.send(solicitud.POST(HttpRequest.BodyPublishers.ofString(cuerpo)).build(),
                    HttpResponse.BodyHandlers.ofString());
        }

        private HttpResponse<String> enviar(
                String metodo,
                String ruta,
                Object cuerpo,
                Map<String, String> encabezados) throws Exception {
            HttpRequest.Builder solicitud = HttpRequest.newBuilder(urlBase.resolve(ruta))
                    .timeout(Duration.ofSeconds(30))
                    .header("Accept", "application/json");
            encabezados.forEach(solicitud::header);
            HttpRequest.BodyPublisher publicador = cuerpo == null
                    ? HttpRequest.BodyPublishers.noBody()
                    : HttpRequest.BodyPublishers.ofString(JSON.writeValueAsString(cuerpo));
            if (cuerpo != null) solicitud.header("Content-Type", "application/json");
            return http.send(solicitud.method(metodo, publicador).build(), HttpResponse.BodyHandlers.ofString());
        }
    }
}
