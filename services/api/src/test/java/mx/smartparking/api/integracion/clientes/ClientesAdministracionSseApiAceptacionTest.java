package mx.smartparking.api.integracion.clientes;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

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
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Aceptación HTTP del directorio, registro post-commit y dos streams de dueño. */
class ClientesAdministracionSseApiAceptacionTest {

    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final String CSRF = "X-CSRF-TOKEN";
    private static final String LISTA = "/api/v1/clientes/administracion";
    private static final String EVENTOS = "/api/v1/eventos/administracion";
    private static URI api;

    @BeforeAll
    static void configurar() {
        assumeTrue(Boolean.getBoolean("smartparking.integration.disposable"),
                "La aceptación requiere el runner conectado a la red desechable.");
        api = URI.create(System.getProperty("smartparking.api-url", ""));
        assertEquals("http", api.getScheme());
        assertEquals("api", api.getHost(), "La prueba debe usar el alias privado del API.");
        assertTrue(api.getPort() > 0);
    }

    @Test
    void dosDuenosRecibenRegistroConfirmadoYElDirectorioAseguraAccesoYProyeccion() throws Exception {
        Api duenoA = iniciarSesion("TEST_OWNER_EMAIL", "TEST_OWNER_PASSWORD", "/api/v1/csrf", "/api/v1/sesion");
        Api duenoB = iniciarSesion("TEST_OWNER_EMAIL", "TEST_OWNER_PASSWORD", "/api/v1/csrf", "/api/v1/sesion");
        HttpResponse<String> anonima = new Api(api).get(LISTA + "?pagina=1&estado=todos");
        assertEquals(401, anonima.statusCode());

        JsonNode primera = JSON.readTree(duenoA.get(LISTA + "?pagina=1&estado=todos").body());
        assertEquals(12, primera.path("totalClientes").asInt());
        assertEquals(10, primera.path("items").size());
        assertEquals("CLI-0001", primera.path("items").get(0).path("codigo").asText());
        String cursor = primera.path("cursorEventos").asText();
        assertFalse(cursor.isBlank());

        JsonNode paginaDos = JSON.readTree(duenoA.get(LISTA + "?pagina=2&estado=todos").body());
        assertEquals(2, paginaDos.path("pagina").asInt());
        assertEquals(2, paginaDos.path("items").size());
        assertEquals("CLI-0012", paginaDos.path("items").get(1).path("codigo").asText());

        JsonNode activas = JSON.readTree(duenoA.get(LISTA + "?pagina=1&estado=activa").body());
        assertEquals("CLI-0002", codigo(activas, "ACTIVA"));
        JsonNode canceladas = JSON.readTree(duenoA.get(LISTA + "?pagina=1&estado=cancelada").body());
        assertEquals("CLI-0003", codigo(canceladas, "CANCELADA"));
        JsonNode sinMembresia = JSON.readTree(duenoA.get(LISTA + "?pagina=1&estado=sin-membresia").body());
        assertTrue(contieneCodigo(sinMembresia, "CLI-0001"));

        JsonNode sinDetalle = JSON.readTree(duenoA.get(LISTA + "/CLI-0001").body());
        assertTrue(sinDetalle.path("membresia").isNull());
        JsonNode detalle = JSON.readTree(duenoA.get(LISTA + "/CLI-0002").body());
        assertEquals("ACTIVA", detalle.path("estadoMembresia").asText());
        assertEquals(39_900, detalle.path("membresia").path("plan").path("importeMenorUnidad").asInt());
        assertFalse(detalle.toString().contains("cus_Fase3"));

        Api cliente = iniciarSesion("TEST_CLIENT_EMAIL", "TEST_CLIENT_PASSWORD",
                "/api/v1/clientes/csrf", "/api/v1/clientes/sesion");
        assertEquals(403, cliente.get(LISTA).statusCode());

        HttpResponse<InputStream> streamA = duenoA.abrirStream(cursor);
        HttpResponse<InputStream> streamB = duenoB.abrirStream(cursor);
        assertTrue(streamA.headers().firstValue("content-type").orElse("").startsWith("text/event-stream"));
        assertTrue(streamB.headers().firstValue("content-type").orElse("").startsWith("text/event-stream"));
        ExecutorService lector = Executors.newVirtualThreadPerTaskExecutor();
        try (InputStream cuerpoA = streamA.body(); InputStream cuerpoB = streamB.body(); lector) {
            String correo = "sse-" + java.util.UUID.randomUUID() + "@example.test";
            Api registro = new Api(api);
            String token = registro.csrf("/api/v1/clientes/csrf");
            HttpResponse<String> creada = registro.post("/api/v1/clientes/registro", Map.of(
                    "nombres", "Cliente SSE",
                    "primerApellido", "Sintetico",
                    "correo", correo,
                    "contrasena", "Prueba-SSE-2026!"), Map.of(CSRF, token));
            assertEquals(201, creada.statusCode());
            assertFalse(creada.body().contains("Prueba-SSE-2026!"));

            CompletableFuture<EventoSse> recibidoA = CompletableFuture.supplyAsync(
                    () -> leerEvento(cuerpoA), lector);
            CompletableFuture<EventoSse> recibidoB = CompletableFuture.supplyAsync(
                    () -> leerEvento(cuerpoB), lector);
            EventoSse eventoA = recibidoA.get(12, TimeUnit.SECONDS);
            EventoSse eventoB = recibidoB.get(12, TimeUnit.SECONDS);
            assertEquals("cliente.registrado", eventoA.nombre());
            assertEquals("cliente.registrado", eventoB.nombre());
            assertEquals("{}", eventoA.datos());
            assertEquals("{}", eventoB.datos());
            assertEquals(eventoA.cursor(), eventoB.cursor());
            assertNotEquals(cursor, eventoA.cursor());

            JsonNode despues = JSON.readTree(duenoB.get(LISTA).body());
            assertEquals(13, despues.path("totalClientes").asInt());
        }
    }

