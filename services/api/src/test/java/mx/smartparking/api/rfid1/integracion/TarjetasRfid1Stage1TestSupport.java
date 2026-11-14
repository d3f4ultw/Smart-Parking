package mx.smartparking.api.rfid1.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.HexFormat;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Soporte HTTP, identidad sintética y datasource loopback para aceptación RFID 1. */
abstract class TarjetasRfid1Stage1TestSupport {

    protected static final JsonMapper JSON = JsonMapper.builder().build();
    protected static final String CSRF = "X-CSRF-TOKEN";
    protected static final String TOKEN_DISPOSITIVO = System.getenv("SMARTPARKING_RFID1_TOKEN");
    protected static final String RUTA_CAPTURAS = "/api/v1/rfid-1/capturas";
    protected static final String RUTA_LECTURAS = "/api/v1/dispositivos/rfid-1/lecturas";
    protected static final String RUTA_ESTADO_DISPOSITIVO = "/api/v1/dispositivos/rfid-1/capturas/";

    @LocalServerPort
    protected int puerto;

    @Autowired
    protected JdbcTemplate jdbc;

    protected Api dueno;
    protected Api anonimo;
    protected Api dispositivo;

    @DynamicPropertySource
    static void configurarDatasourceDescartable(DynamicPropertyRegistry propiedades) {
        String host = variable("POSTGRES_HOST");
        String puerto = variable("POSTGRES_PORT");
        String base = variable("POSTGRES_DB");
        String usuario = variable("POSTGRES_USER");
        String contrasena = variable("POSTGRES_PASSWORD");
        if (!"127.0.0.1".equals(host) || !puerto.matches("[0-9]{1,5}")
                || !puertoValido(puerto) || !"sp_rfid1_stage1_fresh".equals(base)
                || !"sp_rfid1_stage1".equals(usuario)) {
            throw new IllegalStateException("La aceptación RFID 1 requiere PostgreSQL sintético ligado a loopback.");
        }
        propiedades.add("spring.application.name", () -> "smartparking-tarjetas-rfid-stage1-aceptacion");
        propiedades.add("spring.profiles.active", () -> "test");
        propiedades.add("server.address", () -> "127.0.0.1");
        propiedades.add("server.port", () -> "0");
        propiedades.add("spring.datasource.url", () -> "jdbc:postgresql://127.0.0.1:" + puerto + "/" + base);
        propiedades.add("spring.datasource.username", () -> usuario);
        propiedades.add("spring.datasource.password", () -> contrasena);
        propiedades.add("smartparking.rfid1.token-sha256", TarjetasRfid1Stage1TestSupport::hashTokenDispositivo);
        propiedades.add("smartparking.rfid1.cleanup-delay-ms", () -> "250");
    }

    @BeforeEach
    void prepararSesionDueno() throws Exception {
        limpiarCapturasActivasSinteticas();
        URI base = URI.create("http://127.0.0.1:" + puerto + "/");
        Api visitante = new Api(base);
        String estado = texto(json(visitante.get("/api/v1/configuracion/estado")), "estado");
        if ("SIN_CONFIGURAR".equals(estado)) {
            crearDuenoInicial(visitante);
        } else {
            assertEquals("CONFIGURADA", estado, "La base sintética debe tener un único propietario configurado.");
        }
        dueno = iniciarSesion(base);
        anonimo = new Api(base);
        dispositivo = new Api(base, bearer());
    }

    @AfterEach
    void liberarLectorSintetico() {
        limpiarCapturasActivasSinteticas();
    }

    protected Api nuevaSesionDueno() throws Exception {
        return iniciarSesion(baseUrl());
    }

    protected URI baseUrl() {
        return URI.create("http://127.0.0.1:" + puerto + "/");
    }

    protected Persona crearEmpleado(Api cliente, String sufijo) throws Exception {
        HttpResponse<String> respuesta = cliente.post("/api/v1/empleados",
                Map.of("nombres", "Empleado RFID " + sufijo, "primerApellido", "Prueba"),
                Map.of(CSRF, cliente.csrf(), "Idempotency-Key", UUID.randomUUID().toString()));
        assertEquals(201, respuesta.statusCode(), "La API debe crear un empleado sintético.");
        JsonNode cuerpo = json(respuesta);
        return new Persona("EMPLEADO", texto(cuerpo, "codigo"), null, cuerpo.path("id").asLong());
    }

