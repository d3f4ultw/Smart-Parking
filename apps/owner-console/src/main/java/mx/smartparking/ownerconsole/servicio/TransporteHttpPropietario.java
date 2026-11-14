package mx.smartparking.ownerconsole.servicio;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.IOException;
import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.HashMap;
import java.util.Map;

/** Comparte el transporte, las cookies de sesión y el token CSRF entre los clientes. */
final class TransporteHttpPropietario {

    private static final Duration TIEMPO_CONEXION = Duration.ofSeconds(4);
    private static final Duration TIEMPO_SOLICITUD = Duration.ofSeconds(10);
    private static final String RUTA_CSRF = "/api/v1/csrf";
    private final ObjectMapper json = new ObjectMapper();
    private final HttpClient cliente;
    private final URI base;
    private volatile String tokenCsrf;

    TransporteHttpPropietario(URI base) {
        this.base = base;
        CookieManager cookies = new CookieManager(null, CookiePolicy.ACCEPT_ALL);
        cliente = HttpClient.newBuilder()
                .cookieHandler(cookies)
                .connectTimeout(TIEMPO_CONEXION)
                .followRedirects(HttpClient.Redirect.NEVER)
                .build();
    }

    ObjectNode nuevoObjetoJson() {
        return json.createObjectNode();
    }

    JsonNode enviarConCsrf(
            String metodo,
            String ruta,
            String cuerpo,
            Map<String, String> encabezados,
            boolean mutacionIncierta) {
        HttpResponse<String> respuesta = solicitarConCsrf(
                metodo, ruta, cuerpo, encabezados, mutacionIncierta);
        return parsear(respuesta.body(), mutacionIncierta);
    }

    /**
     * obtiene o reutiliza el token de protección y lo agrega a la solicitud
     * si el envío falla lo descarta para pedir uno nuevo más adelante
     */
    HttpResponse<String> solicitarConCsrf(
            String metodo,
            String ruta,
            String cuerpo,
            Map<String, String> encabezados,
            boolean mutacionIncierta) {
        String token = obtenerTokenCsrf();
        Map<String, String> encabezadosCsrf = new HashMap<>(encabezados);
        encabezadosCsrf.put("X-CSRF-TOKEN", token);
        try {
            return solicitar(metodo, ruta, cuerpo, encabezadosCsrf, mutacionIncierta);
        } catch (FalloApi error) {
            tokenCsrf = null;
            throw error;
        }
    }

    JsonNode enviar(
            String metodo,
            String ruta,
            String cuerpo,
            Map<String, String> encabezados,
            boolean mutacionIncierta) {
        HttpResponse<String> respuesta = solicitar(metodo, ruta, cuerpo, encabezados, mutacionIncierta);
        return parsear(respuesta.body(), mutacionIncierta);
    }

