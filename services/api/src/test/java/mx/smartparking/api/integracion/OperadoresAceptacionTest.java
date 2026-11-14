package mx.smartparking.api.integracion;

import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.assertEstado;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.configuracion;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.leerJson;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.texto;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.verificarSinSecretos;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;
import static org.mockito.Mockito.mock;

import java.lang.reflect.Field;
import java.net.InetAddress;
import java.net.URI;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.sql.DataSource;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;
import mx.smartparking.api.activacion.ProteccionIntentosActivacion;
import mx.smartparking.api.activacion.ServicioActivacionOperador;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.correo.NotificadorInvitacionOperador;
import mx.smartparking.api.persistencia.RepositorioActivacionOperadorJdbc;
import mx.smartparking.api.integracion.ApiCliente;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.security.crypto.password.PasswordEncoder;

/** Aceptación HTTP de registro, activación y recuperación de operadores sintéticos. */
final class OperadoresAceptacionTest {

    private static final String CSRF = "X-CSRF-TOKEN";
    private static final String SESION = "/api/v1/sesion";
    private static final String REGISTRO = "/api/v1/operadores";
    private static final String ASUNTO_INVITACION = "Activa tu cuenta de Smart Parking";
    private static final Pattern TOKEN_ENLACE = Pattern.compile("https?://[^\\s#]+/activar-operador#([A-Za-z0-9_-]{43})");