    protected Persona crearEmpleado(String sufijo) throws Exception {
        return crearEmpleado(dueno, sufijo);
    }

    protected Persona crearCliente(String sufijo) throws Exception {
        Api registro = new Api(baseUrl());
        String csrf = texto(json(registro.get("/api/v1/clientes/csrf")), "token");
        String correo = "rfid1-stage1-" + sufijo + "@example.invalid";
        String contrasena = "Clave sintética RFID 2026 " + sufijo;
        HttpResponse<String> alta = registro.post("/api/v1/clientes/registro",
                Map.of("nombres", "Cliente RFID " + sufijo, "primerApellido", "Prueba",
                        "correo", correo, "contrasena", contrasena), Map.of(CSRF, csrf));
        assertEquals(201, alta.statusCode(), "La API debe crear un cliente sintético sin membresía.");
        UUID clienteId = UUID.fromString(texto(json(alta), "clienteId"));
        String busqueda = URLEncoder.encode(sufijo, StandardCharsets.UTF_8);
        HttpResponse<String> encontrados = dueno.get(
                "/api/v1/tarjetas-rfid/personas?tipoEntidad=CLIENTE&busqueda=" + busqueda);
        assertEquals(200, encontrados.statusCode(), "La API debe encontrar al cliente por nombre sintético.");
        JsonNode candidatos = json(encontrados);
        for (JsonNode candidato : candidatos) {
            if (candidato.path("nombreCompleto").asText().contains(sufijo)) {
                return new Persona("CLIENTE", texto(candidato, "codigoPersona"), clienteId, null);
            }
        }
        throw new AssertionError("La búsqueda RFID debe devolver el código público del cliente sintético.");
    }

    protected String crearCaptura(Api cliente, Persona persona) throws Exception {
        HttpResponse<String> respuesta = cliente.post(RUTA_CAPTURAS,
                Map.of("tipoEntidad", persona.tipoEntidad(), "codigoPersona", persona.codigoPersona()),
                Map.of(CSRF, cliente.csrf(), "Idempotency-Key", UUID.randomUUID().toString()));
        assertEquals(201, respuesta.statusCode(), "La captura sintética debe reservar el lector.");
        JsonNode cuerpo = json(respuesta);
        assertEquals("PENDIENTE", texto(cuerpo, "estado"), "La captura debe iniciar sin asociar una tarjeta.");
        return texto(cuerpo, "capturaId");
    }

    protected Captura crearCaptura(Api cliente, String tipoEntidad, String codigoPersona) throws Exception {
        String id = crearCaptura(cliente, new Persona(tipoEntidad, codigoPersona, null, null));
        return new Captura(id);
    }

    protected void iniciarCaptura(String capturaId) throws Exception {
        assertEquals(204, dispositivo().post(RUTA_ESTADO_DISPOSITIVO + capturaId + "/estado",
                Map.of("estado", "ESCANEANDO"), Map.of()).statusCode());
    }

    private void limpiarCapturasActivasSinteticas() {
        assertTrue("sp_rfid1_stage1_fresh".equals(jdbc.queryForObject("SELECT current_database()", String.class)),
                "El cleanup solo puede ejecutarse en la base desechable Stage 1.");
        assertTrue("sp_rfid1_stage1".equals(jdbc.queryForObject("SELECT current_user", String.class)),
                "El cleanup solo puede ejecutarse con el usuario sintético Stage 1.");
        jdbc.update("UPDATE captura_rfid1 SET estado='CANCELADA', resultado=NULL, "
                + "codigo_error='CAPTURA_NO_VIGENTE', terminada_en=now(), actualizada_en=now() "
                + "WHERE estado IN ('PENDIENTE','ESCANEANDO','VISTA_PREVIA')");
        assertEquals(0, jdbc.queryForObject(
                "SELECT count(*) FROM captura_rfid1 WHERE estado IN ('PENDIENTE','ESCANEANDO','VISTA_PREVIA')",
                Integer.class), "Cada caso debe iniciar con el lector RFID1 libre.");
    }

    protected Resultado leer(String capturaId, String uid, String requestId) throws Exception {
        HttpResponse<String> respuesta = enviarLectura(capturaId, requestId, uid);
        return new Resultado(respuesta.statusCode(), respuesta.body(), json(respuesta));
    }

