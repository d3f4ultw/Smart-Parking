package mx.smartparking.api.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.net.http.HttpRequest.BodyPublishers;
import java.net.http.HttpResponse.BodyHandlers;
import mx.smartparking.api.clientes.configuracion.CatalogoMembresia;
import mx.smartparking.api.clientes.membresia.modelo.ActualizacionStripe;
import mx.smartparking.api.persistencia.membresia.RepositorioMembresias;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.json.JsonMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;

abstract class HistorialAccesosAceptacionHttpSoporte {

    protected static final String TOKEN_DISPOSITIVO = UUID.randomUUID().toString();
    protected static final DateTimeFormatter FORMATO_LOCAL = DateTimeFormatter
            .ofPattern("uuuu-MM-dd'T'HH:mm:ssXXX", Locale.ROOT);
    protected static final JsonMapper JSON = JsonMapper.builder().build();

    protected final HttpClient http = HttpClient.newHttpClient();
    @Autowired protected JdbcTemplate jdbc;
    @Autowired protected PasswordEncoder contrasenas;
    @Autowired protected RepositorioMembresias membresias;
    @Autowired protected CatalogoMembresia catalogoMembresia;
    @LocalServerPort protected int puerto;

    protected Sesion iniciarDueno() {
        Sesion anonima = new Sesion(null, null);
        ResponseEntity<Map<String, Object>> csrfRespuesta = get("/api/v1/csrf", anonima);
        anonima = capturarCookie(csrfRespuesta, anonima);
        String correo = "dueno-" + UUID.randomUUID() + "@example.invalid";
        String contrasena = UUID.randomUUID() + "Aa9!";
        Map<String, Object> propietario = Map.of(
                "nombres", "Dueno Sintetico", "primerApellido", "Aceptacion", "correo", correo,
                "contrasenaAcceso", contrasena, "contrasenaAdministrativa", UUID.randomUUID() + "Bb7!");
        Map<String, Object> horario = Map.of("modo", "CONTINUO_24_7", "zonaHoraria", "America/New_York");
        Map<String, Object> configuracion = Map.of("propietario", propietario, "estacionamiento",
                Map.of("nombre", "Aceptacion Historial", "tipo", "MIXTO", "horario", horario));
        ResponseEntity<Map<String, Object>> inicial = post("/api/v1/configuracion/inicial", configuracion,
                anonima, (String) csrfRespuesta.getBody().get("token"), UUID.randomUUID().toString());
        assertEquals(201, inicial.getStatusCode().value());
        anonima = capturarCookie(inicial, anonima);
        csrfRespuesta = get("/api/v1/csrf", anonima);
        anonima = capturarCookie(csrfRespuesta, anonima);
        ResponseEntity<Map<String, Object>> login = post("/api/v1/sesion",
                Map.of("correo", correo, "contrasena", contrasena), anonima,
                (String) csrfRespuesta.getBody().get("token"), null);
        assertEquals(200, login.getStatusCode().value());
        return new Sesion(capturarCookie(login, anonima).cookie(), (String) login.getBody().get("csrfToken"));
    }

    protected Sesion registrarEIniciarCliente() {
        Sesion sesion = new Sesion(null, null);
        ResponseEntity<Map<String, Object>> csrf = get("/api/v1/clientes/csrf", sesion);
        sesion = capturarCookie(csrf, sesion);
        String correo = "cliente-" + UUID.randomUUID() + "@example.invalid";
        String contrasena = UUID.randomUUID() + "Cc5!";
        ResponseEntity<Map<String, Object>> registro = post("/api/v1/clientes/registro", Map.of(
                "nombres", "Clara", "primerApellido", "Cliente", "correo", correo,
                "contrasena", contrasena), sesion, (String) csrf.getBody().get("token"), null);
        assertEquals(201, registro.getStatusCode().value());
        csrf = get("/api/v1/clientes/csrf", sesion);
        sesion = capturarCookie(csrf, sesion);
        ResponseEntity<Map<String, Object>> login = post("/api/v1/clientes/sesion",
                Map.of("correo", correo, "contrasena", contrasena), sesion,
                (String) csrf.getBody().get("token"), null);
        assertEquals(200, login.getStatusCode().value());
        return new Sesion(capturarCookie(login, sesion).cookie(), (String) login.getBody().get("csrfToken"));
    }

