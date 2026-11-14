package mx.smartparking.api.integracion;

import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.baseUrlOptIn;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.leerJson;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.texto;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

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
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import mx.smartparking.api.integracion.ApiCliente;
import org.junit.jupiter.api.Test;

/** Aceptación HTTP real del límite SSE, ACK de heartbeat y expiración de una suscripción. */
class EmpleadosSseCancelacionAceptacionTest {

    private static final String RUTA_SESION = "/api/v1/sesion";
    private static final String RUTA_EMPLEADOS = "/api/v1/empleados?pagina=1";
    private static final String RUTA_EVENTOS = "/api/v1/eventos/administracion";
    private static final String RUTA_ACK = "/api/v1/eventos/administracion/heartbeat";
    private static final String CABECERA_CSRF = "X-CSRF-TOKEN";
    private static final String EVENTO_HEARTBEAT = "empleado.heartbeat";
    private static final int MAXIMO_STREAMS = 5;
    private static final long ESPERA_INICIAL_MS = TimeUnit.SECONDS.toMillis(10);
    private static final long ESPERA_EXPIRACION_MS = TimeUnit.SECONDS.toMillis(30);
    private static final String TIPO_EVENTOS = "text/event-stream";
    private static final Pattern PATRON_SUSCRIPCION =
            Pattern.compile("\\\"suscripcionId\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"");
    private static final Pattern PATRON_SECUENCIA = Pattern.compile("\\\"secuencia\\\"\\s*:\\s*(\\d+)");
    private static final HttpClient CLIENTE = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(4))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();

    @Test
    void limitaCincoStreamsYExpiraElQueNoConfirmaHeartbeat() throws Exception {
        URI base = baseUrlOptIn();
        String correo = System.getenv("TEST_OWNER_EMAIL");
        String contrasena = System.getenv("TEST_OWNER_PASSWORD");
        assumeTrue(correo != null && !correo.isBlank() && contrasena != null && !contrasena.isBlank(),
                "La aceptación requiere credenciales sintéticas del propietario.");

        Sesion sesion = iniciarSesion(base, correo, contrasena);
        String cursorInicial = obtenerCursor(base, sesion.cookie());
        List<Stream> streams = new ArrayList<>();
        List<Future<?>> tareas = new ArrayList<>();
        List<AtomicInteger> confirmaciones = new ArrayList<>();
        ExecutorService executor = Executors.newFixedThreadPool(6);
        AtomicBoolean detener = new AtomicBoolean();

        try {
            for (int indice = 0; indice < MAXIMO_STREAMS; indice++) {
                Stream stream = abrirStream(base, sesion.cookie(), cursorInicial);
                streams.add(stream);
                assertEquals(200, stream.respuesta().statusCode(),
                        "Los primeros cinco streams con ACK deben permanecer abiertos.");
                assertTrue(stream.tipoContenido().startsWith(TIPO_EVENTOS));
                confirmarHeartbeat(base, sesion, stream, leerEventoConLimite(executor, stream));
            }

            assertEquals(cursorInicial, obtenerCursor(base, sesion.cookie()),
                    "Los ACK de heartbeat no deben avanzar el cursor de negocio.");

            try (Stream exceso = abrirStream(base, sesion.cookie(), cursorInicial)) {
                assertEquals(429, exceso.respuesta().statusCode(),
                        "El sexto stream simultáneo de la sesión debe recibir 429.");
                assertFalse(exceso.tipoContenido().contains("json"));
                assertEquals(0, exceso.respuesta().body().readAllBytes().length,
                        "El rechazo del handshake SSE debe tener un cuerpo vacío.");
            }

            for (int indice = 1; indice < MAXIMO_STREAMS; indice++) {
                Stream streamActivo = streams.get(indice);
                AtomicInteger cantidad = new AtomicInteger(1);
                confirmaciones.add(cantidad);
                tareas.add(executor.submit(() -> mantenerConfirmaciones(
                        base, sesion, streamActivo, cantidad, detener)));
            }

            Stream sinConfirmacion = streams.get(0);
            long inicioExpiracion = System.nanoTime();
            Future<Boolean> cierre = executor.submit(() -> esperarCierre(sinConfirmacion));
            tareas.add(cierre);
            assertTrue(cierre.get(ESPERA_EXPIRACION_MS, TimeUnit.MILLISECONDS),
                    "El stream sin ACK debe cerrarse al vencer su concesión.");
            assertElapsedAtMost(inicioExpiracion, ESPERA_EXPIRACION_MS,
                    "La suscripción sin ACK debe expirar dentro de 30 segundos.");

            esperarConfirmacionesActivas(confirmaciones);
            long inicioReemplazo = System.nanoTime();
            Stream reemplazo = abrirStream(base, sesion.cookie(), cursorInicial);
            streams.add(reemplazo);
            assertEquals(200, reemplazo.respuesta().statusCode(),
                    "El cupo expirado debe aceptar un stream de reemplazo.");
            confirmarHeartbeat(base, sesion, reemplazo, leerEventoConLimite(executor, reemplazo));
            assertElapsedAtMost(inicioReemplazo, ESPERA_EXPIRACION_MS,
                    "El stream de reemplazo debe abrirse dentro de 30 segundos.");
            assertEquals(cursorInicial, obtenerCursor(base, sesion.cookie()),
                    "Los heartbeats y sus ACK no deben alterar el cursor SSE de negocio.");
        } finally {
            detener.set(true);
            tareas.forEach(tarea -> tarea.cancel(true));
            cerrarStreams(streams);
            executor.shutdownNow();
            executor.awaitTermination(3, TimeUnit.SECONDS);
        }
    }