    protected void asociar(Api cliente, Persona persona, String uid) throws Exception {
        Captura captura = crearCaptura(cliente, persona.tipoEntidad(), persona.codigoPersona());
        iniciarCaptura(captura.id);
        Resultado lectura = leer(captura.id, uid, "0A01");
        assertEquals(200, lectura.estado, "La lectura sintética debe abrir una vista previa.");
        HttpResponse<String> confirmacion = cliente.confirmar(captura.id, UUID.randomUUID().toString());
        assertEquals(200, confirmacion.statusCode(), "La confirmación explícita debe asociar la tarjeta.");
    }

    protected long contarAsociacionesPorPersona(String tipoEntidad, Long idEmpleado) {
        if ("EMPLEADO".equals(tipoEntidad)) {
            return jdbc.queryForObject("SELECT count(*) FROM asociacion_tarjeta_rfid1 WHERE empleado_id=?",
                    Long.class, idEmpleado);
        }
        throw new IllegalArgumentException("La consulta por UUID de cliente requiere el helper de cliente.");
    }

    protected long contarAsociacionesPorPersona(String tipoEntidad, java.util.UUID idCliente) {
        if ("CLIENTE".equals(tipoEntidad)) {
            return jdbc.queryForObject("SELECT count(*) FROM asociacion_tarjeta_rfid1 WHERE cliente_id=?",
                    Long.class, idCliente);
        }
        throw new IllegalArgumentException("La consulta por id de empleado requiere el helper de empleado.");
    }

    protected boolean esperarEstado(String capturaId, String estado, Duration limite) throws InterruptedException {
        long fin = System.nanoTime() + limite.toNanos();
        do {
            if (estado.equals(estadoCaptura(capturaId))) {
                return true;
            }
            Thread.sleep(40);
        } while (System.nanoTime() < fin);
        return estado.equals(estadoCaptura(capturaId));
    }

    protected HttpResponse<String> enviarLectura(String capturaId, String requestId, String uid) throws Exception {
        return dispositivo().post(RUTA_LECTURAS,
                Map.of("capturaId", capturaId, "requestId", requestId, "uid", uid),
                Map.of("Idempotency-Key", uuidV5(capturaId, requestId)));
    }

    protected HttpResponse<String> cancelarCaptura(Api cliente, String capturaId) throws Exception {
        return cliente.delete(RUTA_CAPTURAS + "/" + capturaId, Map.of(CSRF, cliente.csrf()));
    }

    protected long contarAsociacionesPorUid(String uid) {
        return jdbc.queryForObject("SELECT count(*) FROM asociacion_tarjeta_rfid1 WHERE uid_canonico=?",
                Long.class, uid);
    }

    protected long contarUidTemporal(String capturaId) {
        return jdbc.queryForObject("SELECT count(*) FROM uid_temporal_rfid1 WHERE captura_id=?", Long.class, capturaId);
    }

    protected String estadoCaptura(String capturaId) {
        return jdbc.queryForObject("SELECT estado FROM captura_rfid1 WHERE captura_id=?", String.class, capturaId);
    }

    protected static JsonNode json(HttpResponse<String> respuesta) {
        try {
            return JSON.readTree(respuesta.body());
        } catch (RuntimeException excepcion) {
            throw new AssertionError("La respuesta de aceptación debe contener JSON válido.");
        }
    }

    protected static String texto(JsonNode cuerpo, String campo) {
        assertTrue(cuerpo != null && cuerpo.path(campo).isTextual(), "La respuesta debe incluir un campo de texto.");
        return cuerpo.path(campo).asText();
    }


    protected static String uuidV5(String capturaId, String requestId) {
        try {
            byte[] namespace = HexFormat.of().parseHex(capturaId);
            byte[] nombre = requestId.toUpperCase(java.util.Locale.ROOT).getBytes(StandardCharsets.US_ASCII);
            byte[] entrada = new byte[namespace.length + nombre.length];
            System.arraycopy(namespace, 0, entrada, 0, namespace.length);
            System.arraycopy(nombre, 0, entrada, namespace.length, nombre.length);
            byte[] hash = MessageDigest.getInstance("SHA-1").digest(entrada);
            hash[6] = (byte) ((hash[6] & 0x0f) | 0x50);
            hash[8] = (byte) ((hash[8] & 0x3f) | 0x80);
            java.nio.ByteBuffer buffer = java.nio.ByteBuffer.wrap(hash);
            return new UUID(buffer.getLong(), buffer.getLong()).toString();
        } catch (NoSuchAlgorithmException excepcion) {
            throw new AssertionError("SHA-1 debe estar disponible para la clave UUIDv5 del protocolo.");
        }
    }