    @Test
    void aceptaRegistroActivacionReemisionYLimitesDeSeguridad() throws Exception {
        URI apiUrl = PropietarioApiAceptacionSupport.baseUrlOptIn();
        URI smtpFallidoUrl = MailpitApiCliente.localUrlOptIn(
                "smartparking.integration.smtp-failure-api-url", "API SMTP fallido");
        URI smtpDeshabilitadoUrl = MailpitApiCliente.localUrlOptIn(
                "smartparking.integration.smtp-disabled-api-url", "API SMTP deshabilitado");
        URI mailpit = MailpitApiCliente.baseUrlOptIn("smartparking.mailpit-url");
        ConexionJdbc conexion = conexionJdbcOptIn();
        verificarEsquemaV16(conexion.jdbc());

        String sufijo = UUID.randomUUID().toString().replace("-", "");
        String correoDueno = "dueno." + sufijo + "@example.test";
        String contrasenaDueno = "Dueno-sintetico-2026!";
        String correoOperador = "operador." + sufijo + "@example.test";
        String contrasenaOperador = "Operador-sintetico-2026!";
        assertEquals(0, MailpitApiCliente.cantidadMensajes(mailpit));

        ApiCliente anonimo = new ApiCliente(apiUrl);
        String csrfAnonimo = anonimo.obtenerCsrf(true);
        assertEquals(401, anonimo.get(REGISTRO).statusCode(), "El directorio exige sesión DUENO.");
        HttpResponse<String> sinDueno = anonimo.postJson(REGISTRO, solicitud("Sin dueño", correoOperador),
                Map.of(CSRF, csrfAnonimo, "Idempotency-Key", clave("sin-dueno-" + sufijo)));
        assertEquals(401, sinDueno.statusCode(), "La ruta de registro no acepta sesiones anónimas.");

        ApiCliente configurador = new ApiCliente(apiUrl);
        String csrfInicial = configurador.obtenerCsrf(true);
        assertEstado(configurador, "SIN_CONFIGURAR");
        HttpResponse<String> configuracionInicial = configurador.post(
                "/api/v1/configuracion/inicial",
                configuracion(correoDueno, contrasenaDueno, "Administracion-sintetica-2026!", "Prueba aislada"),
                clave("configuracion-" + sufijo), csrfInicial);
        assertEquals(201, configuracionInicial.statusCode());
        verificarSinSecretos(configuracionInicial.body(), contrasenaDueno);

        ClienteAutenticado dueno = iniciarSesion(apiUrl, correoDueno, contrasenaDueno);
        Map<String, Object> solicitud = solicitud("Operador Sintético", correoOperador);
        String claveRegistro = clave("registro-operador-" + sufijo);
        HttpResponse<String> sinCsrf = dueno.api().post(REGISTRO, solicitud, claveRegistro, null);
        assertEquals(403, sinCsrf.statusCode(), "La mutación de registro exige CSRF.");
        HttpResponse<String> alta = dueno.api().post(REGISTRO, solicitud, claveRegistro, dueno.csrf());
        assertEquals(201, alta.statusCode());
        assertEquals("PENDIENTE", texto(leerJson(alta.body()), "estado"));
        UUID operadorId = UUID.fromString(texto(leerJson(alta.body()), "id"));
        HttpResponse<String> repetida = dueno.api().post(REGISTRO, solicitud, claveRegistro, dueno.csrf());
        assertEquals(201, repetida.statusCode());
        assertEquals(operadorId.toString(), texto(leerJson(repetida.body()), "id"));
        assertEquals(1, MailpitApiCliente.cantidadPorAsunto(mailpit, ASUNTO_INVITACION));

        Map<String, Object> solicitudReutilizada = solicitud("Otro nombre", correoOperador);
        assertEquals(409, dueno.api().post(REGISTRO, solicitudReutilizada, claveRegistro, dueno.csrf()).statusCode());
        assertEquals(409, dueno.api().post(REGISTRO,
                solicitud("Colisión", correoOperador.toUpperCase(java.util.Locale.ROOT)),
                clave("colision-pendiente-" + sufijo), dueno.csrf()).statusCode());

        Map<String, Object> solicitudConcurrente = solicitud("Operador Concurrente", "o" + sufijo + "@example.test");
        String claveConcurrente = clave("registro-concurrente-" + sufijo);
        List<HttpResponse<String>> registrosConcurrentes = ejecutarConcurrentemente(
                () -> registrar(dueno.api(), solicitudConcurrente, claveConcurrente, dueno.csrf()),
                () -> registrar(dueno.api(), solicitudConcurrente, claveConcurrente, dueno.csrf()));
        assertEquals(2L, registrosConcurrentes.stream().filter(respuesta -> respuesta.statusCode() == 201).count());
        String operadorConcurrenteId = texto(leerJson(registrosConcurrentes.get(0).body()), "id");
        assertEquals(operadorConcurrenteId, texto(leerJson(registrosConcurrentes.get(1).body()), "id"));
        assertEquals(2, MailpitApiCliente.cantidadPorAsunto(mailpit, ASUNTO_INVITACION));
        String cuerpoCorreo = MailpitApiCliente.textoUnico(mailpit, ASUNTO_INVITACION, correoOperador);
        String token = extraerToken(cuerpoCorreo);
        verificarSinSecretos(alta.body(), token, contrasenaOperador);
        Invitacion invitacion = invitacion(conexion.jdbc(), operadorId);
        assertEquals(hash(token), invitacion.tokenHash(), "PostgreSQL conserva SHA-256, no el token bearer.");
        assertEquals(64, invitacion.tokenHash().length());
        assertTrue(invitacion.generadoEn().plus(Duration.ofHours(2)).equals(invitacion.venceEn()));
        verificarVencimientoExacto(conexion.dataSource(), conexion.jdbc(), invitacion.venceEn(), token);

        HttpResponse<String> contrasenaInvalida = dueno.api().postJson(
                "/api/v1/operadores/activacion/completar",
                Map.of("token", token, "contrasena", "corta", "confirmarContrasena", "corta"),
                Map.of(CSRF, dueno.csrf()));
        assertEquals(400, contrasenaInvalida.statusCode());
        HttpResponse<String> tokenAunVigente = dueno.api().postJson(
                "/api/v1/operadores/activacion/validar", Map.of("token", token), Map.of(CSRF, dueno.csrf()));
        assertEquals(200, tokenAunVigente.statusCode(), "Una contraseña inválida no consume la invitación.");

        List<HttpResponse<String>> activaciones = ejecutarConcurrentemente(
                () -> completar(dueno.api(), token, dueno.csrf(), contrasenaOperador),
                () -> completar(dueno.api(), token, dueno.csrf(), contrasenaOperador));
        assertEquals(1L, activaciones.stream().filter(respuesta -> respuesta.statusCode() == 204).count());
        assertEquals(1L, activaciones.stream().filter(respuesta -> respuesta.statusCode() == 410).count(),
                "Una sola finalización concurrente debe consumir el token.");
        assertEquals("ACTIVA", jdbcCuentaEstado(conexion.jdbc(), operadorId));
        assertNotNull(jdbcHashContrasena(conexion.jdbc(), operadorId));
        assertNotNull(invitacion(conexion.jdbc(), operadorId).consumidoEn());

        HttpResponse<String> colisionActiva = dueno.api().post(REGISTRO,
                solicitud("Cuenta duplicada", correoOperador), clave("colision-activa-" + sufijo), dueno.csrf());
        assertEquals(409, colisionActiva.statusCode(), "El índice único también reserva correos activos.");
        verificarLoginOperadorSinVinculoRechazado(
                apiUrl, conexion.jdbc(), operadorId, correoOperador, contrasenaOperador, sufijo);

        aceptarFalloInicialYReemision(smtpFallidoUrl, dueno, conexion.jdbc(), mailpit, correoDueno,
                contrasenaDueno, sufijo);
        aceptarReintentoSiSmtpDeshabilitado(smtpDeshabilitadoUrl, dueno, conexion.jdbc(), mailpit,
                correoDueno, contrasenaDueno, sufijo);
    }

