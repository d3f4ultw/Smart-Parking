package mx.smartparking.api.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.io.IOException;
import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.HttpCookie;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import tools.jackson.databind.json.JsonMapper;

final class ApiCliente {

    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final String CSRF = "X-CSRF-TOKEN";

    private final URI base;
    private final CookieManager cookies = new CookieManager(null, CookiePolicy.ACCEPT_ALL);
    private final HttpClient cliente = HttpClient.newBuilder()
            .cookieHandler(cookies)
            .connectTimeout(Duration.ofSeconds(4))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();
    private String tokenCsrf;

    ApiCliente(URI base) {
        this.base = base;
    }

    String obtenerCsrf(boolean revisarCookie) throws Exception {
        HttpResponse<String> respuesta = get("/api/v1/csrf");
        assertEquals(200, respuesta.statusCode(), "La API debe devolver el token CSRF.");
        if (revisarCookie) {
            List<String> cookiesEmitidas = respuesta.headers().allValues("Set-Cookie");
            String cookieSesion = cookiesEmitidas.stream()
                    .filter(cookie -> cookie.startsWith("JSESSIONID="))
                    .findFirst()
                    .orElse("");
            String cookieLower = cookieSesion.toLowerCase(java.util.Locale.ROOT);
            assertTrue(!cookieSesion.isEmpty(), "El token CSRF debe establecer una sesión server-side.");
            assertTrue(cookieLower.contains("httponly"), "La cookie de sesión debe ser HttpOnly.");
            assertTrue(cookieLower.contains("samesite=strict"), "La cookie de sesión debe usar SameSite Strict.");
        }
        tokenCsrf = PropietarioApiAceptacionSupport.texto(
                PropietarioApiAceptacionSupport.leerJson(respuesta.body()), "token");
        assertFalse(tokenCsrf.isBlank(), "El token CSRF no debe estar vacío.");
        return tokenCsrf;
    }

    void csrf(String token) {
        tokenCsrf = token;
    }

    String cookie(String nombre) {
        return cookies.getCookieStore().getCookies().stream()
                .filter(cookie -> nombre.equalsIgnoreCase(cookie.getName()))
                .map(HttpCookie::getValue)
                .findFirst()
                .orElse(null);
    }

    HttpResponse<String> get(String ruta) throws IOException, InterruptedException {
        return enviar("GET", ruta, null, Map.of());
    }

    HttpResponse<String> post(
            String ruta,
            Object cuerpo,
            String claveIdempotencia,
            String csrf) throws IOException, InterruptedException {
        Map<String, String> encabezados = csrf == null
                ? Map.of("Idempotency-Key", claveIdempotencia)
                : Map.of("Idempotency-Key", claveIdempotencia, CSRF, csrf);
        return enviar("POST", ruta, cuerpo, encabezados);
    }

    HttpResponse<String> postJson(
            String ruta,
            Object cuerpo,
            Map<String, String> encabezados) throws IOException, InterruptedException {
        return enviar("POST", ruta, cuerpo, encabezados);
    }

    HttpResponse<String> postCuerpoJson(
            String ruta,
            HttpRequest.BodyPublisher cuerpo,
            String token) throws IOException, InterruptedException {
        HttpRequest solicitud = HttpRequest.newBuilder(base.resolve(ruta))
                .timeout(Duration.ofSeconds(20))
                .header("Accept", "application/json")
                .header("Content-Type", "application/json; charset=UTF-8")
                .header(CSRF, token)
                .POST(cuerpo)
                .build();
        return cliente.send(solicitud, HttpResponse.BodyHandlers.ofString());
    }

    HttpResponse<String> deleteConCsrf(String ruta) throws IOException, InterruptedException {
        return enviar("DELETE", ruta, null, Map.of(CSRF, tokenCsrf));
    }

    HttpResponse<String> deleteSinCsrf(String ruta) throws IOException, InterruptedException {
        return enviar("DELETE", ruta, null, Map.of());
    }

    HttpResponse<String> postConCsrf(
            String ruta,
            Object cuerpo,
            Map<String, String> encabezadosAdicionales) throws IOException, InterruptedException {
        java.util.HashMap<String, String> encabezados = new java.util.HashMap<>(encabezadosAdicionales);
        encabezados.put(CSRF, tokenCsrf);
        return enviar("POST", ruta, cuerpo, encabezados);
    }