    private static Sesion iniciarSesion(URI base, String correo, String contrasena) throws Exception {
        ApiCliente api = new ApiCliente(base);
        String csrf = api.obtenerCsrf(false);
        var respuesta = api.postJson(
                RUTA_SESION,
                Map.of("correo", correo, "contrasena", contrasena),
                Map.of(CABECERA_CSRF, csrf));
        assertEquals(200, respuesta.statusCode(), "La sesión sintética debe autenticarse como DUENO.");
        String csrfRenovado = texto(leerJson(respuesta.body()), "csrfToken");
        api.csrf(csrfRenovado);
        String cookie = api.cookie("JSESSIONID");
        assertNotNull(cookie, "La autenticación debe emitir una cookie de sesión.");
        return new Sesion(cookie, csrfRenovado);
    }

    private static String obtenerCursor(URI base, String cookie) throws Exception {
        HttpRequest solicitud = HttpRequest.newBuilder(base.resolve(RUTA_EMPLEADOS))
                .timeout(Duration.ofSeconds(5))
                .header("Cookie", "JSESSIONID=" + cookie)
                .GET()
                .build();
        HttpResponse<String> respuesta = CLIENTE.send(
                solicitud, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        assertEquals(200, respuesta.statusCode(), "El directorio debe devolver su cursor actual.");
        return texto(leerJson(respuesta.body()), "cursorEventos");
    }

    private static Stream abrirStream(URI base, String cookie, String cursor) throws Exception {
        String query = "?despues=" + URLEncoder.encode(cursor, StandardCharsets.UTF_8);
        HttpRequest solicitud = HttpRequest.newBuilder(base.resolve(RUTA_EVENTOS + query))
                .timeout(Duration.ofMillis(ESPERA_EXPIRACION_MS + TimeUnit.SECONDS.toMillis(5)))
                .header("Accept", TIPO_EVENTOS)
                .header("Cookie", "JSESSIONID=" + cookie)
                .GET()
                .build();
        return new Stream(CLIENTE.send(solicitud, HttpResponse.BodyHandlers.ofInputStream()));
    }

    private static SseEvento leerEventoConLimite(ExecutorService executor, Stream stream) throws Exception {
        Future<SseEvento> lectura = executor.submit(stream::leerEvento);
        return lectura.get(ESPERA_INICIAL_MS, TimeUnit.MILLISECONDS);
    }

    private static void confirmarHeartbeat(URI base, Sesion sesion, Stream stream, SseEvento evento)
            throws Exception {
        assertEquals(EVENTO_HEARTBEAT, evento.nombre(),
                "El servidor debe confirmar la suscripción con el evento de heartbeat.");
        assertFalse(evento.tieneId(), "El heartbeat no debe emitir un SSE id ni mover Last-Event-ID.");
        Confirmacion confirmacion = leerConfirmacion(evento.datos());
        String suscripcionId = confirmacion.suscripcionId();
        long secuencia = confirmacion.secuencia();
        assertFalse(suscripcionId.isBlank(), "El heartbeat debe identificar su suscripción.");
        assertTrue(secuencia > stream.secuencia(), "La secuencia del heartbeat debe avanzar.");
        if (stream.suscripcionId() != null) {
            assertEquals(stream.suscripcionId(), suscripcionId,
                    "La secuencia debe pertenecer a la suscripción que la emitió.");
        }

        byte[] cuerpo = ("{\"suscripcionId\":\"" + suscripcionId
                + "\",\"secuencia\":" + secuencia + "}").getBytes(StandardCharsets.UTF_8);
        HttpRequest solicitud = HttpRequest.newBuilder(base.resolve(RUTA_ACK))
                .timeout(Duration.ofSeconds(5))
                .header("Content-Type", "application/json")
                .header(CABECERA_CSRF, sesion.csrf())
                .header("Cookie", "JSESSIONID=" + sesion.cookie())
                .POST(HttpRequest.BodyPublishers.ofByteArray(cuerpo))
                .build();
        HttpResponse<byte[]> respuesta = CLIENTE.send(solicitud, HttpResponse.BodyHandlers.ofByteArray());
        assertEquals(204, respuesta.statusCode(), "El BFF/API debe aceptar el ACK de heartbeat.");
        assertEquals(0, respuesta.body().length, "El ACK debe responder 204 sin cuerpo.");
        stream.identidad(suscripcionId, secuencia);
    }

    private static Confirmacion leerConfirmacion(String datosJson) {
        Matcher coincidenciaId = PATRON_SUSCRIPCION.matcher(datosJson);
        Matcher coincidenciaSecuencia = PATRON_SECUENCIA.matcher(datosJson);
        assertTrue(coincidenciaId.find(), "El heartbeat debe incluir suscripcionId.");
        assertTrue(coincidenciaSecuencia.find(), "El heartbeat debe incluir secuencia.");
        String suscripcionId = UUID.fromString(coincidenciaId.group(1)).toString();
        long secuencia = Long.parseLong(coincidenciaSecuencia.group(1));
        return new Confirmacion(suscripcionId, secuencia);
    }

    private static void mantenerConfirmaciones(
            URI base,
            Sesion sesion,
            Stream stream,
            AtomicInteger cantidad,
            AtomicBoolean detener) {
        try {
            while (!detener.get() && !Thread.currentThread().isInterrupted()) {
                SseEvento evento = stream.leerEvento();
                if (evento.cerrado()) {
                    if (!detener.get()) throw new IOException("El stream activo se cerró inesperadamente.");
                    return;
                }
                if (EVENTO_HEARTBEAT.equals(evento.nombre())) {
                    confirmarHeartbeat(base, sesion, stream, evento);
                    cantidad.incrementAndGet();
                }
            }
        } catch (Exception excepcion) {
            if (!detener.get()) {
                throw new IllegalStateException("No se pudo confirmar el heartbeat activo.", excepcion);
            }
            Thread.currentThread().interrupt();
        }
    }

    private static void esperarConfirmacionesActivas(List<AtomicInteger> confirmaciones) throws InterruptedException {
        long limite = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
        while (System.nanoTime() < limite
                && confirmaciones.stream().anyMatch(cantidad -> cantidad.get() < 2)) {
            Thread.sleep(50);
        }
        for (AtomicInteger cantidad : confirmaciones) {
            assertTrue(cantidad.get() >= 2,
                    "Cada uno de los otros cuatro streams debe confirmar un heartbeat posterior.");
        }
    }

    private static boolean esperarCierre(Stream stream) throws IOException {
        while (true) {
            if (stream.leerEvento().cerrado()) return true;
        }
    }

    private static void assertElapsedAtMost(long inicio, long limiteMs, String mensaje) {
        long transcurrido = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - inicio);
        assertTrue(transcurrido <= limiteMs, mensaje + " Tiempo observado: " + transcurrido + " ms.");
    }

