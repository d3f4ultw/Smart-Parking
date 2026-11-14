package mx.smartparking.ownerconsole.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicReference;
import mx.smartparking.ownerconsole.modelo.SesionPropietario;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** Verifica el contrato de sesión contra respuestas HTTP sintéticas y locales. */
class ClienteSesionPropietarioTest {

    private final AtomicReference<String> respuestaSesion = new AtomicReference<>("{}");
    private HttpServer servidor;
    private ExecutorService ejecutor;
    private ClienteSesionPropietario cliente;

    @BeforeEach
    void iniciarServidor() throws IOException {
        servidor = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        ejecutor = Executors.newCachedThreadPool();
        servidor.setExecutor(ejecutor);
        servidor.createContext("/", this::responder);
        servidor.start();
        URI base = URI.create("http://127.0.0.1:" + servidor.getAddress().getPort() + "/");
        cliente = new ClienteApi(base).sesion();
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
    void respuestasIncompletasMalformadasOSinRolDuenoNoAutenticanEnGetNiPost() {
        List<Caso> casos = List.of(
                new Caso("objeto vacío", "{}"),
                new Caso("raíz nula", "null"),
                new Caso("raíz arreglo", "[]"),
                new Caso("autenticada ausente", "{\"rol\":\"DUENO\"}"),
                new Caso("autenticada nula", cuerpo("null", "\"DUENO\"", "\"duena@example.test\"", "2")),
                new Caso("autenticada texto", cuerpo("\"true\"", "\"DUENO\"", "\"duena@example.test\"", "2")),
                new Caso("autenticada numérica", cuerpo("1", "\"DUENO\"", "\"duena@example.test\"", "2")),
                new Caso("autenticada falsa", cuerpo("false", "\"DUENO\"", "\"duena@example.test\"", "2")),
                new Caso("rol ausente", "{\"autenticada\":true,\"correo\":\"duena@example.test\","
                        + "\"revisionPropietario\":2}"),
                new Caso("rol nulo", cuerpo("true", "null", "\"duena@example.test\"", "2")),
                new Caso("rol no textual", cuerpo("true", "7", "\"duena@example.test\"", "2")),
                new Caso("rol operador", cuerpo("true", "\"OPERADOR\"", "\"operador@example.test\"", "2")),
                new Caso("rol desconocido", cuerpo("true", "\"ADMIN\"", "\"duena@example.test\"", "2")),
                new Caso("correo ausente", "{\"autenticada\":true,\"rol\":\"DUENO\","
                        + "\"revisionPropietario\":2}"),
                new Caso("correo nulo", cuerpo("true", "\"DUENO\"", "null", "2")),
                new Caso("correo vacío", cuerpo("true", "\"DUENO\"", "\"   \"", "2")),
                new Caso("correo no textual", cuerpo("true", "\"DUENO\"", "42", "2")),
                new Caso("revisión ausente", "{\"autenticada\":true,\"rol\":\"DUENO\","
                        + "\"correo\":\"duena@example.test\"}"),
                new Caso("revisión nula", cuerpo("true", "\"DUENO\"", "\"duena@example.test\"", "null")),
                new Caso("revisión texto", cuerpo("true", "\"DUENO\"", "\"duena@example.test\"", "\"2\"")),
                new Caso("revisión decimal", cuerpo("true", "\"DUENO\"", "\"duena@example.test\"", "2.5")),
                new Caso("revisión negativa", cuerpo("true", "\"DUENO\"", "\"duena@example.test\"", "-1")),
                new Caso("revisión fuera de long", cuerpo("true", "\"DUENO\"", "\"duena@example.test\"",
                        "9223372036854775808")));

        for (Caso caso : casos) {
            respuestaSesion.set(caso.respuesta());
            SesionPropietario inicio = cliente.iniciarSesion("duena@example.test", "clave-sintetica");
            SesionPropietario consulta = cliente.consultarSesion();
            assertFalse(inicio.autenticada(), "POST: " + caso.nombre());
            assertFalse(consulta.autenticada(), "GET: " + caso.nombre());
            assertEquals("", inicio.correo(), "La respuesta rechazada no debe proyectar identidad");
            assertEquals("", consulta.correo(), "La consulta rechazada no debe proyectar identidad");
        }
    }

    @Test
    void propietarioValidoSeAceptaEnGetYPostIncluidaRevisionCero() {
        for (long revision : List.of(0L, 2L)) {
            respuestaSesion.set(cuerpo("true", "\"DUENO\"", "\"duena@example.test\"", Long.toString(revision)));
            SesionPropietario inicio = cliente.iniciarSesion("duena@example.test", "clave-sintetica");
            SesionPropietario consulta = cliente.consultarSesion();
            assertTrue(inicio.autenticada());
            assertTrue(consulta.autenticada());
            assertEquals("duena@example.test", inicio.correo());
            assertEquals(revision, inicio.revisionPropietario());
            assertEquals(revision, consulta.revisionPropietario());
        }
    }

    private static String cuerpo(String autenticada, String rol, String correo, String revision) {
        return "{\"autenticada\":" + autenticada + ",\"rol\":" + rol + ",\"correo\":" + correo
                + ",\"revisionPropietario\":" + revision + "}";
    }

    private void responder(HttpExchange intercambio) throws IOException {
        try {
            intercambio.getRequestBody().readAllBytes();
            String cuerpo = "/api/v1/csrf".equals(intercambio.getRequestURI().getPath())
                    ? "{\"token\":\"csrf-sintetico\"}" : respuestaSesion.get();
            byte[] bytes = cuerpo.getBytes(StandardCharsets.UTF_8);
            intercambio.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
            intercambio.sendResponseHeaders(200, bytes.length);
            intercambio.getResponseBody().write(bytes);
        } finally {
            intercambio.close();
        }
    }

    private record Caso(String nombre, String respuesta) {
    }
}