    protected ResponseEntity<Map<String, Object>> intentarLoginOperador() {
        Sesion sesion = new Sesion(null, null);
        ResponseEntity<Map<String, Object>> csrf = get("/api/v1/csrf", sesion);
        sesion = capturarCookie(csrf, sesion);
        String correo = "operador-" + UUID.randomUUID() + "@example.invalid";
        String contrasena = UUID.randomUUID() + "Dd1!";
        String hash = contrasenas.encode(contrasena);
        jdbc.update("""
                INSERT INTO cuenta (id,nombres,primer_apellido,correo,correo_normalizado,rol,estado,
                    hash_contrasena_acceso,revision_acceso,creada_en,actualizada_en)
                VALUES (?,?,?,?,?,'OPERADOR','ACTIVA',?,1,now(),now())
                """, UUID.randomUUID(), "Operador", "Prueba", correo, correo, hash);
        return post("/api/v1/sesion", Map.of("correo", correo, "contrasena", contrasena),
                sesion, (String) csrf.getBody().get("token"), null);
    }

    protected void assertDecision(String lector, String tarjeta, String lectura, String resultado, String motivo) {
        ResponseEntity<Map<String, Object>> respuesta = enviarDecision(lector, tarjeta, lectura);
        assertEquals(200, respuesta.getStatusCode().value());
        assertEquals(resultado, respuesta.getBody().get("resultado"));
        assertEquals(motivo, respuesta.getBody().get("motivo"));
    }

    protected ResponseEntity<Map<String, Object>> enviarDecision(String lector, String tarjeta, String lectura) {
        String ruta = "RFID2".equals(lector)
                ? "/api/v1/dispositivos/rfid-2/entradas" : "/api/v1/dispositivos/rfid-3/salidas";
        HttpHeaders cabeceras = new HttpHeaders();
        cabeceras.setContentType(MediaType.APPLICATION_JSON);
        cabeceras.setBearerAuth(TOKEN_DISPOSITIVO);
        return intercambiar(ruta, HttpMethod.POST, Map.of("uid", tarjeta, "lecturaId", lectura), cabeceras);
    }

    protected ResponseEntity<Map<String, Object>> get(String ruta, Sesion sesion) {
        return intercambiar(ruta, HttpMethod.GET, null, cabeceras(sesion, null, null));
    }

    protected ResponseEntity<Map<String, Object>> getConBearer(String ruta) {
        HttpHeaders cabeceras = new HttpHeaders();
        cabeceras.setBearerAuth(TOKEN_DISPOSITIVO);
        return intercambiar(ruta, HttpMethod.GET, null, cabeceras);
    }

    protected ResponseEntity<Map<String, Object>> post(
            String ruta, Object cuerpo, Sesion sesion, String csrf, String claveIdempotencia) {
        HttpHeaders cabeceras = cabeceras(sesion, csrf, claveIdempotencia);
        cabeceras.setContentType(MediaType.APPLICATION_JSON);
        return intercambiar(ruta, HttpMethod.POST, cuerpo, cabeceras);
    }

