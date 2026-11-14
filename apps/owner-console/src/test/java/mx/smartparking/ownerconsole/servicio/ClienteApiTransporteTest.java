package mx.smartparking.ownerconsole.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class ClienteApiTransporteTest {

    private final ConcurrentLinkedQueue<Solicitud> solicitudes = new ConcurrentLinkedQueue<>();
    private HttpServer servidor;
    private ExecutorService ejecutor;
    private boolean errorRegistro;
    private volatile boolean sesionCerrada;
    private volatile boolean grantVencido;
    private volatile boolean recuperacionIncompleta;

    @BeforeEach
    void iniciarServidor() throws IOException {
        servidor = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        ejecutor = Executors.newCachedThreadPool();
        servidor.setExecutor(ejecutor);
        servidor.createContext("/", this::responder);
        servidor.start();
    }

    @AfterEach
    void detenerServidor() {
        if (servidor != null) {
            servidor.stop(0);
        }
        if (ejecutor != null) {
            ejecutor.shutdownNow();
        }
    }

    @Test
    void clientesDeSesionYTransferenciaCompartenCookieCsrfYHeadersCondicionales() {
        ClienteApi api = new ClienteApi(uriBase());

        var sesion = api.sesion().iniciarSesion("dueno@example.com", "password-secreto");
        var panel = api.configuracion().consultarPanel();
        var transferencia = api.transferencia().iniciarTransferencia(
                "admin-secreto", panel, "idempotencia-transferencia-123456");

        assertTrue(sesion.autenticada());
        assertEquals("\"7\"", panel.etag());
        assertTrue("grant-temporal".equals(transferencia.grant()));

        List<Solicitud> capturadas = List.copyOf(solicitudes);
        assertEquals(4, capturadas.size());
        assertEquals("/api/v1/csrf", capturadas.get(0).ruta());
        assertEquals("POST", capturadas.get(1).metodo());
        assertTrue("csrf-inicial".equals(capturadas.get(1).csrf()));
        assertTrue(capturadas.get(1).cookie().contains("OWNERSESSION=anonima"));
        assertTrue(capturadas.get(1).cuerpo().contains("\"contrasena\":\"password-secreto\""));

        assertEquals("GET", capturadas.get(2).metodo());
        assertTrue(capturadas.get(2).cookie().contains("OWNERSESSION=autenticada"));
        assertEquals("POST", capturadas.get(3).metodo());
        assertTrue(capturadas.get(3).cookie().contains("OWNERSESSION=autenticada"));
        assertTrue("csrf-sesion".equals(capturadas.get(3).csrf()));
        assertEquals("\"7\"", capturadas.get(3).ifMatch());
        assertEquals("idempotencia-transferencia-123456", capturadas.get(3).idempotencia());
        assertTrue(capturadas.get(3).cuerpo().contains("\"contrasenaAdministrativa\":\"admin-secreto\""));
        assertFalse(capturadas.get(3).cuerpo().contains("grant-temporal"));
    }

    @Test
    void marcaComoInciertoElErrorDeServidorAlRegistrarConfiguracion() {
        errorRegistro = true;

        ClienteApi api = new ClienteApi(uriBase());

        FalloApi error = assertThrows(
                FalloApi.class,
                () -> api.configuracion().registrar(
                        new PayloadConfiguracion("{}"), "idempotencia-registro-123456"));

        assertEquals(500, error.estadoHttp());
        assertTrue(error.respuestaIncierta());
    }

    @Test
    void recuperaYCompletaLaTransferenciaConCsrfGrantEIdempotencia() {
        ClienteApi api = new ClienteApi(uriBase());

        ResultadoTransicion recuperacion = api.transferencia().recuperarTransferencia("clave-administrativa-sintetica");
        assertEquals("TRANSFERENCIA_PENDIENTE", recuperacion.estado());
        assertEquals("transferencia-sintetica", recuperacion.transferenciaId());
        assertEquals("grant-recuperado", recuperacion.grant());
        assertEquals("2026-10-23T21:00:00Z", recuperacion.venceEn());

        ResultadoTransicion finalizacion = api.transferencia().completarTransferencia(
                new PayloadConfiguracion("{\"nombre\":\"Configuración sintética\"}"),
                recuperacion.grant(),
                "idempotencia-finalizacion-sintetica");

        assertEquals("CONFIGURADA", finalizacion.estado());
        assertEquals("ENVIADO", finalizacion.avisoCorreo());
        List<Solicitud> capturadas = List.copyOf(solicitudes);
        assertEquals(3, capturadas.size());
        assertEquals("/api/v1/csrf", capturadas.get(0).ruta());
        assertEquals("POST", capturadas.get(1).metodo());
        assertEquals("/api/v1/transferencia/recuperar", capturadas.get(1).ruta());
        assertEquals("csrf-inicial", capturadas.get(1).csrf());
        assertTrue(capturadas.get(1).cuerpo().contains("\"contrasenaAdministrativa\""));
        assertEquals("POST", capturadas.get(2).metodo());
        assertEquals("/api/v1/transferencia/completar", capturadas.get(2).ruta());
        assertEquals("csrf-inicial", capturadas.get(2).csrf());
        assertEquals("grant-recuperado", capturadas.get(2).grant());
        assertEquals("idempotencia-finalizacion-sintetica", capturadas.get(2).idempotencia());
        assertFalse(capturadas.get(2).cuerpo().contains("grant-recuperado"));
    }

    @Test
    void rechazaUnaRespuestaDeRecuperacionSinGrant() {
        recuperacionIncompleta = true;

        FalloApi error = assertThrows(
                FalloApi.class,
                () -> new ClienteApi(uriBase()).transferencia()
                        .recuperarTransferencia("clave-administrativa-sintetica"));

        assertTrue(error.respuestaIncierta());
        assertEquals(2, solicitudes.size());
    }

    @Test
    void propagaLaDenegacionDeUnGrantVencido() {
        grantVencido = true;

        FalloApi error = assertThrows(
                FalloApi.class,
                () -> new ClienteApi(uriBase()).transferencia().completarTransferencia(
                        new PayloadConfiguracion("{}"), "grant-vencido", "idempotencia-sintetica"));

        assertEquals(403, error.estadoHttp());
        assertFalse(error.respuestaIncierta());
        List<Solicitud> capturadas = List.copyOf(solicitudes);
        assertEquals(2, capturadas.size());
        assertEquals("/api/v1/transferencia/completar", capturadas.get(1).ruta());
        assertEquals("grant-vencido", capturadas.get(1).grant());
    }

    @Test
    void cerrarSesionRequiereCsrfYObtieneUnoNuevoParaElSiguienteAcceso() {
        ClienteApi api = new ClienteApi(uriBase());
        api.sesion().iniciarSesion("dueno@example.test", "clave-sintetica");
        api.sesion().cerrarSesion();
        assertFalse(api.sesion().consultarSesion().autenticada());
        assertTrue(api.sesion().iniciarSesion("dueno@example.test", "clave-sintetica").autenticada());

        List<Solicitud> capturadas = List.copyOf(solicitudes);
        assertEquals(6, capturadas.size());
        assertEquals("DELETE", capturadas.get(2).metodo());
        assertEquals("/api/v1/sesion", capturadas.get(2).ruta());
        assertEquals("csrf-sesion", capturadas.get(2).csrf());
        assertTrue(capturadas.get(2).cookie().contains("OWNERSESSION=autenticada"));
        assertEquals("GET", capturadas.get(3).metodo());
        assertEquals("/api/v1/sesion", capturadas.get(3).ruta());
        assertEquals("/api/v1/csrf", capturadas.get(4).ruta());
        assertEquals("csrf-inicial", capturadas.get(5).csrf());
    }

    private URI uriBase() {
        return URI.create("http://127.0.0.1:" + servidor.getAddress().getPort() + "/");
    }

    private void responder(HttpExchange exchange) throws IOException {
        Solicitud solicitud = capturar(exchange);
        solicitudes.add(solicitud);
        switch (solicitud.ruta()) {
            case "/api/v1/csrf" -> {
                exchange.getResponseHeaders().add(
                        "Set-Cookie", "OWNERSESSION=anonima; Path=/; HttpOnly; SameSite=Strict");
                responderJson(exchange, 200, "{\"token\":\"csrf-inicial\"}");
            }
            case "/api/v1/sesion" -> {
                if ("POST".equals(solicitud.metodo())) {
                    sesionCerrada = false;
                    exchange.getResponseHeaders().add(
                            "Set-Cookie", "OWNERSESSION=autenticada; Path=/; HttpOnly; SameSite=Strict");
                    responderJson(
                            exchange,
                            200,
                            "{\"autenticada\":true,\"correo\":\"dueno@example.com\","
                                    + "\"revisionPropietario\":2,\"rol\":\"DUENO\",\"csrfToken\":\"csrf-sesion\"}");
                } else if ("DELETE".equals(solicitud.metodo())) {
                    sesionCerrada = true;
                    exchange.getResponseHeaders().add(
                            "Set-Cookie", "OWNERSESSION=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict");
                    responderJson(exchange, 200, "{\"autenticada\":false,\"csrfToken\":\"csrf-anonimo\"}");
                } else if (sesionCerrada) {
                    responderJson(exchange, 200, "{\"autenticada\":false}");
                } else {
                    responderJson(
                            exchange,
                            200,
                            "{\"autenticada\":true,\"correo\":\"dueno@example.com\","
                                    + "\"revisionPropietario\":2,\"rol\":\"DUENO\",\"csrfToken\":\"csrf-sesion\"}");
                }
            }
            case "/api/v1/panel" -> {
                exchange.getResponseHeaders().add("ETag", "\"7\"");
                responderJson(exchange, 200, """
                        {"revision":7,"revisionPropietario":2,
                         "propietario":{"nombres":"Ana","primerApellido":"López",
                          "segundoApellido":null,"correo":"dueno@example.com"},
                         "estacionamiento":{"id":"est-1","nombre":"Centro","tipo":"PUBLICO",
                          "horario":{"modo":"INTERVALO_DIARIO","zonaHoraria":"America/Mexico_City",
                           "horaApertura":"08:00","horaCierre":"22:00"}}}
                        """);
            }
            case "/api/v1/transferencia/iniciar" -> responderJson(
                    exchange,
                    200,
                    "{\"estado\":\"TRANSFERENCIA_PENDIENTE\",\"transferenciaId\":\"t-1\","
                            + "\"grant\":\"grant-temporal\",\"venceEn\":\"2026-10-23T21:00:00Z\","
                            + "\"avisoTransferencia\":\"DESHABILITADO\"}");
            case "/api/v1/transferencia/recuperar" -> responderJson(
                    exchange,
                    200,
                    recuperacionIncompleta
                            ? "{\"estado\":\"TRANSFERENCIA_PENDIENTE\",\"transferenciaId\":\"transferencia-sintetica\"}"
                            : "{\"estado\":\"TRANSFERENCIA_PENDIENTE\",\"transferenciaId\":\"transferencia-sintetica\","
                                    + "\"grant\":\"grant-recuperado\",\"venceEn\":\"2026-10-23T21:00:00Z\"}");
            case "/api/v1/transferencia/completar" -> responderJson(
                    exchange,
                    grantVencido ? 403 : 200,
                    grantVencido ? "{\"error\":\"autorización vencida\"}"
                            : "{\"estado\":\"CONFIGURADA\",\"avisoBienvenida\":\"ENVIADO\"}");
            case "/api/v1/configuracion/inicial" -> responderJson(
                    exchange,
                    errorRegistro ? 500 : 201,
                    "{\"estado\":\"CONFIGURADA\"}");
            default -> responderJson(exchange, 404, "{}");
        }
    }

    private Solicitud capturar(HttpExchange exchange) throws IOException {
        String cuerpo = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        return new Solicitud(
                exchange.getRequestMethod(),
                exchange.getRequestURI().getPath(),
                exchange.getRequestHeaders().getFirst("Cookie"),
                exchange.getRequestHeaders().getFirst("X-CSRF-TOKEN"),
                exchange.getRequestHeaders().getFirst("If-Match"),
                exchange.getRequestHeaders().getFirst("Idempotency-Key"),
                exchange.getRequestHeaders().getFirst("X-Transfer-Grant"),
                cuerpo);
    }

    private void responderJson(HttpExchange exchange, int estado, String cuerpo) throws IOException {
        byte[] respuesta = cuerpo.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=UTF-8");
        exchange.sendResponseHeaders(estado, respuesta.length);
        try (var salida = exchange.getResponseBody()) {
            salida.write(respuesta);
        }
    }

    private record Solicitud(
            String metodo,
            String ruta,
            String cookie,
            String csrf,
            String ifMatch,
            String idempotencia,
            String grant,
            String cuerpo) {
    }
}
