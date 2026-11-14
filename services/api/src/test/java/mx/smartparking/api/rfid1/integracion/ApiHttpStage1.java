package mx.smartparking.api.rfid1.integracion;

import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;

import tools.jackson.databind.json.JsonMapper;

/** Cliente HTTP sintético con cookie de sesión aislada por actor de aceptación. */
class ApiHttpStage1 {
    private static final String CSRF = "X-CSRF-TOKEN";
    private static final String RUTA_CAPTURAS = "/api/v1/rfid-1/capturas";
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private final URI base;
    private final Map<String, String> encabezadosFijos;
    private final CookieManager cookies = new CookieManager(null, CookiePolicy.ACCEPT_ALL);
    private final HttpClient http = HttpClient.newBuilder().cookieHandler(cookies)
            .connectTimeout(Duration.ofSeconds(4)).followRedirects(HttpClient.Redirect.NEVER).build();
    private String tokenCsrf;

    ApiHttpStage1(URI base) {
        this(base, Map.of());
    }

    ApiHttpStage1(URI base, Map<String, String> encabezadosFijos) {
        this.base = base;
        this.encabezadosFijos = Map.copyOf(encabezadosFijos);
    }

    String csrf() {
        return tokenCsrf;
    }

    void csrf(String valor) {
        tokenCsrf = valor;
    }

    HttpResponse<String> get(String ruta) throws Exception {
        return solicitar("GET", ruta, null, Map.of());
    }

    HttpResponse<String> get(String ruta, Map<String, String> encabezados) throws Exception {
        return solicitar("GET", ruta, null, encabezados);
    }

    HttpResponse<String> post(String ruta, Object cuerpo, Map<String, String> encabezados) throws Exception {
        return solicitar("POST", ruta, cuerpo, encabezados);
    }

    HttpResponse<String> patch(String ruta, Object cuerpo, Map<String, String> encabezados) throws Exception {
        return solicitar("PATCH", ruta, cuerpo, encabezados);
    }

    HttpResponse<String> delete(String ruta, Map<String, String> encabezados) throws Exception {
        return solicitar("DELETE", ruta, null, encabezados);
    }

    HttpResponse<String> postSinCsrf(String ruta, Object cuerpo) throws Exception {
        return post(ruta, cuerpo, Map.of());
    }

    HttpResponse<String> confirmar(String capturaId, String clave) throws Exception {
        return post(RUTA_CAPTURAS + "/" + capturaId + "/confirmacion", null,
                Map.of(CSRF, tokenCsrf, "Idempotency-Key", clave));
    }

    HttpResponse<String> cancelarCaptura(String capturaId) throws Exception {
        return delete(RUTA_CAPTURAS + "/" + capturaId, Map.of(CSRF, tokenCsrf));
    }

    HttpResponse<String> cerrarSesion() throws Exception {
        return delete("/api/v1/sesion", Map.of(CSRF, tokenCsrf));
    }

    private HttpResponse<String> solicitar(
            String metodo, String ruta, Object cuerpo, Map<String, String> encabezados) throws Exception {
        HttpRequest.Builder solicitud = HttpRequest.newBuilder(base.resolve(ruta))
                .timeout(Duration.ofSeconds(15)).header("Accept", "application/json");
        encabezadosFijos.forEach(solicitud::header);
        encabezados.forEach(solicitud::header);
        if (cuerpo == null) {
            solicitud.method(metodo, HttpRequest.BodyPublishers.noBody());
        } else {
            solicitud.header("Content-Type", "application/json; charset=UTF-8")
                    .method(metodo, HttpRequest.BodyPublishers.ofString(JSON.writeValueAsString(cuerpo)));
        }
        return http.send(solicitud.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    }
}
