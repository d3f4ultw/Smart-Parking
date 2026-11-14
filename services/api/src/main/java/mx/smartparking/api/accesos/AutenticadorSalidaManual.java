package mx.smartparking.api.accesos;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Base64;
import java.util.HexFormat;
import java.util.UUID;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Comprueba que los mensajes de salida manual provengan del dispositivo autorizado antes de aceptar
 * una respuesta.
 */
@Component
public final class AutenticadorSalidaManual {
    private static final String DOMINIO = "smartparking.manual.v1";
    private final byte[] clave;

    public AutenticadorSalidaManual(@Value("${smartparking.rfid.salida-manual.clave:}") String claveHex) {
        this.clave = claveHex != null && claveHex.matches("[0-9a-fA-F]{64}")
                ? HexFormat.of().parseHex(claveHex) : null;
    }

    /** Indica si está configurada la clave necesaria para usar la salida manual. */
    public boolean estaHabilitado() { return clave != null; }

    /**
     * Prepara un permiso para una operación concreta, el inicio actual del dispositivo y el
     * comprobante recibido.
     */
    public String firmarEjecucion(UUID operacion, String bootId, String ticketId) {
        if (!estaHabilitado()) { return null; }
        return firmar(DOMINIO + "|EXEC|" + operacionCompacta(operacion) + "|" + bootId + "|" + ticketId);
    }

    /**
     * Comprueba que la respuesta del dispositivo sea válida antes de dar por realizada o rechazada la
     * salida.
     */
    public boolean verificarResultado(UUID operacion, String bootId, String ticketId, String resultado, String firma) {
        if (!estaHabilitado() || firma == null || !firma.matches("[A-Za-z0-9_-]{16}")) { return false; }
        String codigo = switch (resultado) {
            case "EJECUTADA" -> "E";
            case "NO_EJECUTADA" -> "N";
            default -> null;
        };
        if (codigo == null) { return false; }
        String esperada = firmar(DOMINIO + "|RESULT|" + operacionCompacta(operacion) + "|" + bootId
                + "|" + ticketId + "|" + codigo);
        return MessageDigest.isEqual(esperada.getBytes(StandardCharsets.US_ASCII),
                firma.getBytes(StandardCharsets.US_ASCII));
    }

    /** Comprueba si el dispositivo respondió a una solicitud de un solo uso durante su inicio actual. */
    public boolean verificarPrueba(String bootId, String desafioId, String firma) {
        if (!estaHabilitado() || !identificadorCanonico(bootId) || !identificadorCanonico(desafioId)
                || firma == null || !firma.matches("[A-Za-z0-9_-]{16}")) {
            return false;
        }
        String esperada = firmar(DOMINIO + "|PROBE|" + bootId + "|" + desafioId);
        return MessageDigest.isEqual(esperada.getBytes(StandardCharsets.US_ASCII),
                firma.getBytes(StandardCharsets.US_ASCII));
    }

    static boolean identificadorCanonico(String texto) {
        if (texto == null || !texto.matches("[A-Za-z0-9_-]{22}")) { return false; }
        try {
            byte[] bytes = Base64.getUrlDecoder().decode(texto);
            return bytes.length == 16 && Base64.getUrlEncoder().withoutPadding().encodeToString(bytes).equals(texto);
        } catch (IllegalArgumentException excepcion) {
            return false;
        }
    }

    private String firmar(String texto) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(clave, "HmacSHA256"));
            byte[] resultado = Arrays.copyOf(mac.doFinal(texto.getBytes(StandardCharsets.US_ASCII)), 12);
            return Base64.getUrlEncoder().withoutPadding().encodeToString(resultado);
        } catch (GeneralSecurityException excepcion) {
            throw new IllegalStateException("No se pudo autenticar la operación manual.", excepcion);
        }
    }

    private static String operacionCompacta(UUID operacion) {
        byte[] bytes = ByteBuffer.allocate(16).putLong(operacion.getMostSignificantBits())
                .putLong(operacion.getLeastSignificantBits()).array();
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }
}
