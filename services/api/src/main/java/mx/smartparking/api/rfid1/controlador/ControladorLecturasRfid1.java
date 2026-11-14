package mx.smartparking.api.rfid1.controlador;

import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Pattern;
import mx.smartparking.api.configuracion.ErrorConfiguracionControlador.RespuestaError;
import mx.smartparking.api.rfid1.modelo.RespuestaLecturaRfid1;
import mx.smartparking.api.rfid1.servicio.ServicioRfid1;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.http.converter.HttpMessageNotReadableException;
import tools.jackson.databind.JsonNode;

/** Recibe mensajes de lectura del dispositivo sin asociar tarjetas ni cambiar la información de personas. */
@RestController
@RequestMapping("/api/v1/dispositivos/rfid-1/lecturas")
public final class ControladorLecturasRfid1 {

    private static final Pattern UID_HEXADECIMAL = Pattern.compile("(?i)(?:[0-9a-f]{8}|[0-9a-f]{14}|[0-9a-f]{20})");
    private static final Pattern FORMATO_UUID = Pattern.compile(
            "(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}");
    private static final long MAXIMA_SECUENCIA = 65_535L;
    private static final String ERROR_LECTURA = "LECTURA_NO_VALIDA";
    private static final String MENSAJE_LECTURA = "La lectura no es válida.";
    private final ServicioRfid1 servicio;

    public ControladorLecturasRfid1(ServicioRfid1 servicio) {
        this.servicio = servicio;
    }

    /** Recibe una lectura válida sin registrar por ello una entrada, salida o asociación de tarjeta. */
    @PostMapping
    public ResponseEntity<?> recibir(
            @RequestHeader(value = "Idempotency-Key", required = false) String claveIdempotencia,
            @RequestBody(required = false) JsonNode cuerpo) {
        if (esLecturaCapturada(cuerpo)) {
            return recibirLecturaCapturada(claveIdempotencia, cuerpo);
        }
        LecturaNormalizada lectura = normalizar(cuerpo);
        if (!claveIdempotenciaValida(claveIdempotencia) || lectura == null) {
            return respuestaInvalida();
        }

        return ResponseEntity.accepted()
                .headers(encabezadosPrivados())
                .body(Map.of("estado", "RECIBIDA", "accion", "NINGUNA"));
    }

    private ResponseEntity<?> recibirLecturaCapturada(String claveIdempotencia, JsonNode cuerpo) {
        RespuestaLecturaRfid1 resultado = servicio.procesarLectura(
                texto(cuerpo, "capturaId"), texto(cuerpo, "requestId"), texto(cuerpo, "uid"), claveIdempotencia);
        return ResponseEntity.ok().headers(encabezadosPrivados()).body(resultado);
    }

    private static boolean esLecturaCapturada(JsonNode cuerpo) {
        return cuerpo != null && cuerpo.isObject()
                && (cuerpo.has("capturaId") || cuerpo.has("requestId"));
    }

    private static String texto(JsonNode cuerpo, String campo) {
        JsonNode valor = cuerpo.get(campo);
        return valor == null || !valor.isTextual() ? null : valor.textValue();
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<RespuestaError> jsonNoValido() {
        return respuestaInvalida();
    }

    private static LecturaNormalizada normalizar(JsonNode cuerpo) {
        if (cuerpo == null || !cuerpo.isObject()) {
            return null;
        }
        JsonNode secuencia = cuerpo.get("secuencia");
        JsonNode uid = cuerpo.get("uid");
        if (secuencia == null || !secuencia.isIntegralNumber() || !secuencia.canConvertToLong()
                || secuencia.longValue() < 0 || secuencia.longValue() > MAXIMA_SECUENCIA
                || uid == null || !uid.isTextual()) {
            return null;
        }
        String uidTexto = uid.textValue();
        if (uidTexto == null || !UID_HEXADECIMAL.matcher(uidTexto).matches()) {
            return null;
        }
        return new LecturaNormalizada(secuencia.longValue(), uidTexto.toUpperCase(Locale.ROOT));
    }

    private static boolean claveIdempotenciaValida(String clave) {
        if (clave == null || !FORMATO_UUID.matcher(clave).matches()) {
            return false;
        }
        try {
            UUID.fromString(clave);
            return true;
        } catch (IllegalArgumentException excepcion) {
            return false;
        }
    }

    private static ResponseEntity<RespuestaError> respuestaInvalida() {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .headers(encabezadosPrivados())
                .body(new RespuestaError(ERROR_LECTURA, MENSAJE_LECTURA));
    }

    private static HttpHeaders encabezadosPrivados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.set(HttpHeaders.CACHE_CONTROL, "no-store, private");
        encabezados.set(HttpHeaders.VARY, HttpHeaders.AUTHORIZATION);
        return encabezados;
    }

    private record LecturaNormalizada(long secuencia, String uid) {
    }
}