    HttpResponse<String> postCompletar(
            Object cuerpo,
            String claveIdempotencia,
            String grant) throws IOException, InterruptedException {
        return postConCsrf(
                "/api/v1/transferencia/completar",
                cuerpo,
                Map.of("Idempotency-Key", claveIdempotencia, "X-Transfer-Grant", grant));
    }

    HttpResponse<String> postCompletarSinCsrf(
            Object cuerpo,
            String claveIdempotencia,
            String grant) throws IOException, InterruptedException {
        return enviar(
                "POST",
                "/api/v1/transferencia/completar",
                cuerpo,
                Map.of("Idempotency-Key", claveIdempotencia, "X-Transfer-Grant", grant));
    }

    HttpResponse<String> patch(
            String ruta,
            Object cuerpo,
            String ifMatch,
            String claveIdempotencia) throws IOException, InterruptedException {
        return enviar(
                "PATCH",
                ruta,
                cuerpo,
                Map.of(
                        CSRF, tokenCsrf,
                        "If-Match", ifMatch,
                        "Idempotency-Key", claveIdempotencia));
    }

    HttpResponse<String> patchSinCsrf(
            String ruta,
            Object cuerpo,
            String ifMatch,
            String claveIdempotencia) throws IOException, InterruptedException {
        return enviar(
                "PATCH",
                ruta,
                cuerpo,
                Map.of("If-Match", ifMatch, "Idempotency-Key", claveIdempotencia));
    }

    List<HttpResponse<String>> patchConcurrentes(
            String ifMatch,
            String primeraClave,
            String segundaClave) {
        CompletableFuture<HttpResponse<String>> primera = enviarAsync(
                "PATCH",
                "/api/v1/estacionamiento",
                Map.of("nombre", "Cambio concurrente A"),
                Map.of(CSRF, tokenCsrf, "If-Match", ifMatch, "Idempotency-Key", primeraClave));
        CompletableFuture<HttpResponse<String>> segunda = enviarAsync(
                "PATCH",
                "/api/v1/estacionamiento",
                Map.of("nombre", "Cambio concurrente B"),
                Map.of(CSRF, tokenCsrf, "If-Match", ifMatch, "Idempotency-Key", segundaClave));
        try {
            CompletableFuture.allOf(primera, segunda).join();
            return List.of(primera.join(), segunda.join());
        } catch (CompletionException excepcion) {
            throw new AssertionError("Las solicitudes concurrentes deben completar por HTTP.");
        }
    }

    private CompletableFuture<HttpResponse<String>> enviarAsync(
            String metodo,
            String ruta,
            Object cuerpo,
            Map<String, String> encabezados) {
        try {
            return cliente.sendAsync(solicitud(metodo, ruta, cuerpo, encabezados),
                    HttpResponse.BodyHandlers.ofString());
        } catch (RuntimeException excepcion) {
            throw new AssertionError("La solicitud concurrente debe poder construirse.");
        }
    }

    private HttpResponse<String> enviar(
            String metodo,
            String ruta,
            Object cuerpo,
            Map<String, String> encabezados) throws IOException, InterruptedException {
        return cliente.send(solicitud(metodo, ruta, cuerpo, encabezados), HttpResponse.BodyHandlers.ofString());
    }

    private HttpRequest solicitud(
            String metodo,
            String ruta,
            Object cuerpo,
            Map<String, String> encabezados) {
        HttpRequest.Builder solicitud = HttpRequest.newBuilder(base.resolve(ruta))
                .timeout(Duration.ofSeconds(12))
                .header("Accept", "application/json");
        encabezados.forEach(solicitud::header);
        if (cuerpo == null) {
            solicitud.method(metodo, HttpRequest.BodyPublishers.noBody());
        } else {
            solicitud.header("Content-Type", "application/json")
                    .method(metodo, HttpRequest.BodyPublishers.ofString(serializar(cuerpo)));
        }
        return solicitud.build();
    }

    static String serializar(Object cuerpo) {
        return JSON.writeValueAsString(cuerpo);
    }
}
