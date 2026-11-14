package mx.smartparking.ownerconsole.servicio;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Stub HTTP local con datos sintéticos y apagado automático al terminar la prueba. */
final class ApiPropietarioSintetica implements AutoCloseable {

    private static final ObjectMapper JSON = new ObjectMapper();

    final AtomicInteger consultasPanel = new AtomicInteger();
    final AtomicInteger consultasEstado = new AtomicInteger();
    final AtomicInteger mutacionesNombre = new AtomicInteger();
    final AtomicInteger mutacionesDatos = new AtomicInteger();
    final AtomicInteger iniciosSesion = new AtomicInteger();
    final AtomicInteger consultasSesion = new AtomicInteger();
    final AtomicReference<String> respuestaConsultaSesion =
            new AtomicReference<>("{\"autenticada\":false}");
    final AtomicReference<String> respuestaInicioSesion = new AtomicReference<>();
    final AtomicReference<String> cookieUltimoInicio = new AtomicReference<>("");
    final AtomicReference<String> cuerpoDatos = new AtomicReference<>("");
    final AtomicReference<String> ifMatchDatos = new AtomicReference<>("");
    final AtomicReference<String> csrfDatos = new AtomicReference<>("");
    final AtomicReference<String> etiquetaTipoActualizada = new AtomicReference<>("");

    private final HttpServer servidor;
    private final ExecutorService ejecutores = Executors.newCachedThreadPool(tarea -> {
        Thread hilo = new Thread(tarea, "owner-console-test-api");
        hilo.setDaemon(true);
        return hilo;
    });
    private volatile String tipo = "MIXTO";
    private volatile String modo = "INTERVALO_DIARIO";
    private volatile String zona = "America/Mexico_City";
    private volatile String apertura = "09:00";
    private volatile String cierre = "21:00";
    private volatile long revision = 4;

    ApiPropietarioSintetica() throws IOException {
        servidor = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        servidor.setExecutor(ejecutores);
        servidor.createContext("/", this::responder);
        servidor.start();
    }

    URI uri() {
        return URI.create("http://127.0.0.1:" + servidor.getAddress().getPort() + "/");
    }

    private void responder(HttpExchange intercambio) throws IOException {
        String ruta = intercambio.getRequestURI().getPath();
        try {
            if ("GET".equals(intercambio.getRequestMethod()) && "/api/v1/panel".equals(ruta)) {
                consultasPanel.incrementAndGet();
                intercambio.getResponseHeaders().set("ETag", "\"" + revision + "\"");
                enviar(intercambio, 200, jsonPanel());
            } else if ("GET".equals(intercambio.getRequestMethod())
                    && "/api/v1/configuracion/estado".equals(ruta)) {
                consultasEstado.incrementAndGet();
                enviar(intercambio, 503,
                        "{\"codigo\":\"SERVICIO_NO_DISPONIBLE\",\"mensaje\":\"API no disponible en el stub\"}");
            } else if ("GET".equals(intercambio.getRequestMethod()) && "/api/v1/csrf".equals(ruta)) {
                enviar(intercambio, 200, "{\"token\":\"token-sintetico\"}");
            } else if ("GET".equals(intercambio.getRequestMethod()) && "/api/v1/sesion".equals(ruta)) {
                consultasSesion.incrementAndGet();
                enviar(intercambio, 200, respuestaConsultaSesion.get());
            } else if ("PATCH".equals(intercambio.getRequestMethod())
                    && "/api/v1/estacionamiento/datos".equals(ruta)) {
                actualizarDatos(intercambio);
            } else if ("PATCH".equals(intercambio.getRequestMethod())
                    && "/api/v1/estacionamiento".equals(ruta)) {
                mutacionesNombre.incrementAndGet();
                intercambio.getRequestBody().readAllBytes();
                enviar(intercambio, 400,
                        "{\"codigo\":\"OPERACION_NO_COMPLETADA\",\"mensaje\":\"El nombre sintético fue rechazado.\"}");
            } else if ("POST".equals(intercambio.getRequestMethod()) && "/api/v1/sesion".equals(ruta)) {
                iniciosSesion.incrementAndGet();
                intercambio.getRequestBody().readAllBytes();
                cookieUltimoInicio.set(intercambio.getRequestHeaders().getFirst("Cookie"));
                if (!"token-sintetico".equals(intercambio.getRequestHeaders().getFirst("X-CSRF-TOKEN"))) {
                    enviar(intercambio, 403, "{\"error\":\"Token sintético no válido\"}");
                } else if (respuestaInicioSesion.get() == null) {
                    enviar(intercambio, 401, "{\"error\":\"No autorizado\"}");
                } else {
                    intercambio.getResponseHeaders().add(
                            "Set-Cookie", "OWNERSESSION=sesion-sintetica; Path=/; HttpOnly");
                    enviar(intercambio, 200, respuestaInicioSesion.get());
                }
            } else {
                enviar(intercambio, 404, "{\"error\":\"No encontrado\"}");
            }
        } catch (Throwable error) {
            if (intercambio.getResponseCode() < 0) {
                enviar(intercambio, 500, "{\"error\":\"Error en API sintética\"}");
            }
        } finally {
            intercambio.close();
        }
    }