    protected static Map<String, String> bearer() {
        return Map.of("Authorization", "Bearer " + variable("SMARTPARKING_RFID1_TOKEN"));
    }

    protected Api dispositivo() {
        return new Api(baseUrl(), bearer());
    }

    protected static String variable(String nombre) {
        String valor = System.getenv(nombre);
        if (valor == null || valor.isBlank()) {
            throw new IllegalStateException("La aceptación RFID 1 requiere sus variables sintéticas.");
        }
        return valor;
    }

    private static void crearDuenoInicial(Api anonimo) throws Exception {
        String correo = variable("RFID1_STAGE1_OWNER_EMAIL");
        String contrasena = variable("RFID1_STAGE1_OWNER_PASSWORD");
        String contrasenaAdmin = variable("RFID1_STAGE1_ADMIN_PASSWORD");
        String csrf = texto(json(anonimo.get("/api/v1/csrf")), "token");
        Map<String, Object> horario = Map.of("modo", "INTERVALO_DIARIO", "zonaHoraria", "America/Mexico_City",
                "horaApertura", "22:00", "horaCierre", "06:00");
        Map<String, Object> propietario = Map.of("nombres", "Propietario RFID", "primerApellido", "Stage1",
                "segundoApellido", "Prueba", "correo", correo, "contrasenaAcceso", contrasena,
                "contrasenaAdministrativa", contrasenaAdmin);
        Map<String, Object> estacionamiento = Map.of("nombre", "Estacionamiento de aceptación", "tipo", "MIXTO",
                "horario", horario);
        HttpResponse<String> respuesta = anonimo.post("/api/v1/configuracion/inicial",
                Map.of("propietario", propietario, "estacionamiento", estacionamiento),
                Map.of(CSRF, csrf, "Idempotency-Key", UUID.randomUUID().toString()));
        assertEquals(201, respuesta.statusCode(), "La aceptación debe configurar un DUENO sintético.");
    }

    private static Api iniciarSesion(URI base) throws Exception {
        Api cliente = new Api(base);
        String csrf = texto(json(cliente.get("/api/v1/csrf")), "token");
        HttpResponse<String> respuesta = cliente.post("/api/v1/sesion",
                Map.of("correo", variable("RFID1_STAGE1_OWNER_EMAIL"),
                        "contrasena", variable("RFID1_STAGE1_OWNER_PASSWORD")), Map.of(CSRF, csrf));
        assertEquals(200, respuesta.statusCode(), "El propietario sintético debe poder iniciar sesión.");
        cliente.csrf(texto(json(respuesta), "csrfToken"));
        return cliente;
    }

    private static String hashTokenDispositivo() {
        try {
            byte[] token = variable("SMARTPARKING_RFID1_TOKEN").getBytes(StandardCharsets.US_ASCII);
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(token));
        } catch (NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException("SHA-256 debe estar disponible para la credencial sintética.");
        }
    }

    private static boolean puertoValido(String valor) {
        try {
            int numero = Integer.parseInt(valor);
            return numero >= 1 && numero <= 65_535;
        } catch (NumberFormatException excepcion) {
            return false;
        }
    }

    protected static final class Persona {
        final String tipoEntidad;
        final String codigo;
        final UUID clienteId;
        final Long id;

        Persona(String tipoEntidad, String codigo, UUID clienteId, Long id) {
            this.tipoEntidad = tipoEntidad;
            this.codigo = codigo;
            this.clienteId = clienteId;
            this.id = id;
        }

        String tipoEntidad() {
            return tipoEntidad;
        }

        String codigoPersona() {
            return codigo;
        }

        UUID clienteId() {
            return clienteId;
        }

        Long empleadoId() {
            return id;
        }
    }

    protected static final class Captura {
        final String id;

        Captura(String id) {
            this.id = id;
        }
    }

    protected static final class Resultado {
        final int estado;
        final String texto;
        final JsonNode cuerpo;

        Resultado(int estado, String texto, JsonNode cuerpo) {
            this.estado = estado;
            this.texto = texto;
            this.cuerpo = cuerpo;
        }
    }

    protected static final class Api extends ApiHttpStage1 {
        Api(URI base) {
            super(base);
        }

        Api(URI base, Map<String, String> encabezadosFijos) {
            super(base, encabezadosFijos);
        }
    }
}