    private static void verificarEsquemaV16(JdbcTemplate jdbc) {
        assertTrue(jdbc.queryForObject("SELECT EXISTS (SELECT 1 FROM flyway_schema_history WHERE version='6' AND success)",
                Boolean.class), "La base descartable debe tener V6 aplicada.");
        assertTrue(jdbc.queryForObject("SELECT EXISTS (SELECT 1 FROM flyway_schema_history WHERE version='16' AND success)",
                Boolean.class), "La base aislada debe conservar Flyway V16 sin migración nueva.");
        String rolEstado = restriccion(jdbc, "cuenta", "cuenta_rol_estado_ck").toUpperCase(java.util.Locale.ROOT);
        assertTrue(rolEstado.contains("PENDIENTE") && rolEstado.contains("DUENO") && rolEstado.contains("OPERADOR"));
        String credenciales = restriccion(jdbc, "cuenta", "cuenta_estado_credencial_ck").toUpperCase(java.util.Locale.ROOT);
        assertTrue(credenciales.contains("PENDIENTE") && credenciales.contains("HASH_CONTRASENA_ACCESO"));
        String indice = jdbc.queryForObject(
                "SELECT pg_get_expr(indpred, indrelid) FROM pg_index WHERE indexrelid='cuenta_correo_reservada_uq'::regclass",
                String.class).toUpperCase(java.util.Locale.ROOT);
        assertTrue(indice.contains("ACTIVA") && indice.contains("PENDIENTE"));
        String vigencia = restriccion(jdbc, "invitacion_operador", "invitacion_operador_vigencia_ck");
        assertTrue(vigencia.contains("2 hours") || vigencia.contains("02:00:00"));
        assertTrue(jdbc.queryForObject("SELECT to_regclass('invitacion_operador') IS NOT NULL", Boolean.class));
        assertTrue(jdbc.queryForObject("SELECT to_regclass('idempotencia_registro_operador') IS NOT NULL", Boolean.class));
    }

    private static String restriccion(JdbcTemplate jdbc, String tabla, String nombre) {
        String definicion = jdbc.queryForObject(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid=?::regclass AND conname=?",
                String.class, tabla, nombre);
        assertNotNull(definicion);
        return definicion;
    }

    private static void verificarVencimientoExacto(
            DataSource dataSource, JdbcTemplate jdbc, Instant venceEn, String token) throws Exception {
        ServicioActivacionOperador servicio = new ServicioActivacionOperador(
                new RepositorioActivacionOperadorJdbc(jdbc), mock(NotificadorInvitacionOperador.class),
                mock(PasswordEncoder.class), new ProteccionIntentosActivacion(),
                new DataSourceTransactionManager(dataSource), "https://example.test");
        Field reloj = ServicioActivacionOperador.class.getDeclaredField("reloj");
        reloj.setAccessible(true);
        reloj.set(servicio, Clock.fixed(venceEn.minusNanos(1), ZoneOffset.UTC));
        assertDoesNotThrow(() -> {
            servicio.validar(token);
        });
        reloj.set(servicio, Clock.fixed(venceEn, ZoneOffset.UTC));
        ErrorConfiguracion expirado = assertThrows(ErrorConfiguracion.class, () -> servicio.validar(token));
        assertEquals(410, expirado.estadoHttp().value(), "El instante exacto de vencimiento ya no es válido.");
    }

