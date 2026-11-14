package mx.smartparking.api.integracion;

import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.leerJson;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.numero;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.texto;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import mx.smartparking.api.integracion.ApiCliente;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Aceptación HTTP de administración de cuentas con datos y servicios descartables. */
final class OperadoresAdministracionAceptacionTest {

    private static final String RUTA_OPERADORES = "/api/v1/operadores";
    private static final String RUTA_SESION = "/api/v1/sesion";
    private static final String CSRF = "X-CSRF-TOKEN";
    private static final String ASUNTO_INVITACION = "Activa tu cuenta de Smart Parking";
    private static final Pattern TOKEN_ACTIVACION =
            Pattern.compile("https?://[^\\s#]+/activar-operador#([A-Za-z0-9_-]{43})");
    private static final Pattern TOKEN_RECUPERACION =
            Pattern.compile("https?://[^\\s#]+/restablecer-contrasena#([A-Za-z0-9_-]{43})");
    private static final HttpClient HTTP = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(4))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();
    private static final JsonMapper JSON = JsonMapper.builder().build();

    private static URI apiUrl;
    private static URI mailpitUrl;
    private static ClienteDueno dueno;
    private static ClienteDueno duenoSecundario;
    private static String correoDueno;
    private static String contrasenaDueno;

    @BeforeAll
    static void prepararClientes() throws Exception {
        apiUrl = OperadoresAdministracionEntornoAceptacion.apiUrl();
        mailpitUrl = OperadoresAdministracionEntornoAceptacion.mailpitUrl();
        correoDueno = System.getenv("TEST_OWNER_EMAIL");
        contrasenaDueno = System.getenv("TEST_OWNER_PASSWORD");
        assumeTrue(correoDueno != null && correoDueno.endsWith("@example.test")
                        && contrasenaDueno != null && !contrasenaDueno.isBlank(),
                "La aceptación requiere credenciales sintéticas del propietario.");
        OperadoresAdministracionEntornoAceptacion.prepararCredencialDueno(correoDueno, contrasenaDueno);
        dueno = iniciarSesion(apiUrl, correoDueno, contrasenaDueno);
        OperadoresAdministracionEntornoAceptacion.prepararCredencialDueno(correoDueno, contrasenaDueno);
        duenoSecundario = iniciarSesion(apiUrl, correoDueno, contrasenaDueno);
    }

    @Test
    void buscaFiltraYPaginaEnElServidorAntesDeCalcularElTotal() throws Exception {
        String sufijo = sufijo();
        String prefijo = "Directorio" + sufijo;
        List<String> correos = new ArrayList<>();
        for (int indice = 0; indice < 11; indice++) {
            String correo = "directorio." + sufijo + "." + indice + "@example.test";
            correos.add(correo);
            registrar(prefijo + " Nombre " + indice, "Primer" + indice, "Segundo" + indice, correo);
        }
        String correoEspecial = "directorio.especial." + sufijo + "@example.test";
        registrar(prefijo + " %_\\", "Primer especial", "Segundo especial", correoEspecial);

        String busquedaFilas = prefijo + " Nombre";
        JsonNode primera = pagina("pagina=1&busqueda=" + codificar(busquedaFilas) + "&estado=PENDIENTE");
        assertEquals(11, numero(primera, "totalRegistros"));
        assertEquals(2, numero(primera, "totalPaginas"));
        assertEquals(10, primera.path("items").size());
        assertEquals(1, numero(primera, "pagina"));

        JsonNode segunda = pagina("pagina=2&busqueda=" + codificar(busquedaFilas) + "&estado=PENDIENTE");
        assertEquals(1, segunda.path("items").size());
        assertEquals(2, numero(segunda, "pagina"));

        for (String criterio : List.of("Nombre 4", "Primer4", "Segundo4", correos.get(4))) {
            JsonNode resultado = pagina("busqueda=" + codificar(criterio) + "&estado=PENDIENTE");
            assertEquals(1, numero(resultado, "totalRegistros"), "La búsqueda debe abarcar " + criterio + ".");
        }
        JsonNode comodinesLiterales = pagina("busqueda=" + codificar("%_\\") + "&estado=PENDIENTE");
        assertEquals(1, numero(comodinesLiterales, "totalRegistros"));
        assertEquals(correoEspecial, texto(comodinesLiterales.path("items").get(0), "correo"));

        HttpResponse<String> estadoInvalido = dueno.api().get(RUTA_OPERADORES + "?estado=OTRO");
        assertEquals(400, estadoInvalido.statusCode());
        assertEquals("ESTADO_NO_VALIDO", texto(leerJson(estadoInvalido.body()), "codigo"));
        HttpResponse<String> paginaInvalida = dueno.api().get(RUTA_OPERADORES + "?pagina=abc");
        assertEquals(400, paginaInvalida.statusCode());
        assertEquals("PAGINA_NO_VALIDA", texto(leerJson(paginaInvalida.body()), "codigo"));
        HttpResponse<String> sinSesion = new ApiCliente(apiUrl).get(RUTA_OPERADORES + "?pagina=1");
        assertEquals(401, sinSesion.statusCode());

        String id = texto(primera.path("items").get(0), "id");
        HttpResponse<String> detalle = dueno.api().get(RUTA_OPERADORES + "/" + id);
        assertEquals(200, detalle.statusCode());
        assertTrue(etag(detalle).matches("\\\"[0-9]+\\\""));
        JsonNode proyeccion = leerJson(detalle.body());
        assertTrue(proyeccion.hasNonNull("creadaEn"));
        assertTrue(proyeccion.has("puedeDesactivar") && proyeccion.has("puedeReactivar"));
        assertFalse(proyeccion.has("revisionAcceso") || proyeccion.has("revision"));
        assertFalse(detalle.body().matches("(?s).*\\\"(?:tokenHash|hashContrasena|hash_contrasena_acceso)\\\".*"));
    }

    @Test
    void aplicaRevisionUnicaBajaReactivacionYRecuperacionSegura() throws Exception {
        String sufijo = sufijo();
        String correo = "administracion." + sufijo + "@example.test";
        UUID id = registrar("Administración " + sufijo, "Primer apellido", "Segundo apellido", correo);
        String tokenInicial = extraerToken(MailpitApiCliente.textoUnico(mailpitUrl, ASUNTO_INVITACION, correo),
                TOKEN_ACTIVACION);
        HttpResponse<String> detalleInicial = dueno.api().get(RUTA_OPERADORES + "/" + id);
        String etagInicial = etag(detalleInicial);

        HttpResponse<String> reenvioEnEspera = postDueno(
                RUTA_OPERADORES + "/" + id + "/invitacion/reemitir", null,
                etagInicial, clave("reenvio-espera-" + sufijo));
        assertEquals(429, reenvioEnEspera.statusCode());
        assertEquals("REENVIO_EN_ENFRIAMIENTO", texto(leerJson(reenvioEnEspera.body()), "codigo"));
        assertTrue(reenvioEnEspera.headers().firstValue("Retry-After").isPresent());
        assertEquals(1, MailpitApiCliente.textosPorAsunto(mailpitUrl, ASUNTO_INVITACION, correo).size());

        List<HttpResponse<String>> bajas = patchConcurrentes(
                RUTA_OPERADORES + "/" + id + "/estado", Map.of("estado", "INACTIVA"), etagInicial,
                clave("baja-a-" + sufijo), clave("baja-b-" + sufijo));
        assertEquals(1, bajas.stream().filter(respuesta -> respuesta.statusCode() == 200).count());
        assertEquals(1, bajas.stream().filter(respuesta -> respuesta.statusCode() == 412).count());
        HttpResponse<String> detalleInactivo = dueno.api().get(RUTA_OPERADORES + "/" + id);
        assertEquals("INACTIVA", texto(leerJson(detalleInactivo.body()), "estado"));
        assertTrue(numeroRevision(etag(detalleInactivo)) > numeroRevision(etagInicial));
        assertEquals(410, dueno.api().postJson("/api/v1/operadores/activacion/validar",
                Map.of("token", tokenInicial), Map.of(CSRF, dueno.csrf())).statusCode());

        HttpResponse<String> sinCambio = patchDueno(
                RUTA_OPERADORES + "/" + id + "/estado", Map.of("estado", "INACTIVA"),
                etag(detalleInactivo), clave("no-op-" + sufijo));
        assertEquals(200, sinCambio.statusCode());
        assertEquals(etag(detalleInactivo), etag(sinCambio), "El no-op no debe incrementar la revisión.");
        assertEquals("TRANSICION_NO_PERMITIDA", codigo(patchDueno(
                RUTA_OPERADORES + "/" + id + "/estado", Map.of("estado", "ACTIVA"), etag(detalleInactivo),
                clave("estado-directo-" + sufijo))));
        String claveReactivacion = clave("reactivar-" + sufijo);
        HttpResponse<String> reactivacion = patchDueno(
                RUTA_OPERADORES + "/" + id + "/estado", Map.of("estado", "PENDIENTE"),
                etag(detalleInactivo), claveReactivacion);
        esperarEnfriamientoSiAplica(reactivacion);
        if (reactivacion.statusCode() == 429) {
            reactivacion = patchDueno(RUTA_OPERADORES + "/" + id + "/estado",
                    Map.of("estado", "PENDIENTE"), etag(detalleInactivo), claveReactivacion);
        }
        assertEquals(200, reactivacion.statusCode());
        assertEquals("PENDIENTE", texto(leerJson(reactivacion.body()), "estado"));
        int correosTrasReactivacion = MailpitApiCliente.textosPorAsunto(mailpitUrl, ASUNTO_INVITACION, correo).size();
        HttpResponse<String> replayReactivacion = patchDueno(
                RUTA_OPERADORES + "/" + id + "/estado", Map.of("estado", "PENDIENTE"),
                etag(detalleInactivo), claveReactivacion);
        assertEquals(200, replayReactivacion.statusCode());
        assertEquals(correosTrasReactivacion,
                MailpitApiCliente.textosPorAsunto(mailpitUrl, ASUNTO_INVITACION, correo).size());

        String tokenReactivacion = MailpitApiCliente.textosPorAsunto(
                        mailpitUrl, ASUNTO_INVITACION, correo).stream()
                .map(mensaje -> extraerToken(mensaje, TOKEN_ACTIVACION))
                .filter(token -> !tokenInicial.equals(token))
                .findFirst()
                .orElseThrow(() -> new AssertionError("La reactivación debe emitir un token distinto."));
        assertEquals(200, dueno.api().postJson("/api/v1/operadores/activacion/validar",
                Map.of("token", tokenReactivacion), Map.of(CSRF, dueno.csrf())).statusCode());
        assertEquals(204, dueno.api().postJson("/api/v1/operadores/activacion/completar",
                Map.of("token", tokenReactivacion, "contrasena", "Operador nueva 2026!",
                        "confirmarContrasena", "Operador nueva 2026!"), Map.of(CSRF, dueno.csrf())).statusCode());

        HttpResponse<String> detalleActivo = dueno.api().get(RUTA_OPERADORES + "/" + id);
        assertEquals("ACTIVA", texto(leerJson(detalleActivo.body()), "estado"));
        String keyRecuperacion = clave("recuperar-" + sufijo);
        HttpResponse<String> solicitudRecuperacion = postDueno(
                RUTA_OPERADORES + "/" + id + "/recuperacion", null, etag(detalleActivo), keyRecuperacion);
        assertEquals(200, solicitudRecuperacion.statusCode());
        assertFalse(solicitudRecuperacion.body().contains("token"));
        JsonNode respuestaRecuperacion = leerJson(solicitudRecuperacion.body());
        assertTrue(List.of("ENVIADO", "FALLIDO", "DESCONOCIDO", "DESHABILITADO")
                .contains(texto(respuestaRecuperacion, "estadoEnvio")));
        long minutosRestantes = Duration.between(Instant.now(),
                Instant.parse(texto(respuestaRecuperacion, "venceEn"))).toMinutes();
        assertTrue(minutosRestantes >= 29 && minutosRestantes <= 30,
                "El enlace de recuperación debe vencer a los 30 minutos.");
        HttpResponse<String> replayRecuperacion = postDueno(
                RUTA_OPERADORES + "/" + id + "/recuperacion", null, etag(detalleActivo), keyRecuperacion);
        assertEquals(200, replayRecuperacion.statusCode());
        assertEquals(texto(respuestaRecuperacion, "estadoEnvio"),
                texto(leerJson(replayRecuperacion.body()), "estadoEnvio"));
        assertEquals(429, postDueno(RUTA_OPERADORES + "/" + id + "/recuperacion", null,
                etag(dueno.api().get(RUTA_OPERADORES + "/" + id)), clave("recuperar-duplicado-" + sufijo)).statusCode());
        String textoRecuperacion = leerCorreoConRuta(mailpitUrl, correo, TOKEN_RECUPERACION);
        String tokenRecuperacion = extraerToken(textoRecuperacion, TOKEN_RECUPERACION);
        assertEquals(410, dueno.api().postJson("/api/v1/operadores/activacion/validar",
                Map.of("token", tokenRecuperacion), Map.of(CSRF, dueno.csrf())).statusCode());
        assertEquals(200, dueno.api().postJson("/api/v1/operadores/recuperacion/validar",
                Map.of("token", tokenRecuperacion), Map.of(CSRF, dueno.csrf())).statusCode());
        assertEquals(200, dueno.api().postJson("/api/v1/operadores/recuperacion/validar",
                Map.of("token", tokenRecuperacion), Map.of(CSRF, dueno.csrf())).statusCode());
        assertEquals(204, dueno.api().postJson("/api/v1/operadores/recuperacion/completar",
                Map.of("token", tokenRecuperacion, "contrasena", "Operador renovada 2026!",
                        "confirmarContrasena", "Operador renovada 2026!"),
                Map.of(CSRF, dueno.csrf())).statusCode());
        assertEquals(410, dueno.api().postJson("/api/v1/operadores/recuperacion/validar",
                Map.of("token", tokenRecuperacion), Map.of(CSRF, dueno.csrf())).statusCode());
        assertEquals(410, dueno.api().postJson("/api/v1/operadores/recuperacion/completar",
                Map.of("token", tokenRecuperacion, "contrasena", "Operador renovada 2026!",
                        "confirmarContrasena", "Operador renovada 2026!"),
                Map.of(CSRF, dueno.csrf())).statusCode());
        HttpResponse<String> detalleTrasRecuperacion = dueno.api().get(RUTA_OPERADORES + "/" + id);
        assertTrue(numeroRevision(etag(detalleTrasRecuperacion)) > numeroRevision(etag(detalleActivo)));
        assertEquals(200, dueno.api().get("/api/v1/panel").statusCode(),
                "La operación de operador no debe revocar la sesión DUENO.");
        assertEquals(401, intentarSesion(apiUrl, correo, "Operador nueva 2026!").statusCode(),
                "La cuenta OPERADOR legada sin vínculo continúa rechazada después de la recuperación.");
        assertEquals(401, intentarSesion(apiUrl, correo, "Operador renovada 2026!").statusCode(),
                "La cuenta OPERADOR legada sin vínculo sigue rechazada.");
        HttpResponse<String> bajaActiva = patchDueno(RUTA_OPERADORES + "/" + id + "/estado",
                Map.of("estado", "INACTIVA"), etag(detalleTrasRecuperacion), clave("baja-activa-" + sufijo));
        assertEquals(200, bajaActiva.statusCode());
        assertEquals("INACTIVA", texto(leerJson(bajaActiva.body()), "estado"));
    }

    private static UUID registrar(String nombres, String primerApellido, String segundoApellido, String correo)
            throws Exception {
        HttpResponse<String> respuesta = dueno.api().post(RUTA_OPERADORES,
                Map.of("nombres", nombres, "primerApellido", primerApellido, "segundoApellido", segundoApellido,
                        "correo", correo), clave("registro-" + sufijo()), dueno.csrf());
        assertEquals(201, respuesta.statusCode());
        return UUID.fromString(texto(leerJson(respuesta.body()), "id"));
    }

    private static JsonNode pagina(String consulta) throws Exception {
        HttpResponse<String> respuesta = dueno.api().get(RUTA_OPERADORES + "?" + consulta);
        assertEquals(200, respuesta.statusCode());
        return leerJson(respuesta.body());
    }

    private static ClienteDueno iniciarSesion(URI base, String correo, String contrasena) throws Exception {
        ApiCliente cliente = new ApiCliente(base);
        String csrf = cliente.obtenerCsrf(true);
        HttpResponse<String> login = cliente.postJson(RUTA_SESION,
                Map.of("correo", correo, "contrasena", contrasena), Map.of(CSRF, csrf));
        assertEquals(200, login.statusCode(), "El acceso sintético de propietario debe funcionar.");
        String csrfRenovado = texto(leerJson(login.body()), "csrfToken");
        cliente.csrf(csrfRenovado);
        return new ClienteDueno(cliente, csrfRenovado);
    }

    private static HttpResponse<String> intentarSesion(URI base, String correo, String contrasena) throws Exception {
        ApiCliente cliente = new ApiCliente(base);
        String csrf = cliente.obtenerCsrf(true);
        return cliente.postJson(RUTA_SESION, Map.of("correo", correo, "contrasena", contrasena),
                Map.of(CSRF, csrf));
    }

    private static HttpResponse<String> patchDueno(String ruta, Object cuerpo, String ifMatch, String key)
            throws Exception {
        return enviar(dueno, "PATCH", ruta, cuerpo, Map.of("If-Match", ifMatch, "Idempotency-Key", key));
    }

    private static HttpResponse<String> postDueno(String ruta, Object cuerpo, String ifMatch, String key)
            throws Exception {
        return enviar(dueno, "POST", ruta, cuerpo, Map.of("If-Match", ifMatch, "Idempotency-Key", key));
    }

    private static List<HttpResponse<String>> patchConcurrentes(
            String ruta, Object cuerpo, String ifMatch, String primeraClave, String segundaClave) {
        CompletableFuture<HttpResponse<String>> primera = CompletableFuture.supplyAsync(() ->
                enviarSinChecked(dueno, "PATCH", ruta, cuerpo,
                        Map.of("If-Match", ifMatch, "Idempotency-Key", primeraClave)));
        CompletableFuture<HttpResponse<String>> segunda = CompletableFuture.supplyAsync(() ->
                enviarSinChecked(duenoSecundario, "PATCH", ruta, cuerpo,
                        Map.of("If-Match", ifMatch, "Idempotency-Key", segundaClave)));
        try {
            CompletableFuture.allOf(primera, segunda).join();
            return List.of(primera.join(), segunda.join());
        } catch (CompletionException excepcion) {
            throw new AssertionError("Las transiciones concurrentes deben completar por HTTP.");
        }
    }

    private static HttpResponse<String> enviarSinChecked(
            ClienteDueno cliente, String metodo, String ruta, Object cuerpo, Map<String, String> encabezados) {
        try {
            return enviar(cliente, metodo, ruta, cuerpo, encabezados);
        } catch (Exception excepcion) {
            throw new CompletionException(excepcion);
        }
    }

    private static HttpResponse<String> enviar(
            ClienteDueno cliente, String metodo, String ruta, Object cuerpo, Map<String, String> encabezados)
            throws Exception {
        HttpRequest.Builder solicitud = HttpRequest.newBuilder(apiUrl.resolve(ruta))
                .timeout(Duration.ofSeconds(20))
                .header("Accept", "application/json")
                .header("Cookie", "JSESSIONID=" + cliente.api().cookie("JSESSIONID"))
                .header(CSRF, cliente.csrf());
        encabezados.forEach(solicitud::header);
        if (cuerpo == null) {
            solicitud.method(metodo, HttpRequest.BodyPublishers.noBody());
        } else {
            solicitud.header("Content-Type", "application/json")
                    .method(metodo, HttpRequest.BodyPublishers.ofString(ApiCliente.serializar(cuerpo)));
        }
        return HTTP.send(solicitud.build(), HttpResponse.BodyHandlers.ofString());
    }

    private static String leerCorreoConRuta(URI mailpit, String destinatario, Pattern ruta)
            throws Exception {
        JsonNode mensajes = JSON.readTree(HTTP.send(HttpRequest.newBuilder(
                        mailpit.resolve("/api/v1/messages?limit=100")).GET().build(),
                HttpResponse.BodyHandlers.ofString()).body());
        for (JsonNode mensaje : mensajes.path("messages")) {
            boolean coincide = false;
            for (JsonNode direccion : mensaje.path("To")) {
                coincide |= destinatario.equals(direccion.path("Address").asText());
            }
            if (!coincide) continue;
            String id = URLEncoder.encode(mensaje.path("ID").asText(), StandardCharsets.UTF_8);
            JsonNode detalle = JSON.readTree(HTTP.send(HttpRequest.newBuilder(
                            mailpit.resolve("/api/v1/message/" + id)).GET().build(),
                    HttpResponse.BodyHandlers.ofString()).body());
            String texto = detalle.path("Text").asText("");
            if (ruta.matcher(texto).find()) return texto;
        }
        throw new AssertionError("Mailpit no contiene el mensaje sintético con enlace esperado.");
    }

    private static String extraerToken(String mensaje, Pattern formato) {
        Matcher matcher = formato.matcher(mensaje);
        assertTrue(matcher.find(), "El correo sintético debe contener el token en el fragmento del enlace.");
        return matcher.group(1);
    }

    private static void esperarEnfriamientoSiAplica(HttpResponse<String> respuesta) throws Exception {
        if (respuesta.statusCode() != 429) return;
        long segundos = respuesta.headers().firstValue("Retry-After").map(Long::parseLong).orElse(60L);
        Thread.sleep(Math.max(0, segundos * 1_000L + 250));
    }

    private static String etag(HttpResponse<String> respuesta) {
        return respuesta.headers().firstValue("ETag")
                .orElseThrow(() -> new AssertionError("La respuesta del detalle debe incluir ETag."));
    }

    private static long numeroRevision(String etag) {
        return Long.parseLong(etag.replace("\"", ""));
    }

    private static String codigo(HttpResponse<String> respuesta) throws Exception {
        assertEquals(409, respuesta.statusCode());
        return texto(leerJson(respuesta.body()), "codigo");
    }

    private static String codificar(String valor) {
        return URLEncoder.encode(valor, StandardCharsets.UTF_8);
    }

    private static String sufijo() {
        return UUID.randomUUID().toString().replace("-", "").substring(0, 12);
    }

    private static String clave(String prefijo) {
        return prefijo + "-" + UUID.randomUUID();
    }

    private record ClienteDueno(ApiCliente api, String csrf) {
    }
}
