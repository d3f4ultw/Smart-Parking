package mx.smartparking.api.integracion;

import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.baseUrlOptIn;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.clave;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.configuracion;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.leerJson;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.numero;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.texto;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.BufferedReader;
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
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import mx.smartparking.api.integracion.ApiCliente;

/** Aceptación HTTP real de paginación, concurrencia y notificaciones del directorio. */
class EmpleadosApiSseAceptacionTest {

    private static final String CSRF = "X-CSRF-TOKEN";
    private static final String SESION = "/api/v1/sesion";
    private static final String EVENTO_DIRECTORIO = "empleado.directorio.actualizado";
    private static final String EVENTO_RESINCRONIZAR = "administracion.directorio.resincronizar";
    private static final HttpClient CLIENTE_STREAM = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(4))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();

    @Test
    void validaDirectorioIdempotenciaRevisionYDosStreamsReales() throws Exception {
        URI base = baseUrlOptIn();
        String sufijo = UUID.randomUUID().toString().replace("-", "");
        String correo = valorDePrueba("TEST_OWNER_EMAIL", "empleados." + sufijo + "@example.test");
        String contrasena = valorDePrueba("TEST_OWNER_PASSWORD", "acceso de prueba robusto 2026 " + sufijo + "!");
        ApiCliente sesionA = new ApiCliente(base);
        ApiCliente anonimo = new ApiCliente(base);

        assertEquals(401, anonimo.get("/api/v1/empleados").statusCode(),
                "El directorio requiere una sesión de propietario.");
        assertEquals(401, anonimo.get("/api/v1/eventos/administracion").statusCode(),
                "El stream administrativo requiere una sesión de propietario.");

        String csrfInicial = sesionA.obtenerCsrf(false);
        var configurada = sesionA.post(
                "/api/v1/configuracion/inicial",
                configuracion(correo, contrasena, "administracion prueba 2026 B!", "Estacionamiento de prueba"),
                clave("setup-empleados-" + sufijo),
                csrfInicial);
        assertEquals(201, configurada.statusCode(), "La base desechable debe permitir crear su dueño inicial.");
        String cookieA = iniciarSesion(sesionA, correo, contrasena);

        ApiCliente sesionB = new ApiCliente(base);
        String cookieB = iniciarSesion(sesionB, correo, contrasena);
        assertNotNull(cookieA);
        assertNotNull(cookieB);
        assertNotEquals(cookieA, cookieB, "Las sesiones HTTP deben tener identificadores independientes.");

        Map<String, Object> solicitudInicial = empleado(" Ana 😀 ", " Solís ", "");
        String claveRegistro = clave("alta-empleado-" + sufijo);
        var alta = sesionA.post("/api/v1/empleados", solicitudInicial, claveRegistro, csrf(sesionA));
        assertEquals(201, alta.statusCode(), "El dueño debe poder registrar un empleado.");
        JsonNode recibo = leerJson(alta.body());
        long empleadoId = numero(recibo, "id");
        String codigo = texto(recibo, "codigo");
        assertTrue(empleadoId > 0);
        assertFalse(codigo.isBlank());

        var listadoDespuesAlta = sesionA.get("/api/v1/empleados");
        JsonNode paginaDespuesAlta = leerJson(listadoDespuesAlta.body());
        String cursorDespuesAlta = texto(paginaDespuesAlta, "cursorEventos");
        var replay = sesionA.post(
                "/api/v1/empleados",
                empleado("Ana 😀", "Solís", null),
                claveRegistro,
                csrf(sesionA));
        assertEquals(201, replay.statusCode(), "El retry equivalente debe reproducir el recibo original.");
        assertEquals(empleadoId, numero(leerJson(replay.body()), "id"));
        assertEquals(codigo, texto(leerJson(replay.body()), "codigo"));
        var conflicto = sesionA.post(
                "/api/v1/empleados",
                empleado("Otra persona", "Solís", null),
                claveRegistro,
                csrf(sesionA));
        assertEquals(409, conflicto.statusCode(), "La misma clave no debe aceptar otro contenido.");
        JsonNode paginaTrasReplay = leerJson(sesionA.get("/api/v1/empleados").body());
        assertEquals(1, numero(paginaTrasReplay, "totalRegistros"), "El replay no debe insertar otra fila.");
        assertEquals(cursorDespuesAlta, texto(paginaTrasReplay, "cursorEventos"),
                "El replay y el conflicto no deben publicar invalidaciones.");

        String cursorAntesCarrera = texto(paginaTrasReplay, "cursorEventos");
        String claveCarrera = clave("carrera-empleado-" + sufijo);
        List<HttpResponse<String>> altasConcurrentes = registrarConcurrentemente(
                base, cookieA, csrf(sesionA), empleado("Concurrente", "Clave", null), claveCarrera);
        assertEquals(201, altasConcurrentes.get(0).statusCode());
        assertEquals(201, altasConcurrentes.get(1).statusCode());
        JsonNode reciboConcurrente = leerJson(altasConcurrentes.get(0).body());
        JsonNode reciboConcurrenteRetry = leerJson(altasConcurrentes.get(1).body());
        assertEquals(numero(reciboConcurrente, "id"), numero(reciboConcurrenteRetry, "id"));
        assertEquals(texto(reciboConcurrente, "codigo"), texto(reciboConcurrenteRetry, "codigo"));
        JsonNode paginaTrasCarrera = leerJson(sesionA.get("/api/v1/empleados").body());
        assertEquals(2, numero(paginaTrasCarrera, "totalRegistros"),
                "Dos POST concurrentes con la misma clave deben crear solo un empleado.");
        String cursorTrasCarrera = texto(paginaTrasCarrera, "cursorEventos");
        assertEquals(epoca(cursorAntesCarrera), epoca(cursorTrasCarrera));
        assertEquals(secuencia(cursorAntesCarrera) + 1, secuencia(cursorTrasCarrera),
                "La reserva concurrente debe publicar exactamente una invalidación.");

        for (int indice = 1; indice <= 10; indice++) {
            var respuesta = sesionA.post(
                    "/api/v1/empleados",
                    empleado("Empleado " + indice, "Apellido", null),
                    clave("alta-pagina-" + indice + "-" + sufijo),
                    csrf(sesionA));
            assertEquals(201, respuesta.statusCode(), "Cada alta de prueba debe confirmarse una sola vez.");
        }

        JsonNode paginaUno = leerJson(sesionA.get("/api/v1/empleados?pagina=1").body());
        JsonNode paginaDos = leerJson(sesionA.get("/api/v1/empleados?pagina=2").body());
        JsonNode paginaClamped = leerJson(sesionA.get("/api/v1/empleados?pagina=99").body());
        assertEquals(10, paginaUno.path("items").size());
        assertEquals(2, paginaDos.path("items").size());
        assertEquals(12, numero(paginaUno, "totalRegistros"));
        assertEquals(2, numero(paginaUno, "totalPaginas"));
        assertEquals(2, numero(paginaDos, "pagina"));
        assertEquals(2, numero(paginaClamped, "pagina"), "La ruta debe normalizar la página fuera de rango.");
        assertEquals(empleadoId, numero(paginaUno.path("items").get(0), "id"));
        assertEquals("Ana 😀", texto(paginaUno.path("items").get(0), "nombres"));
        assertEquals("Solís", texto(paginaUno.path("items").get(0), "primerApellido"));
        assertTrue(paginaUno.path("items").get(0).path("segundoApellido").isNull());
        long ultimoIdPrimeraPagina = numero(paginaUno.path("items").get(9), "id");
        long primerIdSegundaPagina = numero(paginaDos.path("items").get(0), "id");
        assertTrue(ultimoIdPrimeraPagina < primerIdSegundaPagina, "El orden debe ser estable por id ascendente.");
        assertEquals(400, sesionA.get("/api/v1/empleados?pagina=").statusCode(),
                "Una página vacía debe rechazarse y no convertirse en página uno.");

        JsonNode empleado = buscarEmpleado(paginaUno, empleadoId);
        long revisionInicial = numero(empleado, "revision");
        assertTrue(revisionInicial > 0);
        String estadoUrl = "/api/v1/empleados/" + empleadoId + "/estado";
        String cursorAntesNoOp = texto(paginaUno, "cursorEventos");
        var noOp = sesionA.patch(estadoUrl, Map.of("estado", "ACTIVO"), etag(revisionInicial),
                clave("no-op-empleado-" + sufijo));
        assertEquals(200, noOp.statusCode());
        assertEquals(revisionInicial, numero(leerJson(noOp.body()), "revision"));
        JsonNode paginaTrasNoOp = leerJson(sesionA.get("/api/v1/empleados").body());
        assertEquals(cursorAntesNoOp, texto(paginaTrasNoOp, "cursorEventos"),
                "La transición a un estado igual no debe publicar SSE.");

        String cursorBase = texto(paginaTrasNoOp, "cursorEventos");
        try (Stream streamA = abrirStream(base, cookieA, cursorBase, null);
                Stream streamB = abrirStream(base, cookieB, "cursor-invalido", cursorBase)) {
            var cambio = sesionA.patch(
                    estadoUrl,
                    Map.of("estado", "INACTIVO"),
                    etag(revisionInicial),
                    clave("cambio-empleado-" + sufijo));
            assertEquals(200, cambio.statusCode());
            JsonNode empleadoInactivo = leerJson(cambio.body());
            assertEquals("INACTIVO", texto(empleadoInactivo, "estado"));
            assertEquals(revisionInicial + 1, numero(empleadoInactivo, "revision"));
            String eventoA = leerEventoConLimite(streamA);
            String eventoB = leerEventoConLimite(streamB);
            assertEquals(EVENTO_DIRECTORIO, campoEvento(eventoA, "event"));
            assertEquals(EVENTO_DIRECTORIO, campoEvento(eventoB, "event"));
            assertEquals(campoEvento(eventoA, "id"), campoEvento(eventoB, "id"));
            assertFalse(eventoB.contains("Ana"), "La invalidación no debe incluir datos personales.");
            assertFalse(eventoB.contains("Solís"), "La invalidación no debe incluir apellidos.");
        }

        JsonNode paginaInactiva = leerJson(sesionA.get("/api/v1/empleados").body());
        String cursorCambio = texto(paginaInactiva, "cursorEventos");
        try (Stream replaySse = abrirStream(base, cookieB, "cursor-invalido", cursorBase)) {
            String replayEvento = leerEventoConLimite(replaySse);
            assertEquals(EVENTO_DIRECTORIO, campoEvento(replayEvento, "event"));
            assertEquals(cursorCambio, campoEvento(replayEvento, "id"), "El cursor previo debe reproducir el cambio.");
        }
        try (Stream resincronizacion = abrirStream(base, cookieB, "cursor-invalido", null)) {
            String eventoActual = leerEventoConLimite(resincronizacion);
            assertEquals(EVENTO_RESINCRONIZAR, campoEvento(eventoActual, "event"));
            assertEquals(cursorCambio, campoEvento(eventoActual, "id"),
                    "Un cursor ajeno o inválido debe recibir el cursor actual para resincronizar.");
            assertFalse(eventoActual.contains("Ana"), "La resincronización no debe revelar nombres.");
        }

        var obsoleto = sesionA.patch(
                estadoUrl,
                Map.of("estado", "ACTIVO"),
                etag(revisionInicial),
                clave("stale-empleado-" + sufijo));
        assertEquals(412, obsoleto.statusCode(), "Una revisión obsoleta debe rechazarse aun si coincide el destino.");
        JsonNode paginaTrasObsoleto = leerJson(sesionA.get("/api/v1/empleados").body());
        assertEquals(cursorCambio, texto(paginaTrasObsoleto, "cursorEventos"),
                "El PATCH obsoleto no debe publicar eventos adicionales.");
        assertEquals(revisionInicial + 1, numero(buscarEmpleado(paginaTrasObsoleto, empleadoId), "revision"));
    }

    private static String iniciarSesion(ApiCliente api, String correo, String contrasena) throws Exception {
        String token = api.obtenerCsrf(false);
        var respuesta = api.postJson(SESION, Map.of("correo", correo, "contrasena", contrasena), Map.of(CSRF, token));
        assertEquals(200, respuesta.statusCode(), "Las dos sesiones deben autenticarse como DUENO.");
        api.csrf(texto(leerJson(respuesta.body()), "csrfToken"));
        return api.cookie("JSESSIONID");
    }

    private static String csrf(ApiCliente api) throws Exception {
        return api.obtenerCsrf(false);
    }

    private static String valorDePrueba(String variable, String valorPredeterminado) {
        String valor = System.getenv(variable);
        return valor == null || valor.isBlank() ? valorPredeterminado : valor;
    }

    private static List<HttpResponse<String>> registrarConcurrentemente(
            URI base, String cookie, String csrf, Map<String, Object> cuerpo, String clave) throws Exception {
        ExecutorService trabajadores = Executors.newFixedThreadPool(2);
        CountDownLatch inicio = new CountDownLatch(1);
        try {
            Future<HttpResponse<String>> primero = trabajadores.submit(() -> {
                inicio.await();
                return enviarAlta(base, cookie, csrf, cuerpo, clave);
            });
            Future<HttpResponse<String>> segundo = trabajadores.submit(() -> {
                inicio.await();
                return enviarAlta(base, cookie, csrf, cuerpo, clave);
            });
            inicio.countDown();
            return List.of(primero.get(20, TimeUnit.SECONDS), segundo.get(20, TimeUnit.SECONDS));
        } finally {
            trabajadores.shutdownNow();
        }
    }

    private static HttpResponse<String> enviarAlta(
            URI base, String cookie, String csrf, Map<String, Object> cuerpo, String clave)
            throws IOException, InterruptedException {
        HttpRequest solicitud = HttpRequest.newBuilder(base.resolve("/api/v1/empleados"))
                .timeout(Duration.ofSeconds(12))
                .header("Accept", "application/json")
                .header("Content-Type", "application/json")
                .header("Cookie", "JSESSIONID=" + cookie)
                .header(CSRF, csrf)
                .header("Idempotency-Key", clave)
                .POST(HttpRequest.BodyPublishers.ofString(ApiCliente.serializar(cuerpo)))
                .build();
        return CLIENTE_STREAM.send(solicitud, HttpResponse.BodyHandlers.ofString());
    }

    private static Map<String, Object> empleado(String nombres, String primerApellido, String segundoApellido) {
        Map<String, Object> cuerpo = new HashMap<>();
        cuerpo.put("nombres", nombres);
        cuerpo.put("primerApellido", primerApellido);
        cuerpo.put("segundoApellido", segundoApellido);
        return cuerpo;
    }

    private static JsonNode buscarEmpleado(JsonNode pagina, long id) {
        for (JsonNode item : pagina.path("items")) {
            if (numero(item, "id") == id) {
                return item;
            }
        }
        throw new AssertionError("El directorio debe contener el empleado solicitado.");
    }

    private static String etag(long revision) {
        return "\"" + revision + "\"";
    }

    private static String epoca(String cursor) {
        return cursor.substring(0, cursor.lastIndexOf(':'));
    }

    private static long secuencia(String cursor) {
        return Long.parseLong(cursor.substring(cursor.lastIndexOf(':') + 1));
    }

    private static Stream abrirStream(URI base, String cookie, String cursorQuery, String cursorHeader)
            throws IOException, InterruptedException {
        String query = URLEncoder.encode(cursorQuery, StandardCharsets.UTF_8);
        URI uri = URI.create(base.resolve("/api/v1/eventos/administracion").toString() + "?despues=" + query);
        HttpRequest.Builder solicitud = HttpRequest.newBuilder(uri)
                .header("Accept", "text/event-stream")
                .header("Cookie", "JSESSIONID=" + cookie)
                .GET();
        if (cursorHeader != null) {
            solicitud.header("Last-Event-ID", cursorHeader);
        }
        HttpResponse<InputStream> respuesta = CLIENTE_STREAM.send(solicitud.build(), HttpResponse.BodyHandlers.ofInputStream());
        if (respuesta.statusCode() != 200) {
            respuesta.body().close();
            throw new AssertionError("El stream del dueño debe responder 200, recibió " + respuesta.statusCode());
        }
        assertTrue(respuesta.headers().firstValue("Content-Type").orElse("").startsWith("text/event-stream"));
        return new Stream(respuesta.body(), new BufferedReader(
                new InputStreamReader(respuesta.body(), StandardCharsets.UTF_8)));
    }

    private static String leerEventoConLimite(Stream stream) throws Exception {
        CompletableFuture<String> lectura = CompletableFuture.supplyAsync(() -> {
            try {
                StringBuilder evento = new StringBuilder();
                String linea;
                while ((linea = stream.lector().readLine()) != null) {
                    if (linea.startsWith(":")) {
                        continue;
                    }
                    if (linea.isEmpty()) {
                        String bloque = evento.toString();
                        evento.setLength(0);
                        if (bloque.indexOf("event:") >= 0
                                && !"empleado.heartbeat".equals(campoEvento(bloque, "event"))) {
                            return bloque;
                        }
                        continue;
                    }
                    evento.append(linea).append('\n');
                }
                throw new IOException("El stream terminó antes de entregar una invalidación.");
            } catch (IOException excepcion) {
                throw new IllegalStateException(excepcion);
            }
        });
        try {
            // Un único get limita el tiempo total aunque se ignoren varios heartbeats.
            return lectura.get(8, TimeUnit.SECONDS);
        } catch (TimeoutException excepcion) {
            stream.close();
            throw new AssertionError("El stream debe entregar la invalidación dentro del límite.", excepcion);
        }
    }

    private static String campoEvento(String bloque, String campo) {
        String prefijo = campo + ":";
        return bloque.lines()
                .filter(linea -> linea.startsWith(prefijo))
                .map(linea -> linea.substring(prefijo.length()).strip())
                .findFirst()
                .orElseThrow(() -> new AssertionError("El evento SSE debe incluir " + campo + "."));
    }

    private record Stream(InputStream cuerpo, BufferedReader lector) implements AutoCloseable {
        @Override
        public void close() throws IOException {
            lector.close();
            cuerpo.close();
        }
    }
}