    private static List<HttpResponse<String>> ejecutarConcurrentemente(
            java.util.function.Supplier<HttpResponse<String>> primera,
            java.util.function.Supplier<HttpResponse<String>> segunda) {
        var primero = CompletableFuture.supplyAsync(primera);
        var segundo = CompletableFuture.supplyAsync(segunda);
        CompletableFuture.allOf(primero, segundo).join();
        return List.of(primero.join(), segundo.join());
    }

    private static HttpResponse<String> registrar(
            ApiCliente api, Map<String, Object> solicitud, String clave, String csrf) {
        try {
            return api.post(REGISTRO, solicitud, clave, csrf);
        } catch (Exception excepcion) {
            throw new CompletionException(excepcion);
        }
    }

    private static HttpResponse<String> completar(ApiCliente api, String token, String csrf, String contrasena) {
        try {
            return api.postJson("/api/v1/operadores/activacion/completar",
                    Map.of("token", token, "contrasena", contrasena,
                            "confirmarContrasena", contrasena), Map.of(CSRF, csrf));
        } catch (Exception excepcion) {
            throw new CompletionException(excepcion);
        }
    }

    private static void aceptarFalloInicialYReemision(
            URI urlFallida, ClienteAutenticado dueno, JdbcTemplate jdbc, URI mailpit,
            String correoDueno, String contrasenaDueno, String sufijo) throws Exception {
        String correoFallido = "fallido." + sufijo + "@example.test";
        ClienteAutenticado clienteFallido = iniciarSesion(urlFallida, correoDueno, contrasenaDueno);
        HttpResponse<String> fallida = clienteFallido.api().post(REGISTRO,
                solicitud("Correo fallido", correoFallido), clave("smtp-fallido-" + sufijo), clienteFallido.csrf());
        assertEquals(201, fallida.statusCode());
        assertEquals(EstadoEnvioInvitacion.FALLIDO.name(), texto(leerJson(fallida.body()), "estadoInvitacion"));
        assertEquals(0, MailpitApiCliente.textosPorAsunto(mailpit, ASUNTO_INVITACION, correoFallido).size());

        String correo = "reemision." + sufijo + "@example.test";
        HttpResponse<String> inicial = dueno.api().post(REGISTRO, solicitud("Reemisión", correo),
                clave("reemision-inicial-" + sufijo), dueno.csrf());
        assertEquals(201, inicial.statusCode());
        UUID id = UUID.fromString(texto(leerJson(inicial.body()), "id"));
        String tokenAnterior = extraerToken(MailpitApiCliente.textoUnico(mailpit, ASUNTO_INVITACION, correo));
        jdbc.update("UPDATE invitacion_operador SET estado_envio='FALLIDO' WHERE operador_id=?", id);

        String claveReemision = clave("reemision-smtp-fallido-" + sufijo);
        HttpResponse<String> reemitida = dueno.api().postJson(
                REGISTRO + "/" + id + "/invitacion/reemitir", null,
                Map.of(CSRF, dueno.csrf(), "Idempotency-Key", claveReemision));
        assertEquals(200, reemitida.statusCode(), "El UUID debe recorrer la ruta de reemisión.");
        assertEquals("ENVIADO", texto(leerJson(reemitida.body()), "estadoInvitacion"));
        Invitacion actual = invitacion(jdbc, id);
        assertFalse(hash(tokenAnterior).equals(actual.tokenHash()), "La reemisión reemplaza el hash anterior.");
        List<String> mensajes = MailpitApiCliente.textosPorAsunto(mailpit, ASUNTO_INVITACION, correo);
        assertEquals(2, mensajes.size());
        String tokenNuevo = "";
        for (String mensaje : mensajes) {
            String candidato = extraerToken(mensaje);
            if (hash(candidato).equals(actual.tokenHash())) tokenNuevo = candidato;
        }
        assertTrue(!tokenNuevo.isBlank(), "Mailpit debe contener el token de la generación vigente.");
        assertEquals(410, dueno.api().postJson("/api/v1/operadores/activacion/validar",
                Map.of("token", tokenAnterior), Map.of(CSRF, dueno.csrf())).statusCode());
        assertEquals(200, dueno.api().postJson("/api/v1/operadores/activacion/validar",
                Map.of("token", tokenNuevo), Map.of(CSRF, dueno.csrf())).statusCode());
        verificarSinSecretos(reemitida.body(), tokenNuevo);
        assertEquals(200, dueno.api().postJson(REGISTRO + "/" + id + "/invitacion/reemitir", null,
                Map.of(CSRF, dueno.csrf(), "Idempotency-Key", claveReemision)).statusCode());
        assertEquals(2, MailpitApiCliente.textosPorAsunto(mailpit, ASUNTO_INVITACION, correo).size());
    }

