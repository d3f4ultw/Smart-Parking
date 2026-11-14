package mx.smartparking.api.vision;

import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.vision.ContratosVision.*;
import org.springframework.http.HttpStatus;
import tools.jackson.databind.JsonNode;

/** Comprueba el formato de los datos enviados por la cámara sin aceptar valores de otro tipo por accidente. */
final class ParseadorVision {
    private ParseadorVision() { }

    static SolicitudFuente fuente(JsonNode cuerpo) {
        return new SolicitudFuente(uuid(objeto(cuerpo), "fuenteId", false));
    }

    static SolicitudCalibracion calibracion(JsonNode cuerpo) {
        JsonNode raiz = objeto(cuerpo);
        List<ZonaConfiguracion> zonas = new ArrayList<>();
        for (JsonNode elemento : arreglo(raiz, "zonas")) {
            JsonNode zona = objeto(elemento);
            zonas.add(new ZonaConfiguracion(uuid(zona, "visionZoneId", false),
                    texto(zona, "etiqueta"), uuid(zona, "cajonId", true)));
        }
        return new SolicitudCalibracion(List.copyOf(zonas));
    }

    static SolicitudSesion sesion(JsonNode cuerpo) {
        JsonNode raiz = objeto(cuerpo);
        return new SolicitudSesion(uuid(raiz, "fuenteId", false), uuid(raiz, "solicitudId", false),
                instante(raiz, "iniciadaEn"));
    }

    static SolicitudObservacion observacion(JsonNode cuerpo) {
        JsonNode raiz = objeto(cuerpo);
        List<ZonaObservacion> zonas = new ArrayList<>();
        for (JsonNode elemento : arreglo(raiz, "zonas")) {
            JsonNode zona = objeto(elemento);
            zonas.add(new ZonaObservacion(uuid(zona, "visionZoneId", false), texto(zona, "estado")));
        }
        return new SolicitudObservacion(uuid(raiz, "fuenteId", false), uuid(raiz, "sesionId", false),
                entero(raiz, "secuencia"), uuid(raiz, "solicitudId", false),
                instante(raiz, "observadoEn"), List.copyOf(zonas));
    }

    private static JsonNode objeto(JsonNode nodo) {
        if (nodo == null || !nodo.isObject()) {
            throw invalida();
        }
        return nodo;
    }

    private static JsonNode arreglo(JsonNode nodo, String nombre) {
        JsonNode valor = nodo.get(nombre);
        if (valor == null || !valor.isArray() || valor.size() < 1 || valor.size() > 1000) {
            throw invalida();
        }
        return valor;
    }

    private static String texto(JsonNode nodo, String nombre) {
        JsonNode valor = nodo.get(nombre);
        if (valor == null || !valor.isTextual()) {
            throw invalida();
        }
        return valor.textValue();
    }

    private static long entero(JsonNode nodo, String nombre) {
        JsonNode valor = nodo.get(nombre);
        if (valor == null || !valor.isIntegralNumber() || !valor.canConvertToLong()) {
            throw invalida();
        }
        return valor.longValue();
    }

    private static UUID uuid(JsonNode nodo, String nombre, boolean opcional) {
        JsonNode valor = nodo.get(nombre);
        if (opcional && (valor == null || valor.isNull())) {
            return null;
        }
        String texto = texto(nodo, nombre);
        if (!texto.matches("(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")) {
            throw invalida();
        }
        try {
            return UUID.fromString(texto);
        } catch (IllegalArgumentException excepcion) {
            throw invalida();
        }
    }

    private static Instant instante(JsonNode nodo, String nombre) {
        try {
            return Instant.parse(texto(nodo, nombre));
        } catch (DateTimeParseException excepcion) {
            throw invalida();
        }
    }

    private static ErrorConfiguracion invalida() {
        return new ErrorConfiguracion(HttpStatus.BAD_REQUEST, "La solicitud de Vision no es válida.", "VISION_INVALIDA");
    }
}
