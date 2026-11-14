package mx.smartparking.api.activacion;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.HexFormat;
import java.util.regex.Pattern;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import org.springframework.http.HttpStatus;

/** Crea códigos difíciles de adivinar y guarda solo una huella que no permite recuperar el código original. */
public final class SeguridadTokensOperador {

    private static final int BYTES_TOKEN = 32;
    private static final Pattern FORMATO_TOKEN = Pattern.compile("^[A-Za-z0-9_-]{43}$");

    private SeguridadTokensOperador() {
    }

    public static String crearToken(SecureRandom aleatorio) {
        byte[] bytes = new byte[BYTES_TOKEN];
        aleatorio.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    public static String hash(String secreto) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(secreto.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException("No pudimos completar la acción en este momento.", excepcion);
        }
    }

    public static boolean hashesIguales(String esperado, String presentado) {
        return esperado != null && presentado != null && MessageDigest.isEqual(
                esperado.getBytes(StandardCharsets.US_ASCII), presentado.getBytes(StandardCharsets.US_ASCII));
    }

    public static boolean tokenTieneFormato(String token) {
        if (token == null || !FORMATO_TOKEN.matcher(token).matches()) {
            return false;
        }
        try {
            return Base64.getUrlDecoder().decode(token).length == BYTES_TOKEN;
        } catch (IllegalArgumentException excepcion) {
            return false;
        }
    }

    public static String hashClaveIdempotencia(String clave) {
        if (clave == null || clave.strip().length() < 16 || clave.length() > 200
                || clave.codePoints().anyMatch(Character::isISOControl)) {
            throw new ErrorConfiguracion(HttpStatus.BAD_REQUEST, "No pudimos completar esta acción. Inténtalo de nuevo.",
                    "CLAVE_IDEMPOTENCIA_NO_VALIDA");
        }
        return hash(clave);
    }
}