    protected ResponseEntity<Map<String, Object>> intercambiar(
            String ruta, HttpMethod metodo, Object cuerpo, HttpHeaders cabeceras) {
        try {
            HttpRequest.Builder solicitud = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + puerto + ruta));
            if (cuerpo != null) cabeceras.setContentType(MediaType.APPLICATION_JSON);
            cabeceras.forEach((nombre, valores) -> valores.forEach(valor -> solicitud.header(nombre, valor)));
            if (cuerpo == null) {
                solicitud.method(metodo.name(), BodyPublishers.noBody());
            } else {
                solicitud.method(metodo.name(), BodyPublishers.ofString(JSON.writeValueAsString(cuerpo)));
            }
            HttpResponse<String> respuesta = http.send(solicitud.build(), BodyHandlers.ofString());
            HttpHeaders encabezados = new HttpHeaders();
            respuesta.headers().map().forEach(encabezados::put);
            Map<String, Object> cuerpoRespuesta = respuesta.body().isBlank() ? null
                    : JSON.readValue(respuesta.body(), new TypeReference<>() { });
            return ResponseEntity.status(respuesta.statusCode()).headers(encabezados).body(cuerpoRespuesta);
        } catch (InterruptedException excepcion) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Se interrumpió la solicitud HTTP de aceptación.", excepcion);
        } catch (java.io.IOException excepcion) {
            throw new IllegalStateException("No se pudo completar la solicitud HTTP de aceptación.", excepcion);
        } catch (tools.jackson.core.JacksonException excepcion) {
            throw new IllegalStateException("No se pudo completar la solicitud HTTP de aceptación.", excepcion);
        }
    }

    protected HttpHeaders cabeceras(Sesion sesion, String csrf, String claveIdempotencia) {
        HttpHeaders cabeceras = new HttpHeaders();
        cabeceras.setAccept(List.of(MediaType.APPLICATION_JSON));
        if (sesion != null && sesion.cookie() != null) cabeceras.set(HttpHeaders.COOKIE, sesion.cookie());
        if (csrf != null) cabeceras.set("X-CSRF-TOKEN", csrf);
        if (claveIdempotencia != null) cabeceras.set("Idempotency-Key", claveIdempotencia);
        return cabeceras;
    }

    protected Sesion capturarCookie(ResponseEntity<?> respuesta, Sesion anterior) {
        List<String> cookies = respuesta.getHeaders().get(HttpHeaders.SET_COOKIE);
        if (cookies == null) return anterior;
        for (String cookie : cookies) {
            if (cookie.startsWith("JSESSIONID=")) return new Sesion(cookie.split(";", 2)[0], anterior.csrf());
        }
        return anterior;
    }

    protected SseProbe abrirSse(Sesion sesion) throws Exception {
        Map<String, Object> snapshot = get("/api/v1/accesos/historial", sesion).getBody();
        String cursor = (String) snapshot.get("cursorEventos");
        return new SseProbe("http://127.0.0.1:" + puerto
                + "/api/v1/eventos/administracion?despues=" + cursor, sesion.cookie());
    }

    protected void insertarEventosPaginables(long asociacionId) {
        Instant fijo = Instant.parse("2050-01-02T04:59:59Z");
        for (int indice = 0; indice < 55; indice++) {
            String lector = indice % 2 == 0 ? "RFID2" : "RFID3";
            String motivo = "RFID2".equals(lector) ? "ENTRADA_PENDIENTE" : "SIN_ENTRADA_ABIERTA";
            jdbc.update("""
                    INSERT INTO evento_acceso (ocurrido_en,lector,resultado,motivo,lectura_id,asociacion_id)
                    VALUES (?,?,'DENEGADA',?,?,?)
                    """, java.time.OffsetDateTime.ofInstant(fijo, java.time.ZoneOffset.UTC),
                    lector, motivo, UUID.randomUUID(), asociacionId);
        }
        jdbc.update("""
                INSERT INTO evento_acceso (ocurrido_en,lector,resultado,motivo,lectura_id,asociacion_id)
                VALUES (?,'RFID2','DENEGADA','ENTRADA_PENDIENTE',?,?)
                """, java.time.OffsetDateTime.ofInstant(Instant.parse("2050-01-01T04:59:59Z"),
                java.time.ZoneOffset.UTC), UUID.randomUUID(), asociacionId);
        jdbc.update("""
                INSERT INTO evento_acceso (ocurrido_en,lector,resultado,motivo,lectura_id,asociacion_id)
                VALUES (?,'RFID2','DENEGADA','ENTRADA_PENDIENTE',?,?)
                """, java.time.OffsetDateTime.ofInstant(Instant.parse("2050-01-02T05:00:00Z"),
                java.time.ZoneOffset.UTC), UUID.randomUUID(), asociacionId);
        for (String instante : List.of(
                "2026-11-01T03:59:59Z", "2026-11-01T04:00:00Z",
                "2026-11-01T05:30:00Z", "2026-11-01T06:30:00Z", "2026-11-02T05:00:00Z")) {
            jdbc.update("""
                    INSERT INTO evento_acceso (ocurrido_en,lector,resultado,motivo,lectura_id,asociacion_id)
                    VALUES (?,'RFID2','DENEGADA','ENTRADA_PENDIENTE',?,?)
                    """, java.time.OffsetDateTime.ofInstant(Instant.parse(instante), java.time.ZoneOffset.UTC),
                    UUID.randomUUID(), asociacionId);
        }
    }

    protected String asociarYCancelar(String uid, long empleadoId) {
        long asociacion = asociar(uid, empleadoId);
        jdbc.update("UPDATE asociacion_tarjeta_rfid1 SET estado='CANCELADA',cancelada_en=now() WHERE asociacion_id=?",
                asociacion);
        return uid;
    }

    protected long asociar(String uid, long empleadoId) {
        return jdbc.queryForObject("""
                INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico,empleado_id)
                VALUES (?,?) RETURNING asociacion_id
                """, Long.class, uid, empleadoId);
    }

    protected long crearEmpleado(String nombres, String apellido) {
        return jdbc.queryForObject("INSERT INTO empleado (nombres,primer_apellido) VALUES (?,?) RETURNING id",
                Long.class, nombres, apellido);
    }

    protected long asociarCliente(String uid, UUID clienteId) {
        return jdbc.queryForObject("""
                INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico,cliente_id)
                VALUES (?,?) RETURNING asociacion_id
                """, Long.class, uid, clienteId);
    }

    protected void prepararMembresiaVigente(UUID clienteId) {
        Instant ahora = Instant.now();
        String sufijo = UUID.randomUUID().toString().replace("-", "");
        String clienteStripe = "cus_" + sufijo;
        String suscripcion = "sub_" + sufijo;
        String evento = "evt_" + sufijo;
        String tipo = "customer.subscription.updated";
        membresias.reservarClienteStripe(clienteId, ahora);
        membresias.asociarCustomer(clienteId, clienteStripe, ahora);
        membresias.registrarEventoStripe(evento, tipo, suscripcion, ahora);
        membresias.aplicarActualizacionStripe(new ActualizacionStripe(
                evento, tipo, ahora, null, null, clienteStripe, suscripcion, clienteId,
                catalogoMembresia.precioId(), "active", "in_" + sufijo, "paid",
                ahora.minusSeconds(60), ahora.plusSeconds(3600), false, ahora, true));
        assertEquals("ACTIVA", membresias.consultarResumenMembresia(clienteId).estado());
    }

    protected void prepararCapacidadDisponible(int cantidad) {
        UUID estacionamiento = jdbc.queryForObject(
                "SELECT estacionamiento_id FROM configuracion_estacionamiento WHERE id=1", UUID.class);
        UUID fuente = UUID.randomUUID();
        jdbc.update("INSERT INTO vision_fuente (fuente_id,estacionamiento_id) VALUES (?,?)",
                fuente, estacionamiento);
        for (int numero = 0; numero < cantidad; numero++) {
            UUID cajon = UUID.randomUUID();
            jdbc.update("INSERT INTO vision_cajon (cajon_id,estacionamiento_id,etiqueta) VALUES (?,?,?)",
                    cajon, estacionamiento, "H" + numero);
            jdbc.update("INSERT INTO vision_zona (fuente_id,vision_zone_id,cajon_id) VALUES (?,?,?)",
                    fuente, UUID.randomUUID(), cajon);
        }
        assertEquals(cantidad, jdbc.queryForObject("""
                SELECT count(*) FROM vision_cajon c
                JOIN vision_zona z ON z.cajon_id=c.cajon_id AND z.activa
                WHERE c.estacionamiento_id=?
                """, Integer.class, estacionamiento));
    }

    protected UUID clienteId() {
        return jdbc.queryForObject("SELECT id FROM cuenta WHERE rol='CLIENTE' ORDER BY creada_en DESC LIMIT 1",
                UUID.class);
    }

    protected void insertarMovimientoPrevioV15(String uid, long asociacionId, long empleadoId, String lectura) {
        Instant instante = Instant.now().minusSeconds(60);
        LocalDateTime local = instante.atZone(ZoneId.of("America/Mexico_City")).toLocalDateTime();
        jdbc.update("""
                INSERT INTO movimiento_estacionamiento (
                    asociacion_id,tipo_persona,empleado_id,uid_historico,lectura_id,fecha_entrada,
                    hora_entrada,instante_entrada)
                VALUES (?, 'EMPLEADO', ?, ?, ?, ?, ?, ?)
                """, asociacionId, empleadoId, uid, UUID.fromString(lectura), local.toLocalDate(),
                local.toLocalTime(), java.time.OffsetDateTime.ofInstant(instante, java.time.ZoneOffset.UTC));
    }

    protected long idEvento(String lector, String lectura) {
        return jdbc.queryForObject("SELECT evento_id FROM evento_acceso WHERE lector=? AND lectura_id=?",
                Long.class, lector, UUID.fromString(lectura));
    }

    protected Instant horaEvento(String lector, String lectura) {
        return jdbc.queryForObject("SELECT ocurrido_en FROM evento_acceso WHERE lector=? AND lectura_id=?",
                java.sql.Timestamp.class, lector, UUID.fromString(lectura)).toInstant();
    }

    protected int contarEvento(String lector, String lectura) {
        return jdbc.queryForObject("SELECT count(*) FROM evento_acceso WHERE lector=? AND lectura_id=?",
                Integer.class, lector, UUID.fromString(lectura));
    }

    protected int contarMovimientos(String uid) {
        return jdbc.queryForObject("SELECT count(*) FROM movimiento_estacionamiento WHERE uid_historico=?",
                Integer.class, uid);
    }

    protected int contarMovimientoLectura(String lectura) {
        return jdbc.queryForObject("SELECT count(*) FROM movimiento_estacionamiento WHERE lectura_id=?",
                Integer.class, UUID.fromString(lectura));
    }

    protected void activarFalloEvento() {
        jdbc.execute("""
                CREATE FUNCTION fallo_evento_acceso() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'fallo de prueba'; END; $$
                """);
        jdbc.execute("""
                CREATE TRIGGER fallo_evento_acceso BEFORE INSERT OR UPDATE ON evento_acceso
                FOR EACH ROW EXECUTE FUNCTION fallo_evento_acceso()
                """);
    }

    protected void desactivarFalloEvento() {
        jdbc.execute("DROP TRIGGER IF EXISTS fallo_evento_acceso ON evento_acceso");
        jdbc.execute("DROP FUNCTION IF EXISTS fallo_evento_acceso()");
    }

    @SuppressWarnings("unchecked")
    protected static List<Map<String, Object>> items(Map<String, Object> pagina) {
        return (List<Map<String, Object>>) pagina.get("items");
    }

    protected static String uid() {
        return UUID.randomUUID().toString().replace("-", "").substring(0, 8).toUpperCase(Locale.ROOT);
    }

    protected static String variable(String nombre) {
        String valor = System.getenv(nombre);
        if (valor == null || valor.isBlank()) throw new IllegalStateException("Falta " + nombre + ".");
        return valor;
    }

    protected static String sha256(String texto) {
        try {
            byte[] bytes = MessageDigest.getInstance("SHA-256").digest(texto.getBytes(StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(bytes);
        } catch (java.security.NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException(excepcion);
        }
    }

    protected record Sesion(String cookie, String csrf) { }

    protected static final class SseProbe implements AutoCloseable {
        private final InputStream cuerpo;
        private final BlockingQueue<String> recibidos = new ArrayBlockingQueue<>(20);
        private final ExecutorService lector = Executors.newSingleThreadExecutor();

        SseProbe(String url, String cookie) throws Exception {
            HttpRequest solicitud = HttpRequest.newBuilder(URI.create(url)).header("Cookie", cookie).GET().build();
            HttpResponse<InputStream> respuesta = HttpClient.newHttpClient()
                    .send(solicitud, HttpResponse.BodyHandlers.ofInputStream());
            assertEquals(200, respuesta.statusCode());
            cuerpo = respuesta.body();
            lector.submit(this::leer);
        }

        String esperar(String nombre, Duration plazo) throws InterruptedException {
            long limite = System.nanoTime() + plazo.toNanos();
            while (System.nanoTime() < limite) {
                String bloque = recibidos.poll(Math.max(1, limite - System.nanoTime()), TimeUnit.NANOSECONDS);
                if (bloque == null) return null;
                if (bloque.startsWith(nombre + "\n")) return bloque;
            }
            return null;
        }

        private void leer() {
            try (BufferedReader lineas = new BufferedReader(new InputStreamReader(cuerpo, StandardCharsets.UTF_8))) {
                String evento = null;
                StringBuilder datos = new StringBuilder();
                String linea;
                while ((linea = lineas.readLine()) != null) {
                    if (linea.startsWith("event:")) evento = linea.substring(6).trim();
                    if (linea.startsWith("data:")) datos.append(linea.substring(5).trim());
                    if (linea.isEmpty()) {
                        if (evento != null) recibidos.offer(evento + "\n" + datos);
                        evento = null;
                        datos.setLength(0);
                    }
                }
            } catch (java.io.IOException ignorada) {
                // Cerrar el stream termina el lector durante el teardown del test.
            }
        }

        @Override
        public void close() throws Exception {
            cuerpo.close();
            lector.shutdownNow();
            lector.awaitTermination(1, TimeUnit.SECONDS);
        }
    }
}