    private static void cerrarStreams(List<Stream> streams) {
        for (Stream stream : streams) {
            try {
                stream.close();
            } catch (IOException ignored) {
                // Cerrar un stream vencido puede reportar una desconexión ya iniciada por el servidor.
            }
        }
    }

    private record Sesion(String cookie, String csrf) {}

    private record Confirmacion(String suscripcionId, long secuencia) {}

    private record SseEvento(String nombre, String id, boolean tieneId, String datos, boolean cerrado) {}

    private static final class Stream implements AutoCloseable {

        private final HttpResponse<InputStream> respuesta;
        private final BufferedReader lector;
        private String suscripcionId;
        private long secuencia;

        private Stream(HttpResponse<InputStream> respuesta) {
            this.respuesta = respuesta;
            lector = new BufferedReader(new InputStreamReader(respuesta.body(), StandardCharsets.UTF_8));
        }

        private HttpResponse<InputStream> respuesta() {
            return respuesta;
        }

        private String tipoContenido() {
            return respuesta.headers().firstValue("Content-Type").orElse("").toLowerCase(Locale.ROOT);
        }

        private String suscripcionId() {
            return suscripcionId;
        }

        private long secuencia() {
            return secuencia;
        }

        private void identidad(String id, long valorSecuencia) {
            suscripcionId = id;
            secuencia = valorSecuencia;
        }

        private SseEvento leerEvento() throws IOException {
            String nombre = "message";
            String id = "";
            boolean tieneId = false;
            StringBuilder datos = new StringBuilder();
            boolean tieneCampo = false;
            while (true) {
                String linea = lector.readLine();
                if (linea == null) return new SseEvento(nombre, id, tieneId, datos.toString(), true);
                if (linea.isEmpty()) {
                    if (!tieneCampo) continue;
                    return new SseEvento(nombre, id, tieneId, datos.toString(), false);
                }
                if (linea.startsWith(":")) continue;
                int separador = linea.indexOf(':');
                String campo = separador < 0 ? linea : linea.substring(0, separador);
                String valor = separador < 0 ? "" : linea.substring(separador + 1).replaceFirst("^ ", "");
                if ("event".equals(campo)) nombre = valor;
                else if ("id".equals(campo)) {
                    id = valor;
                    tieneId = true;
                } else if ("data".equals(campo)) {
                    if (!datos.isEmpty()) datos.append('\n');
                    datos.append(valor);
                }
                tieneCampo = true;
            }
        }

        @Override
        public void close() throws IOException {
            lector.close();
        }
    }
}