    private static String codigo(JsonNode pagina, String estado) {
        for (JsonNode item : pagina.path("items")) {
            if (estado.equals(item.path("estadoMembresia").asText())) return item.path("codigo").asText();
        }
        throw new AssertionError("No apareció un cliente con estado " + estado + ".");
    }

    private static boolean contieneCodigo(JsonNode pagina, String codigo) {
        for (JsonNode item : pagina.path("items")) {
            if (codigo.equals(item.path("codigo").asText())) return true;
        }
        return false;
    }

    private static Api iniciarSesion(String correoVariable, String claveVariable, String rutaCsrf, String rutaSesion)
            throws Exception {
        String correo = variable(correoVariable);
        String contrasena = variable(claveVariable);
        Api cliente = new Api(api);
        String csrf = cliente.csrf(rutaCsrf);
        HttpResponse<String> respuesta = cliente.post(rutaSesion,
                Map.of("correo", correo, "contrasena", contrasena), Map.of(CSRF, csrf));
        assertEquals(200, respuesta.statusCode());
        return cliente;
    }

    private static String variable(String nombre) {
        String valor = System.getenv(nombre);
        assertTrue(valor != null && !valor.isBlank(), "Falta la variable sintetica " + nombre + ".");
        return valor;
    }

    private static EventoSse leerEvento(InputStream cuerpo) {
        try (BufferedReader lector = new BufferedReader(new InputStreamReader(cuerpo, StandardCharsets.UTF_8))) {
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
                    if (!datos.isEmpty()) datos.append('\n');
                    datos.append(linea.substring(5).strip());
                }
            }
            throw new AssertionError("El stream terminó antes de publicar el registro.");
        } catch (Exception excepcion) {
            throw new AssertionError("No se pudo leer la invalidación SSE.", excepcion);
        }
    }

    private record EventoSse(String nombre, String cursor, String datos) {
    }

    private static final class Api {

        private final CookieManager cookies = new CookieManager(null, CookiePolicy.ACCEPT_ALL);
        private final HttpClient http = HttpClient.newBuilder()
                .cookieHandler(cookies)
                .connectTimeout(Duration.ofSeconds(5))
                .followRedirects(HttpClient.Redirect.NEVER)
                .build();
        private final URI base;

        private Api(URI base) {
            this.base = base;
        }

        private String csrf(String ruta) throws Exception {
            HttpResponse<String> respuesta = get(ruta);
            assertEquals(200, respuesta.statusCode());
            String token = JSON.readTree(respuesta.body()).path("token").asText();
            assertFalse(token.isBlank());
            return token;
        }

        private HttpResponse<String> get(String ruta) throws Exception {
            HttpRequest solicitud = HttpRequest.newBuilder(base.resolve(ruta))
                    .timeout(Duration.ofSeconds(15))
                    .header("Accept", "application/json")
                    .GET()
                    .build();
            return http.send(solicitud, HttpResponse.BodyHandlers.ofString());
        }

        private HttpResponse<String> post(String ruta, Object cuerpo, Map<String, String> encabezados)
                throws Exception {
            HttpRequest.Builder solicitud = HttpRequest.newBuilder(base.resolve(ruta))
                    .timeout(Duration.ofSeconds(20))
                    .header("Accept", "application/json")
                    .header("Content-Type", "application/json");
            encabezados.forEach(solicitud::header);
            return http.send(solicitud.POST(HttpRequest.BodyPublishers.ofString(JSON.writeValueAsString(cuerpo))).build(),
                    HttpResponse.BodyHandlers.ofString());
        }

        private HttpResponse<InputStream> abrirStream(String cursor) throws Exception {
            HttpRequest solicitud = HttpRequest.newBuilder(base.resolve(EVENTOS + "?despues=" + cursor))
                    .timeout(Duration.ofSeconds(20))
                    .header("Accept", "text/event-stream")
                    .GET()
                    .build();
            return http.send(solicitud, HttpResponse.BodyHandlers.ofInputStream());
        }
    }
}