    private void actualizarDatos(HttpExchange intercambio) throws IOException {
        mutacionesDatos.incrementAndGet();
        cuerpoDatos.set(new String(intercambio.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
        ifMatchDatos.set(intercambio.getRequestHeaders().getFirst("If-Match"));
        csrfDatos.set(intercambio.getRequestHeaders().getFirst("X-CSRF-TOKEN"));
        JsonNode cuerpo = JSON.readTree(cuerpoDatos.get());
        tipo = cuerpo.path("tipo").asText();
        JsonNode horario = cuerpo.path("horario");
        modo = horario.path("modo").asText();
        zona = horario.path("zonaHoraria").asText();
        apertura = horario.path("horaApertura").isNull() ? null : horario.path("horaApertura").asText();
        cierre = horario.path("horaCierre").isNull() ? null : horario.path("horaCierre").asText();
        revision++;
        etiquetaTipoActualizada.set(switch (tipo) {
            case "PUBLICO" -> "Público";
            case "PRIVADO" -> "Privado";
            default -> "Mixto";
        });
        intercambio.getResponseHeaders().set("ETag", "\"" + revision + "\"");
        enviar(intercambio, 200, jsonPanel());
    }

    private String jsonPanel() {
        String horaAperturaJson = apertura == null ? "null" : "\"" + apertura + "\"";
        String horaCierreJson = cierre == null ? "null" : "\"" + cierre + "\"";
        return "{\"revision\":" + revision
                + ",\"revisionPropietario\":3,\"propietario\":{\"nombres\":\"Dueña\","
                + "\"apellidoPaterno\":\"Sintética\",\"apellidoMaterno\":null,"
                + "\"correo\":\"duena@example.test\"},\"estacionamiento\":{"
                + "\"id\":\"estacionamiento-sintetico\",\"nombre\":\"AAA\","
                + "\"tipo\":\"" + tipo + "\",\"horario\":{\"modo\":\"" + modo
                + "\",\"zonaHoraria\":\"" + zona + "\",\"horaApertura\":" + horaAperturaJson
                + ",\"horaCierre\":" + horaCierreJson + "}}}";
    }

    private void enviar(HttpExchange intercambio, int estado, String cuerpo) throws IOException {
        byte[] bytes = cuerpo.getBytes(StandardCharsets.UTF_8);
        intercambio.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        intercambio.sendResponseHeaders(estado, bytes.length);
        intercambio.getResponseBody().write(bytes);
    }

    @Override
    public void close() {
        servidor.stop(0);
        ejecutores.shutdownNow();
    }
}
