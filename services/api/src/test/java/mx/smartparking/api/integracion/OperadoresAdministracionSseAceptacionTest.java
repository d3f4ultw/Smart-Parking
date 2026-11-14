package mx.smartparking.api.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.io.BufferedReader;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import mx.smartparking.api.integracion.ApiCliente;
import mx.smartparking.api.integracion.PropietarioApiAceptacionSupport;
import org.junit.jupiter.api.Test;

/** Comprueba el cursor y el replay del evento de operadores en el stream administrativo real. */
final class OperadoresAdministracionSseAceptacionTest {

    private static final String CSRF = "X-CSRF-TOKEN";
    private static final String EVENTOS = "/api/v1/eventos/administracion";
    private static final String EVENTO_EMPLEADO = "empleado.directorio.actualizado";
    private static final String EVENTO_OPERADOR = "operador.directorio.actualizado";
    private static final String EVENTO_RESINCRONIZAR = "administracion.directorio.resincronizar";
    private static final String EVENTO_HEARTBEAT = "empleado.heartbeat";
    private static final HttpClient CLIENTE_HTTP = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(4))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();

    @Test
    void reanudaElTipoDeEventoOperadorYResincronizaUnCursorInvalido() throws Exception {
        assumeTrue(Boolean.parseBoolean(System.getProperty("smartparking.integration.disposable", "false")),
                "Aceptación omitida: requiere el proyecto de servicios descartables.");
        assertEquals("test", System.getProperty("smartparking.integration.profile"));

        URI apiUrl = OperadoresAdministracionEntornoAceptacion.apiUrl();
        String correoDueno = System.getenv("TEST_OWNER_EMAIL");
        String contrasenaDueno = System.getenv("TEST_OWNER_PASSWORD");
        assumeTrue(correoDueno != null && correoDueno.endsWith("@example.test")
                        && contrasenaDueno != null && !contrasenaDueno.isBlank(),
                "La aceptación requiere credenciales sintéticas del propietario.");
        OperadoresAdministracionEntornoAceptacion.prepararCredencialDueno(correoDueno, contrasenaDueno);

        ApiCliente dueno = iniciarSesion(apiUrl, correoDueno, contrasenaDueno);
        ApiCliente segundoDueno = iniciarSesion(apiUrl, correoDueno, contrasenaDueno);
        String cookieSecundaria = segundoDueno.cookie("JSESSIONID");
        assertNotNull(cookieSecundaria);
        assertNotEquals(dueno.cookie("JSESSIONID"), cookieSecundaria,
                "El replay se debe validar con una sesión DUENO independiente.");

        String sufijo = UUID.randomUUID().toString();
        Map<String, Object> registro = Map.of(
                "nombres", "SSE " + sufijo,
                "primerApellido", "Aceptacion",
                "segundoApellido", "Eventos",
                "correo", "sse." + sufijo + "@example.test");
        String sufijoReconexion = UUID.randomUUID().toString();
        Map<String, Object> registroReconexion = Map.of(
                "nombres", "Reconectado " + sufijoReconexion,
                "primerApellido", "Aceptacion",
                "segundoApellido", "Eventos",
                "correo", "reconexion." + sufijoReconexion + "@example.test");
        EmpleadoPreparado empleado = crearEmpleado(dueno, registro);
        EmpleadoPreparado empleadoReconexion = crearEmpleado(dueno, registroReconexion);
        String cursorInicial = cursorActual(dueno);
        try (FlujoEventos anonimo = abrirFlujo(apiUrl, null, cursorInicial)) {
            assertEquals(401, anonimo.respuesta().statusCode(), "El stream administrativo requiere DUENO.");
        }

        String claveRegistro = "sse-operador-" + sufijo;
        HttpResponse<String> alta = promocionar(dueno, empleado, claveRegistro);
        assertEquals(200, alta.statusCode());
        String idOperador = PropietarioApiAceptacionSupport.texto(
                PropietarioApiAceptacionSupport.leerJson(alta.body()), "operadorId");

        String cursorTrasAlta = cursorActual(dueno);
        List<SseEvento> eventosIniciales;
        try (ExecutorService lector = Executors.newSingleThreadExecutor(tarea -> {
                    Thread hilo = new Thread(tarea, "aceptacion-sse-operadores");
                    hilo.setDaemon(true);
                    return hilo;
                });
                FlujoEventos flujo = abrirFlujo(apiUrl, cookieSecundaria, cursorInicial)) {
            assertEquals(200, flujo.respuesta().statusCode());
            assertTrue(flujo.tipoContenido().startsWith("text/event-stream"));
            eventosIniciales = leerEventosHastaCursor(
                    lector, flujo, cursorInicial, cursorTrasAlta, Duration.ofSeconds(8));
        }
        assertEquals(3, eventosIniciales.size(),
                "La promoción y el resultado visible de la invitación deben invalidar los directorios.");
        assertEquals(List.of(EVENTO_EMPLEADO, EVENTO_OPERADOR, EVENTO_OPERADOR),
                eventosIniciales.stream().map(SseEvento::evento).toList());
        for (SseEvento evento : eventosIniciales) {
            assertTrue(evento.id().matches("[0-9a-fA-F-]{36}:[0-9]+"));
            assertEquals("{}", evento.datos().strip());
            assertFalseContiene(evento.datos(), registro.get("nombres").toString());
            assertFalseContiene(evento.datos(), registro.get("correo").toString());
        }
        assertEquals(cursorTrasAlta, eventosIniciales.getLast().id(),
                "El último evento del replay debe coincidir con el cursor actual del directorio.");
        HttpResponse<String> replayIdempotente = promocionar(dueno, empleado, claveRegistro);
        assertEquals(200, replayIdempotente.statusCode());
        assertEquals(idOperador, PropietarioApiAceptacionSupport.texto(
                PropietarioApiAceptacionSupport.leerJson(replayIdempotente.body()), "operadorId"));
        assertEquals(cursorTrasAlta, cursorActual(dueno),
                "Repetir el alta idempotente no debe publicar otro evento.");

        String cursorTrasReconexion;
        List<SseEvento> eventosReconexion;
        try (ExecutorService lector = Executors.newSingleThreadExecutor(tarea -> {
                    Thread hilo = new Thread(tarea, "aceptacion-sse-reconexion");
                    hilo.setDaemon(true);
                    return hilo;
                });
                FlujoEventos flujo = abrirFlujo(apiUrl, cookieSecundaria, cursorTrasAlta)) {
            assertEquals(200, flujo.respuesta().statusCode());
            assertEquals(200, promocionar(dueno, empleadoReconexion,
                    "sse-reconexion-" + sufijoReconexion).statusCode());
            cursorTrasReconexion = cursorActual(dueno);
            eventosReconexion = leerEventosHastaCursor(
                    lector, flujo, cursorTrasAlta, cursorTrasReconexion, Duration.ofSeconds(8));
        }
        assertEquals(3, eventosReconexion.size());
        assertEquals(List.of(EVENTO_EMPLEADO, EVENTO_OPERADOR, EVENTO_OPERADOR),
                eventosReconexion.stream().map(SseEvento::evento).toList());
        for (SseEvento evento : eventosReconexion) {
            assertEquals("{}", evento.datos().strip());
            assertFalseContiene(evento.datos(), registroReconexion.get("nombres").toString());
            assertFalseContiene(evento.datos(), registroReconexion.get("correo").toString());
        }
        assertTrue(eventosReconexion.stream().noneMatch(evento ->
                eventosIniciales.stream().anyMatch(anterior -> anterior.id().equals(evento.id()))),
                "La reconexión no debe reproducir cursores ya confirmados.");
        assertEquals(cursorTrasReconexion, eventosReconexion.getLast().id());

        try (ExecutorService lector = Executors.newSingleThreadExecutor(tarea -> {
                    Thread hilo = new Thread(tarea, "aceptacion-sse-resincronizacion");
                    hilo.setDaemon(true);
                    return hilo;
                });
                FlujoEventos flujo = abrirFlujo(apiUrl, cookieSecundaria, "cursor-invalido")) {
            assertEquals(200, flujo.respuesta().statusCode());
            SseEvento resincronizacion = leerEventoNoHeartbeat(lector, flujo, Duration.ofSeconds(8));
            assertEquals(EVENTO_RESINCRONIZAR, resincronizacion.evento());
            assertEquals(cursorActual(dueno), resincronizacion.id());
            assertFalseContiene(resincronizacion.datos(), registroReconexion.get("correo").toString());
        }
    }

    private static ApiCliente iniciarSesion(URI apiUrl, String correo, String contrasena) throws Exception {
        ApiCliente cliente = new ApiCliente(apiUrl);
        String csrfInicial = cliente.obtenerCsrf(false);
        HttpResponse<String> login = cliente.postJson(
                "/api/v1/sesion",
                Map.of("correo", correo, "contrasena", contrasena),
                Map.of(CSRF, csrfInicial));
        assertEquals(200, login.statusCode());
        cliente.csrf(PropietarioApiAceptacionSupport.texto(
                PropietarioApiAceptacionSupport.leerJson(login.body()), "csrfToken"));
        assertNotNull(cliente.cookie("JSESSIONID"));
        return cliente;
    }

    private static String cursorActual(ApiCliente cliente) throws Exception {
        HttpResponse<String> respuesta = cliente.get("/api/v1/operadores?pagina=1");
        assertEquals(200, respuesta.statusCode());
        return PropietarioApiAceptacionSupport.texto(
                PropietarioApiAceptacionSupport.leerJson(respuesta.body()), "cursorEventos");
    }

    private static EmpleadoPreparado crearEmpleado(ApiCliente cliente, Map<String, Object> datos) throws Exception {
        HttpResponse<String> alta = cliente.postJson("/api/v1/empleados", datos,
                Map.of(CSRF, cliente.obtenerCsrf(false), "Idempotency-Key", UUID.randomUUID().toString()));
        assertEquals(201, alta.statusCode());
        String id = PropietarioApiAceptacionSupport.texto(
                PropietarioApiAceptacionSupport.leerJson(alta.body()), "idTexto");
        HttpResponse<String> detalle = cliente.get("/api/v1/empleados/" + id);
        assertEquals(200, detalle.statusCode());
        String revision = detalle.headers().firstValue("ETag").orElseThrow();
        return new EmpleadoPreparado(id, revision);
    }

    private static HttpResponse<String> promocionar(ApiCliente cliente, EmpleadoPreparado empleado, String clave)
            throws Exception {
        return cliente.postJson("/api/v1/empleados/" + empleado.id() + "/operador/promocion", Map.of(),
                Map.of(CSRF, cliente.obtenerCsrf(false), "If-Match", empleado.revision(),
                        "Idempotency-Key", clave));
    }

    private static FlujoEventos abrirFlujo(URI apiUrl, String cookie, String cursor) throws Exception {
        String query = URLEncoder.encode(cursor, StandardCharsets.UTF_8);
        HttpRequest.Builder solicitud = HttpRequest.newBuilder(
                        apiUrl.resolve(EVENTOS + "?despues=" + query))
                .timeout(Duration.ofSeconds(40))
                .header("Accept", "text/event-stream")
                .GET();
        if (cookie != null) solicitud.header("Cookie", "JSESSIONID=" + cookie);
        return new FlujoEventos(CLIENTE_HTTP.send(solicitud.build(), HttpResponse.BodyHandlers.ofInputStream()));
    }

    private static SseEvento leerEventoNoHeartbeat(
            ExecutorService lector, FlujoEventos flujo, Duration limite) throws Exception {
        long vencimiento = System.nanoTime() + limite.toNanos();
        while (true) {
            long restante = vencimiento - System.nanoTime();
            if (restante <= 0) throw new TimeoutException("El stream no entregó el evento esperado a tiempo.");
            Future<SseEvento> lectura = lector.submit(flujo::leerEvento);
            SseEvento evento = lectura.get(restante, TimeUnit.NANOSECONDS);
            if (!EVENTO_HEARTBEAT.equals(evento.evento())) return evento;
        }
    }

    private static List<SseEvento> leerEventosHastaCursor(
            ExecutorService lector,
            FlujoEventos flujo,
            String cursorAnterior,
            String cursorObjetivo,
            Duration limite) throws Exception {
        long vencimiento = System.nanoTime() + limite.toNanos();
        long secuenciaEsperada = secuencia(cursorAnterior) + 1;
        List<SseEvento> eventos = new ArrayList<>();
        while (true) {
            long restante = vencimiento - System.nanoTime();
            if (restante <= 0) throw new TimeoutException("No se reprodujo el cursor SSE esperado.");
            SseEvento evento = leerEventoNoHeartbeat(lector, flujo, Duration.ofNanos(restante));
            assertTrue(evento.id().startsWith(epoca(cursorAnterior) + ":"));
            assertEquals(secuenciaEsperada++, secuencia(evento.id()),
                    "El replay debe conservar el orden y la secuencia de los eventos.");
            eventos.add(evento);
            if (cursorObjetivo.equals(evento.id())) return List.copyOf(eventos);
            assertTrue(secuencia(evento.id()) < secuencia(cursorObjetivo),
                    "El stream debe alcanzar el cursor solicitado sin saltarlo.");
        }
    }

    private static String epoca(String cursor) {
        int separador = cursor.lastIndexOf(':');
        assertTrue(separador > 0);
        return cursor.substring(0, separador);
    }

    private static long secuencia(String cursor) {
        int separador = cursor.lastIndexOf(':');
        assertTrue(separador > 0);
        return Long.parseLong(cursor.substring(separador + 1));
    }

    private static void assertFalseContiene(String texto, String valor) {
        assertTrue(!texto.contains(valor), "La invalidación SSE no debe exponer datos personales.");
    }

    private static final class FlujoEventos implements AutoCloseable {

        private final HttpResponse<InputStream> respuesta;
        private final BufferedReader lector;

        private FlujoEventos(HttpResponse<InputStream> respuesta) {
            this.respuesta = respuesta;
            this.lector = new BufferedReader(new InputStreamReader(respuesta.body(), StandardCharsets.UTF_8));
        }

        private HttpResponse<InputStream> respuesta() {
            return respuesta;
        }

        private String tipoContenido() {
            return respuesta.headers().firstValue("Content-Type").orElse("").toLowerCase(java.util.Locale.ROOT);
        }

        private SseEvento leerEvento() throws IOException {
            String id = "";
            String nombre = "message";
            StringBuilder datos = new StringBuilder();
            String linea;
            while ((linea = lector.readLine()) != null) {
                if (linea.isEmpty()) {
                    if (!id.isEmpty() || !datos.isEmpty() || !"message".equals(nombre)) {
                        return new SseEvento(id, nombre, datos.toString());
                    }
                    continue;
                }
                if (linea.startsWith(":")) continue;
                if (linea.startsWith("id:")) id = linea.substring(3).stripLeading();
                else if (linea.startsWith("event:")) nombre = linea.substring(6).stripLeading();
                else if (linea.startsWith("data:")) {
                    if (!datos.isEmpty()) datos.append('\n');
                    datos.append(linea.substring(5).stripLeading());
                }
            }
            throw new EOFException("El servidor cerró el stream antes del siguiente evento.");
        }

        @Override
        public void close() throws IOException {
            lector.close();
        }
    }

    private record SseEvento(String id, String evento, String datos) {
    }

    private record EmpleadoPreparado(String id, String revision) {
    }
}
