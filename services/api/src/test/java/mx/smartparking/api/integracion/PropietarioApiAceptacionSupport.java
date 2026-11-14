package mx.smartparking.api.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;
import java.io.IOException;
import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.HttpCookie;
import java.net.InetAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Utilidades compartidas por la aceptación HTTP de propietario. */
final class PropietarioApiAceptacionSupport {

    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final String ESTADO = "/api/v1/configuracion/estado";

    static URI baseUrlOptIn() throws Exception {
        String baseConfigurada = System.getProperty("smartparking.api-url");
        boolean ambienteDescartable = Boolean.parseBoolean(
                System.getProperty("smartparking.integration.disposable", "false"));
        assumeTrue(ambienteDescartable,
                "Aceptación omitida: requiere smartparking.integration.disposable=true.");
        assertTrue(baseConfigurada != null && !baseConfigurada.isBlank(),
                "La aceptación descartable requiere smartparking.api-url.");

        URI base;
        try {
            base = URI.create(baseConfigurada.strip());
        } catch (IllegalArgumentException excepcion) {
            throw new AssertionError("La URL configurada para aceptación no es válida.");
        }
        assertTrue("http".equalsIgnoreCase(base.getScheme()) || "https".equalsIgnoreCase(base.getScheme()),
                "La URL debe usar HTTP(S) loopback.");
        assertTrue(base.getHost() != null, "La URL debe tener host.");
        assertTrue(base.getUserInfo() == null && base.getQuery() == null && base.getFragment() == null,
                "La URL no debe contener credenciales, consulta ni fragmento.");
        assertTrue(base.getPath().isEmpty() || "/".equals(base.getPath()),
                "La URL base debe apuntar a la raíz de la API.");
        InetAddress[] direcciones = InetAddress.getAllByName(base.getHost());
        assertTrue(direcciones.length > 0 && Arrays.stream(direcciones).allMatch(InetAddress::isLoopbackAddress),
                "La API de aceptación solo puede estar expuesta en loopback.");
        return base;
    }

    static Map<String, Object> configuracion(
            String correo,
            String contrasenaAcceso,
            String contrasenaAdministrativa,
            String nombreEstacionamiento) {
        Map<String, Object> horario = Map.of(
                "modo", "INTERVALO_DIARIO",
                "zonaHoraria", "America/Mexico_City",
                "horaApertura", "22:00",
                "horaCierre", "06:00");
        Map<String, Object> propietario = Map.of(
                "nombres", "Propietario de prueba",
                "primerApellido", "Fase",
                "segundoApellido", "Tres",
                "correo", correo,
                "contrasenaAcceso", contrasenaAcceso,
                "contrasenaAdministrativa", contrasenaAdministrativa);
        Map<String, Object> estacionamiento = Map.of(
                "nombre", nombreEstacionamiento,
                "tipo", "PUBLICO",
                "horario", horario);
        return Map.of("propietario", propietario, "estacionamiento", estacionamiento);
    }

    static String clave(String base) {
        return base + "-" + UUID.randomUUID();
    }

    static void assertEstado(ApiCliente api, String estadoEsperado) throws Exception {
        HttpResponse<String> respuesta = api.get(ESTADO);
        assertEquals(200, respuesta.statusCode());
        JsonNode cuerpo = leerJson(respuesta.body());
        assertEquals(1, cuerpo.size());
        assertEquals(estadoEsperado, texto(cuerpo, "estado"));
    }

    static void assertAviso(JsonNode cuerpo, String campo) {
        String aviso = texto(cuerpo, campo);
        assertTrue(Set.of("ENVIADO", "FALLIDO", "DESHABILITADO", "DESCONOCIDO").contains(aviso),
                "La transición debe indicar el resultado del único intento de correo.");
    }

    static void verificarSinSecretos(String cuerpo, String... secretos) {
        boolean exponeSecreto = Arrays.stream(secretos)
                .filter(secreto -> secreto != null && !secreto.isBlank())
                .anyMatch(cuerpo::contains);
        assertFalse(exponeSecreto, "La respuesta HTTP no debe devolver credenciales ni grants.");
    }

    static void verificarCorreoSinSecretos(String cuerpo, String... secretos) {
        boolean exponeSecreto = Arrays.stream(secretos)
                .filter(secreto -> secreto != null && !secreto.isBlank())
                .anyMatch(cuerpo::contains);
        assertFalse(exponeSecreto, "El correo no debe contener credenciales ni grants.");
    }

    static JsonNode leerJson(String cuerpo) throws IOException {
        return JSON.readTree(cuerpo);
    }

    static String texto(JsonNode nodo, String campo) {
        return nodo.path(campo).asText("");
    }

    static long numero(JsonNode nodo, String campo) {
        return nodo.path(campo).asLong(-1);
    }

    static String etag(HttpResponse<String> respuesta) {
        return respuesta.headers().firstValue("ETag")
                .orElseThrow(() -> new AssertionError("La respuesta debe incluir ETag."));
    }


}