    private static void aceptarReintentoSiSmtpDeshabilitado(
            URI urlDeshabilitada, ClienteAutenticado dueno, JdbcTemplate jdbc, URI mailpit,
            String correoDueno, String contrasenaDueno, String sufijo) throws Exception {
        String correo = "deshabilitado." + sufijo + "@example.test";
        ClienteAutenticado deshabilitado = iniciarSesion(urlDeshabilitada, correoDueno, contrasenaDueno);
        HttpResponse<String> alta = deshabilitado.api().post(REGISTRO,
                solicitud("Correo deshabilitado", correo), clave("smtp-off-registro-" + sufijo), deshabilitado.csrf());
        assertEquals(201, alta.statusCode());
        assertEquals("DESHABILITADO", texto(leerJson(alta.body()), "estadoInvitacion"));
        UUID id = UUID.fromString(texto(leerJson(alta.body()), "id"));
        Invitacion inicial = invitacion(jdbc, id);
        String claveReemision = clave("smtp-off-retry-" + sufijo);
        HttpResponse<String> error = deshabilitado.api().postJson(
                REGISTRO + "/" + id + "/invitacion/reemitir", null,
                Map.of(CSRF, deshabilitado.csrf(), "Idempotency-Key", claveReemision));
        assertEquals(503, error.statusCode());
        Invitacion trasError = invitacion(jdbc, id);
        assertFalse(trasError.reemisionUsada());
        assertEquals(inicial.tokenHash(), trasError.tokenHash());

        HttpResponse<String> retry = dueno.api().postJson(REGISTRO + "/" + id + "/invitacion/reemitir", null,
                Map.of(CSRF, dueno.csrf(), "Idempotency-Key", claveReemision));
        assertEquals(200, retry.statusCode(), "La misma clave debe funcionar al habilitar SMTP.");
        String textoCorreo = MailpitApiCliente.textoUnico(mailpit, ASUNTO_INVITACION, correo);
        String token = extraerToken(textoCorreo);
        assertEquals(hash(token), invitacion(jdbc, id).tokenHash());
        assertTrue(invitacion(jdbc, id).reemisionUsada());
    }

    private static void verificarLoginOperadorSinVinculoRechazado(
            URI base, JdbcTemplate jdbc, UUID operadorId,
            String correo, String contrasena, String sufijo) throws Exception {
        assertEquals(1, jdbc.queryForObject(
                "SELECT count(*) FROM cuenta WHERE id = ? AND empleado_id IS NULL", Integer.class, operadorId));
        ClienteAutenticado noOperador = iniciarSesionIntentada(base, correo, contrasena);
        assertEquals(401, noOperador.respuestaLogin().statusCode(),
                "Una cuenta OPERADOR sin empleado vinculado no puede iniciar sesión.");
        ClienteAutenticado correoDesconocido = iniciarSesionIntentada(
                base, "desconocido." + sufijo + "@example.test", "Clave-aleatoria-sintetica-2026!");
        assertEquals(401, correoDesconocido.respuestaLogin().statusCode());
        assertEquals(texto(leerJson(correoDesconocido.respuestaLogin().body()), "codigo"),
                texto(leerJson(noOperador.respuestaLogin().body()), "codigo"),
                "La respuesta no distingue un OPERADOR de credenciales desconocidas.");
    }

