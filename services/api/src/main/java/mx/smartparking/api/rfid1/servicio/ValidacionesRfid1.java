package mx.smartparking.api.rfid1.servicio;

import java.util.Locale;
import java.util.regex.Pattern;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import org.springframework.http.HttpStatus;

/** Revisa los identificadores y datos recibidos para las operaciones con el lector de tarjetas. */
final class ValidacionesRfid1 {

    private static final Pattern FORMATO_CAPTURA = Pattern.compile("[0-9a-f]{32}");
    private static final Pattern FORMATO_REQUEST = Pattern.compile("(?i)[0-9a-f]{1,4}");
    private static final Pattern FORMATO_UID = Pattern.compile("(?i)(?:[0-9a-f]{8}|[0-9a-f]{14}|[0-9a-f]{20})");
    private static final Pattern FORMATO_UUID = Pattern.compile(
            "(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}");
    private static final Pattern FORMATO_HUELLA = Pattern.compile("[0-9a-f]{64}");

    private ValidacionesRfid1() {
    }

    static String tipoEntidad(String tipo) {
        if (!"CLIENTE".equals(tipo) && !"EMPLEADO".equals(tipo)) {
            throw error(HttpStatus.BAD_REQUEST, "SOLICITUD_NO_VALIDA", "El tipo de persona no es válido.");
        }
        return tipo;
    }

    static String codigoPersona(String codigo) {
        if (codigo == null || codigo.isBlank() || codigo.length() > 32
                || codigo.codePoints().anyMatch(Character::isISOControl)) {
            throw error(HttpStatus.BAD_REQUEST, "SOLICITUD_NO_VALIDA", "El código de persona no es válido.");
        }
        return codigo.strip();
    }

    static String requestId(String valor) {
        if (valor == null || !FORMATO_REQUEST.matcher(valor).matches()) {
            throw error(HttpStatus.BAD_REQUEST, "LECTURA_NO_VALIDA", "La lectura no es válida.");
        }
        return valor.toUpperCase(Locale.ROOT);
    }

    static String uid(String valor) {
        if (valor == null || !FORMATO_UID.matcher(valor).matches()) {
            throw error(HttpStatus.BAD_REQUEST, "LECTURA_NO_VALIDA", "La lectura no es válida.");
        }
        return valor.toUpperCase(Locale.ROOT);
    }

    static void capturaId(String valor) {
        if (valor == null || !FORMATO_CAPTURA.matcher(valor).matches()) {
            throw error(HttpStatus.BAD_REQUEST, "CAPTURA_ID_NO_VALIDO", "La captura indicada no es válida.");
        }
    }

    static void claveInicio(String clave) {
        if (clave == null || clave.strip().length() < 16 || clave.length() > 200
                || clave.codePoints().anyMatch(Character::isISOControl)) {
            throw error(HttpStatus.BAD_REQUEST, "CLAVE_IDEMPOTENCIA_NO_VALIDA",
                    "No pudimos iniciar la captura. Actualiza la página e inténtalo de nuevo.");
        }
    }

    static void claveLectura(String capturaId, String requestId, String clave) {
        if (clave == null || !FORMATO_UUID.matcher(clave).matches()
                || !ClavesRfid1.uuidV5(capturaId, requestId).equalsIgnoreCase(clave)) {
            throw error(HttpStatus.BAD_REQUEST, "LECTURA_NO_VALIDA", "La lectura no es válida.");
        }
    }

    static void huellaSesion(String huella) {
        if (huella == null || !FORMATO_HUELLA.matcher(huella).matches()) {
            throw error(HttpStatus.UNAUTHORIZED, "SESION_NO_VIGENTE", "Inicia sesión para continuar.");
        }
    }

    private static ErrorConfiguracion error(HttpStatus estado, String codigo, String mensaje) {
        return new ErrorConfiguracion(estado, mensaje, codigo);
    }
}