    /**
     * envía la solicitud con un tiempo límite y no sigue otras direcciones indicadas por el servidor
     * si ocurre un error indica si podría haberse guardado algún cambio
     */
    HttpResponse<String> solicitar(
            String metodo,
            String ruta,
            String cuerpo,
            Map<String, String> encabezados,
            boolean mutacionIncierta) {
        HttpRequest.Builder constructor = HttpRequest.newBuilder(base.resolve(ruta))
                .timeout(TIEMPO_SOLICITUD)
                .header("Accept", "application/json");
        encabezados.forEach(constructor::header);
        if (cuerpo != null) {
            constructor.header("Content-Type", "application/json; charset=UTF-8")
                    .method(metodo, HttpRequest.BodyPublishers.ofString(cuerpo));
        } else {
            constructor.method(metodo, HttpRequest.BodyPublishers.noBody());
        }
        try {
            HttpResponse<String> respuesta = cliente.send(
                    constructor.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            int estado = respuesta.statusCode();
            if (estado >= 300 && estado < 400) {
                throw new FalloApi(estado, mutacionIncierta, "No pudimos abrir la conexión. Inténtalo de nuevo.");
            }
            if (estado < 200 || estado >= 300) {
                String mensaje = estado == 400 ? mensajeValidacion(respuesta.body()) : null;
                throw new FalloApi(
                        estado,
                        mutacionIncierta && estado >= 500,
                        mensaje == null ? mensajePorEstado(estado) : mensaje);
            }
            return respuesta;
        } catch (IOException error) {
            throw new FalloApi(0, mutacionIncierta, "No pudimos conectar con Smart Parking. Revisa tu conexión e inténtalo de nuevo.");
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new FalloApi(0, mutacionIncierta, "La conexión se interrumpió. Revisa tu conexión e inténtalo de nuevo.");
        }
    }

    /**
     * lee la información que respondió el servidor
     * si no puede leerla indica si podría haberse guardado algún cambio
     */
    JsonNode parsear(String cuerpo, boolean mutacionIncierta) {
        try {
            JsonNode respuesta = json.readTree(cuerpo);
            if (respuesta == null) {
                throw new FalloApi(0, mutacionIncierta, "No pudimos leer la información recibida.");
            }
            return respuesta;
        } catch (JsonProcessingException error) {
            throw new FalloApi(0, mutacionIncierta, "No pudimos leer la información recibida.");
        }
    }

    String texto(JsonNode nodo, String campo) {
        return texto(nodo, campo, false);
    }

    String texto(JsonNode nodo, String campo, boolean respuestaIncierta) {
        String valor = textoOpcional(nodo, campo);
        if (valor == null) {
            throw new FalloApi(0, respuestaIncierta, "No pudimos cargar toda la información. Inténtalo de nuevo.");
        }
        return valor;
    }

    String textoOpcional(JsonNode nodo, String campo) {
        JsonNode valor = nodo.path(campo);
        return valor.isMissingNode() || valor.isNull() ? null : valor.asText();
    }

    void actualizarTokenCsrf(String token) {
        tokenCsrf = token;
    }

    void limpiarTokenCsrf() {
        tokenCsrf = null;
    }

    private String obtenerTokenCsrf() {
        if (tokenCsrf != null && !tokenCsrf.isBlank()) {
            return tokenCsrf;
        }
        JsonNode respuesta = enviar("GET", RUTA_CSRF, null, Map.of(), false);
        tokenCsrf = texto(respuesta, "token");
        return tokenCsrf;
    }

    private String mensajePorEstado(int estado) {
        return switch (estado) {
            case 400 -> "Revisa la información e inténtalo de nuevo.";
            case 401 -> "Tu acceso venció. Inicia sesión de nuevo.";
            case 403 -> "No pudimos comprobar tu acceso. Vuelve a intentarlo.";
            case 409 -> "La información cambió. Actualiza la pantalla antes de continuar.";
            case 412 -> "La información cambió. Actualiza la pantalla antes de continuar.";
            case 503 -> "Smart Parking no está disponible ahora. Inténtalo de nuevo más tarde.";
            default -> estado >= 500
                    ? "No pudimos confirmar si se guardaron los cambios. Revisa la información antes de intentarlo otra vez."
                    : "No pudimos completar la acción. Inténtalo de nuevo.";
        };
    }

    private String mensajeValidacion(String cuerpo) {
        if (cuerpo == null || cuerpo.isBlank()) {
            return null;
        }
        try {
            JsonNode error = json.readTree(cuerpo);
            if (error == null || !"OPERACION_NO_COMPLETADA".equals(error.path("codigo").asText())) {
                return null;
            }
            String mensaje = error.path("mensaje").asText("").strip();
            return mensaje.isBlank() ? null : mensaje;
        } catch (JsonProcessingException excepcion) {
            return null;
        }
    }

    /**
     * busca la dirección de conexión en la configuración del programa o del entorno
     * acepta conexiones sin cifrar solo a esta computadora y rechaza direcciones con datos de acceso
     */
    static URI leerUrlBase() {
        String valor = System.getProperty("smartparking.api.url");
        if (valor == null || valor.isBlank()) {
            valor = System.getenv("SMARTPARKING_API_URL");
        }
        if (valor == null || valor.isBlank()) {
            throw new IllegalStateException(
                    "No encontramos la dirección de Smart Parking. Revisa la configuración de conexión.");
        }
        URI uri = URI.create(valor.endsWith("/") ? valor : valor + "/");
        if (!"http".equals(uri.getScheme()) && !"https".equals(uri.getScheme())) {
            throw new IllegalArgumentException("La dirección de conexión no es válida.");
        }
        if (uri.getUserInfo() != null || uri.getHost() == null) {
            throw new IllegalArgumentException("La dirección de conexión no es válida.");
        }
        String host = uri.getHost();
        boolean loopback = "localhost".equalsIgnoreCase(host)
                || "127.0.0.1".equals(host)
                || "::1".equals(host)
                || "[::1]".equals(host);
        if ("http".equals(uri.getScheme()) && !loopback) {
            throw new IllegalArgumentException("Esta conexión no es segura. Pide ayuda para configurarla.");
        }
        return uri;
    }
}
