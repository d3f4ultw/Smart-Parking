package mx.smartparking.api.integracion.clientes.membresia;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.HexFormat;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import mx.smartparking.api.clientes.membresia.servicio.ProveedorStripeMembresia;
import mx.smartparking.api.clientes.membresia.servicio.StripeMembresiaException;

/** Valida firma, commit de membresía y emisión SSE con PostgreSQL descartable y proveedor falso. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@Import(ClientesMembresiaSseIntegracionTest.ProveedorLocalConfiguracion.class)
@EnabledIfSystemProperty(named = "smartparking.integration.disposable", matches = "true")
class ClientesMembresiaSseIntegracionTest {

    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final String PRECIO = "price_1USQ5HAqtHmR2qmyAWwUp5vy";
    private static final String CSRF = "X-CSRF-TOKEN";

    @LocalServerPort
    private int puerto;

    @Autowired
    private JdbcTemplate jdbc;

    @Autowired
    private ProveedorStripeLocal stripe;

    @Test
    void webhookFirmadoEmiteSoloTrasCambioVisibleConfirmadoEnDosSesiones() throws Exception {
        String nombreDb = System.getenv("POSTGRES_DB");
        assertTrue(nombreDb != null && nombreDb.startsWith("smartparking_test_"),
                "La prueba solo puede usar una base smartparking_test_*.");
        assertTrue(jdbc.queryForObject("SELECT version()", String.class).contains("PostgreSQL 18.6"));
        assertEquals(1, jdbc.queryForObject(
                "SELECT count(*) FROM flyway_schema_history WHERE version = '10' AND success", Integer.class));

        URI base = URI.create("http://127.0.0.1:" + puerto + "/");
        Api inicial = new Api(base);
        String correoDueno = variable("TEST_OWNER_EMAIL");
        String contrasenaDueno = variable("TEST_OWNER_PASSWORD");
        String contrasenaAdministrativa = variable("TEST_OWNER_ADMIN_PASSWORD");
        String token = inicial.csrf("/api/v1/csrf");
        HttpResponse<String> configurada = inicial.post("/api/v1/configuracion/inicial", Map.of(
                "propietario", Map.of(
                        "nombres", "Propietario SSE",
                        "primerApellido", "Sintetico",
                        "correo", correoDueno,
                        "contrasenaAcceso", contrasenaDueno,
                        "contrasenaAdministrativa", contrasenaAdministrativa),
                "estacionamiento", Map.of(
                        "nombre", "Estacionamiento de prueba",
                        "tipo", "PRIVADO",
                        "horario", Map.of("modo", "CONTINUO_24_7", "zonaHoraria", "America/Mexico_City"))),
                Map.of(CSRF, token, "Idempotency-Key", UUID.randomUUID().toString()));
        assertEquals(201, configurada.statusCode());

        Api duenoA = iniciarSesion(base, correoDueno, contrasenaDueno);
        Api duenoB = iniciarSesion(base, correoDueno, contrasenaDueno);
        String cursorInicial = JSON.readTree(duenoA.get("/api/v1/clientes/administracion").body())
                .path("cursorEventos").asText();
        try (Stream streamA = duenoA.abrirStream(cursorInicial);
             Stream streamB = duenoB.abrirStream(cursorInicial)) {
            Api cliente = new Api(base);
            String csrfCliente = cliente.csrf("/api/v1/clientes/csrf");
            HttpResponse<String> registro = cliente.post("/api/v1/clientes/registro", Map.of(
                    "nombres", "Cliente de membresia",
                    "primerApellido", "Sintetico",
                    "correo", "membresia-" + UUID.randomUUID() + "@example.test",
                    "contrasena", "Prueba-Membresia-2026!"), Map.of(CSRF, csrfCliente));
            assertEquals(201, registro.statusCode());
            UUID clienteId = UUID.fromString(JSON.readTree(registro.body()).path("clienteId").asText());
            EventoSse altaA = streamA.siguiente();
            EventoSse altaB = streamB.siguiente();
            assertEquals("cliente.registrado", altaA.nombre());
            assertEquals("cliente.registrado", altaB.nombre());
            assertEquals("{}", altaA.datos());
            assertEquals(altaA.cursor(), altaB.cursor());

            UUID intentoId = UUID.randomUUID();
            sembrarCustomerEIntento(clienteId, intentoId);
            configurarFake(clienteId, intentoId);
            String cuerpo = evento("evt_" + tokenSeguro(), "customer.subscription.updated", 0);
            HttpResponse<String> aplicado = publicarWebhook(base, cuerpo);
            assertEquals(204, aplicado.statusCode());
            EventoSse membresiaA = streamA.siguiente();
            EventoSse membresiaB = streamB.siguiente();
            assertEquals("membresia.actualizada", membresiaA.nombre());
            assertEquals("membresia.actualizada", membresiaB.nombre());
            assertEquals("{}", membresiaA.datos());
            assertEquals(membresiaA.cursor(), membresiaB.cursor());

            String cursorConfirmado = cursor(duenoA);
            assertEquals("ACTIVA", JSON.readTree(duenoA.get("/api/v1/clientes/administracion/CLI-0001").body())
                    .path("estadoMembresia").asText());
            assertEquals(204, publicarWebhook(base, cuerpo).statusCode());
            assertEquals(cursorConfirmado, cursor(duenoA), "Un evento duplicado no publica otra invalidacion.");

            String sinCambio = evento("evt_" + tokenSeguro(), "customer.subscription.updated", 1);
            assertEquals(204, publicarWebhook(base, sinCambio).statusCode());
            assertEquals(cursorConfirmado, cursor(duenoA), "Una proyeccion visible sin cambios no publica.");

            stripe.fallarProximaConsulta();
            String fallido = evento("evt_" + tokenSeguro(), "customer.subscription.updated", 2);
            assertEquals(503, publicarWebhook(base, fallido).statusCode());
            assertEquals(cursorConfirmado, cursor(duenoA), "Una conciliacion fallida no publica.");
        }
    }

    private void sembrarCustomerEIntento(UUID clienteId, UUID intentoId) {
        Instant ahora = Instant.now();
        java.sql.Timestamp marcaTiempo = java.sql.Timestamp.from(ahora);
        jdbc.update("""
                INSERT INTO cliente_stripe (cliente_id, estado, stripe_customer_id, livemode, creada_en, actualizada_en)
                VALUES (?, 'ASOCIADO', 'cus_Fase3Sse', FALSE, ?, ?)
                """, clienteId, marcaTiempo, marcaTiempo);
        jdbc.update("""
                INSERT INTO intento_checkout (
                    intento_id, cliente_id, clave_hash, huella_solicitud, estado, session_id,
                    price_id, expira_en, livemode, creado_en, actualizado_en)
                VALUES (?, ?, ?, ?, 'ABIERTO', 'cs_test_Fase3Sse', ?, ?, FALSE, ?, ?)
                """, intentoId, clienteId, "a".repeat(64), "b".repeat(64), PRECIO,
                java.sql.Timestamp.from(ahora.plusSeconds(3600)), marcaTiempo, marcaTiempo);
    }

    private void configurarFake(UUID clienteId, UUID intentoId) {
        String customerId = "cus_Fase3Sse";
        String subscriptionId = "sub_Fase3Sse";
        Map<String, String> metadata = Map.of(
                "smartparking_cliente_id", clienteId.toString(),
                "smartparking_checkout_intento", intentoId.toString(),
                "smartparking_price_id", PRECIO);
        stripe.suscripcion.set(new ProveedorStripeMembresia.SuscripcionRemota(
                subscriptionId, customerId, "active", "in_Fase3Sse",
                Instant.parse("2026-10-27T00:00:00Z"), Instant.parse("2026-11-27T00:00:00Z"),
                true, PRECIO, false, metadata));
        stripe.factura.set(new ProveedorStripeMembresia.FacturaRemota(
                "in_Fase3Sse", customerId, subscriptionId, "paid", false));
    }

    private static String evento(String id, String tipo, int incremento) throws Exception {
        Map<String, Object> objeto = Map.of("id", "sub_Fase3Sse", "object", "subscription");
        Map<String, Object> datos = Map.of("object", objeto);
        Map<String, Object> raiz = Map.of(
                "id", id,
                "object", "event",
                "created", Instant.now().plusSeconds(incremento).getEpochSecond(),
                "type", tipo,
                "livemode", false,
                "data", datos);
        return JSON.writeValueAsString(raiz);
    }

    private static HttpResponse<String> publicarWebhook(URI base, String cuerpo) throws Exception {
        String firma = firmar(cuerpo, variable("STRIPE_WEBHOOK_SECRET"));
        HttpRequest solicitud = HttpRequest.newBuilder(base.resolve("/api/v1/webhooks/stripe"))
                .timeout(Duration.ofSeconds(20))
                .header("Content-Type", "application/json")
                .header("Stripe-Signature", firma)
                .POST(HttpRequest.BodyPublishers.ofString(cuerpo))
                .build();
        return HttpClient.newHttpClient().send(solicitud, HttpResponse.BodyHandlers.ofString());
    }

    private static String firmar(String cuerpo, String secreto) throws Exception {
        long marcaTiempo = Instant.now().getEpochSecond();
        return "t=" + marcaTiempo + ",v1=" + digest(marcaTiempo, cuerpo, secreto);
    }

    private static String digest(long marcaTiempo, String cuerpo, String secreto) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(secreto.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        byte[] resultado = mac.doFinal((marcaTiempo + "." + cuerpo).getBytes(StandardCharsets.UTF_8));
        return HexFormat.of().formatHex(resultado);
    }

    private static String cursor(Api dueno) throws Exception {
        return JSON.readTree(dueno.get("/api/v1/clientes/administracion").body())
                .path("cursorEventos").asText();
    }

    private static Api iniciarSesion(URI base, String correo, String contrasena) throws Exception {
        Api api = new Api(base);
        String csrf = api.csrf("/api/v1/csrf");
        HttpResponse<String> respuesta = api.post("/api/v1/sesion",
                Map.of("correo", correo, "contrasena", contrasena), Map.of(CSRF, csrf));
        assertEquals(200, respuesta.statusCode());
        return api;
    }

    private static String variable(String nombre) {
        String valor = System.getenv(nombre);
        assertTrue(valor != null && !valor.isBlank(), "Falta la variable sintetica " + nombre + ".");
        return valor;
    }

    private static String tokenSeguro() {
        return UUID.randomUUID().toString().replace("-", "");
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class ProveedorLocalConfiguracion {
        @Bean
        @Primary
        ProveedorStripeLocal proveedorStripeLocal() {
            return new ProveedorStripeLocal();
        }
    }

    static class ProveedorStripeLocal implements ProveedorStripeMembresia {
        private final AtomicReference<SuscripcionRemota> suscripcion = new AtomicReference<>();
        private final AtomicReference<FacturaRemota> factura = new AtomicReference<>();
        private final AtomicBoolean fallar = new AtomicBoolean();

        void fallarProximaConsulta() {
            fallar.set(true);
        }

        @Override
        public void validarFirmaWebhook(byte[] cuerpo, String firma, String secreto) {
            try {
                String contenido = new String(cuerpo, StandardCharsets.UTF_8);
                String[] partes = firma.split(",");
                long marcaTiempo = Long.parseLong(partes[0].substring(2));
                String esperada = "t=" + marcaTiempo + ",v1=" + digest(marcaTiempo, contenido, secreto);
                if (!MessageDigest.isEqual(esperada.getBytes(StandardCharsets.UTF_8), firma.getBytes(StandardCharsets.UTF_8))) {
                    throw new StripeMembresiaException("Firma sintetica no valida.");
                }
            } catch (StripeMembresiaException excepcion) {
                throw excepcion;
            } catch (Exception excepcion) {
                throw new StripeMembresiaException("No se pudo comprobar la firma sintetica.", excepcion);
            }
        }

        @Override
        public SuscripcionRemota obtenerSuscripcion(String id) {
            if (fallar.getAndSet(false)) throw new StripeMembresiaException("Fallo sintetico del proveedor.");
            SuscripcionRemota valor = suscripcion.get();
            return valor != null && valor.id().equals(id) ? valor : null;
        }

        @Override
        public FacturaRemota obtenerFactura(String id) {
            FacturaRemota valor = factura.get();
            return valor != null && valor.id().equals(id) ? valor : null;
        }

        private AssertionError redExternaProhibida() {
            return new AssertionError("La prueba no permite operaciones de red hacia Stripe.");
        }

        @Override public ClienteRemoto crearCliente(UUID id, String key) { throw redExternaProhibida(); }
        @Override public java.util.List<ClienteRemoto> buscarClientes(UUID id) { throw redExternaProhibida(); }
        @Override public CheckoutRemoto crearCheckout(UUID a, UUID b, String c, String d, String e, String f,
                String g, String h) { throw redExternaProhibida(); }
        @Override public CheckoutRemoto obtenerCheckout(String id) { throw redExternaProhibida(); }
        @Override public java.util.List<CheckoutRemoto> buscarCheckouts(String id) { throw redExternaProhibida(); }
        @Override public boolean tieneSuscripcionNoTerminal(String id) { throw redExternaProhibida(); }
    }

    private record EventoSse(String nombre, String cursor, String datos) { }

    private static final class Stream implements AutoCloseable {
        private final BufferedReader lector;

        private Stream(InputStream cuerpo) {
            lector = new BufferedReader(new InputStreamReader(cuerpo, StandardCharsets.UTF_8));
        }

        private EventoSse siguiente() throws Exception {
            String nombre = "";
            String cursor = "";
            StringBuilder datos = new StringBuilder();
            String linea;
            while ((linea = lector.readLine()) != null) {
                if (linea.isEmpty()) {
                    if (!nombre.isEmpty() && !"empleado.heartbeat".equals(nombre) && !datos.isEmpty()) {
                        return new EventoSse(nombre, cursor, datos.toString());
                    }
                    nombre = "";
                    cursor = "";
                    datos.setLength(0);
                } else if (linea.startsWith("event:")) {
                    nombre = linea.substring(6).strip();
                } else if (linea.startsWith("id:")) {
                    cursor = linea.substring(3).strip();
                } else if (linea.startsWith("data:")) {
                    datos.append(linea.substring(5).strip());
                }
            }
            throw new AssertionError("El stream terminó antes del evento esperado.");
        }

        @Override
        public void close() throws Exception {
            lector.close();
        }
    }

    private static final class Api {
        private final CookieManager cookies = new CookieManager(null, CookiePolicy.ACCEPT_ALL);
        private final HttpClient http = HttpClient.newBuilder().cookieHandler(cookies)
                .connectTimeout(Duration.ofSeconds(5)).build();
        private final URI base;

        private Api(URI base) { this.base = base; }

        private String csrf(String ruta) throws Exception {
            String token = JSON.readTree(get(ruta).body()).path("token").asText();
            assertFalse(token.isBlank());
            return token;
        }

        private HttpResponse<String> get(String ruta) throws Exception {
            return http.send(HttpRequest.newBuilder(base.resolve(ruta)).timeout(Duration.ofSeconds(20))
                    .header("Accept", "application/json").GET().build(), HttpResponse.BodyHandlers.ofString());
        }

        private HttpResponse<String> post(String ruta, Object body, Map<String, String> headers) throws Exception {
            HttpRequest.Builder request = HttpRequest.newBuilder(base.resolve(ruta)).timeout(Duration.ofSeconds(30))
                    .header("Content-Type", "application/json").header("Accept", "application/json");
            headers.forEach(request::header);
            return http.send(request.POST(HttpRequest.BodyPublishers.ofString(JSON.writeValueAsString(body))).build(),
                    HttpResponse.BodyHandlers.ofString());
        }

        private Stream abrirStream(String cursor) throws Exception {
            HttpResponse<InputStream> respuesta = http.send(HttpRequest.newBuilder(
                    base.resolve("/api/v1/eventos/administracion?despues=" + cursor))
                    .timeout(Duration.ofSeconds(20)).header("Accept", "text/event-stream").GET().build(),
                    HttpResponse.BodyHandlers.ofInputStream());
            assertEquals(200, respuesta.statusCode());
            assertTrue(respuesta.headers().firstValue("content-type").orElse("").startsWith("text/event-stream"));
            return new Stream(respuesta.body());
        }
    }
}