    private static ClienteAutenticado iniciarSesion(URI base, String correo, String contrasena) throws Exception {
        ApiCliente api = new ApiCliente(base);
        String csrf = api.obtenerCsrf(true);
        HttpResponse<String> respuesta = api.postJson(SESION, Map.of("correo", correo, "contrasena", contrasena),
                Map.of(CSRF, csrf));
        assertEquals(200, respuesta.statusCode(), "Solo la cuenta DUENO debe iniciar sesión.");
        String csrfNuevo = texto(leerJson(respuesta.body()), "csrfToken");
        api.csrf(csrfNuevo);
        return new ClienteAutenticado(api, csrfNuevo, respuesta);
    }

    private static ClienteAutenticado iniciarSesionIntentada(URI base, String correo, String contrasena)
            throws Exception {
        ApiCliente api = new ApiCliente(base);
        String csrf = api.obtenerCsrf(true);
        HttpResponse<String> respuesta = api.postJson(SESION, Map.of("correo", correo, "contrasena", contrasena),
                Map.of(CSRF, csrf));
        return new ClienteAutenticado(api, csrf, respuesta);
    }

    private static Map<String, Object> solicitud(String nombres, String correo) {
        return Map.of("nombres", nombres, "primerApellido", "Prueba", "segundoApellido", "Sintética",
                "correo", correo);
    }

    private static String extraerToken(String cuerpo) {
        Matcher matcher = TOKEN_ENLACE.matcher(cuerpo);
        assertTrue(matcher.find(), "Mailpit debe contener un enlace de activación con token temporal.");
        return matcher.group(1);
    }

    private static String hash(String valor) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(valor.getBytes(StandardCharsets.UTF_8)));
    }

    private static Invitacion invitacion(JdbcTemplate jdbc, UUID id) {
        return jdbc.queryForObject("SELECT token_hash, generado_en, vence_en, consumido_en, reemision_usada "
                + "FROM invitacion_operador WHERE operador_id=?", (rs, fila) -> new Invitacion(
                rs.getString("token_hash").trim(), rs.getTimestamp("generado_en").toInstant(),
                rs.getTimestamp("vence_en").toInstant(),
                rs.getTimestamp("consumido_en") == null ? null : rs.getTimestamp("consumido_en").toInstant(),
                rs.getBoolean("reemision_usada")), id);
    }

    private static String jdbcCuentaEstado(JdbcTemplate jdbc, UUID id) {
        return jdbc.queryForObject("SELECT estado FROM cuenta WHERE id=?", String.class, id);
    }

    private static String jdbcHashContrasena(JdbcTemplate jdbc, UUID id) {
        return jdbc.queryForObject("SELECT hash_contrasena_acceso FROM cuenta WHERE id=?", String.class, id);
    }

    private static ConexionJdbc conexionJdbcOptIn() throws Exception {
        assumeTrue(Boolean.parseBoolean(System.getProperty("smartparking.integration.disposable", "false")),
                "La conexión JDBC exige el indicador de recursos descartables.");
        String url = System.getProperty("smartparking.integration.jdbc-url", "");
        String usuario = System.getProperty("smartparking.integration.jdbc-user", "");
        String contrasena = System.getProperty("smartparking.integration.jdbc-password", "");
        assertTrue(url.startsWith("jdbc:postgresql://") && !usuario.isBlank() && !contrasena.isBlank(),
                "Configura JDBC descartable sin incluir valores en la salida.");
        URI destino = URI.create(url.replaceFirst("^jdbc:postgresql://", "http://"));
        InetAddress[] direcciones = InetAddress.getAllByName(destino.getHost());
        assertTrue(direcciones.length > 0 && java.util.Arrays.stream(direcciones)
                .allMatch(InetAddress::isLoopbackAddress), "La aceptación JDBC solo puede usar loopback.");
        DriverManagerDataSource dataSource = new DriverManagerDataSource(url, usuario, contrasena);
        dataSource.setDriverClassName("org.postgresql.Driver");
        return new ConexionJdbc(dataSource, new JdbcTemplate(dataSource));
    }

    private static String clave(String base) {
        return base + "-" + UUID.randomUUID();
    }

    private record ClienteAutenticado(ApiCliente api, String csrf, HttpResponse<String> respuestaLogin) {
    }

    private record ConexionJdbc(DataSource dataSource, JdbcTemplate jdbc) {
    }

    private record Invitacion(
            String tokenHash, Instant generadoEn, Instant venceEn, Instant consumidoEn, boolean reemisionUsada) {
    }
}
