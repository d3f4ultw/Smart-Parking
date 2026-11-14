package mx.smartparking.api.seguridad.rfid1;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.regex.Pattern;

/** Comprueba que el lector presente el código de acceso autorizado sin guardar ese código directamente. */
public final class AutenticadorDispositivoRfid1 {

    private static final Pattern HASH_SHA256 = Pattern.compile("[0-9a-fA-F]{64}");

    private final byte[] hashTokenConfigurado;

    public AutenticadorDispositivoRfid1(String hashTokenConfigurado) {
        this.hashTokenConfigurado = decodificarHash(hashTokenConfigurado);
    }

    /** Indica si el lector cuenta con los datos necesarios para comprobar su acceso. */
    public boolean estaHabilitado() {
        return hashTokenConfigurado != null;
    }

    /** Compara de forma protegida el código recibido con el configurado para el lector. */
    public boolean autenticar(String token) {
        if (!estaHabilitado() || token == null || token.isEmpty()) {
            return false;
        }
        byte[] hashRecibido = sha256(token.getBytes(StandardCharsets.UTF_8));
        return MessageDigest.isEqual(hashTokenConfigurado, hashRecibido);
    }

    private static byte[] decodificarHash(String texto) {
        if (texto == null || !HASH_SHA256.matcher(texto).matches()) {
            return null;
        }
        return HexFormat.of().parseHex(texto);
    }

    private static byte[] sha256(byte[] valor) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(valor);
        } catch (NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException("SHA-256 no está disponible.", excepcion);
        }
    }
}
