package mx.smartparking.api.rfid1.servicio;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.UUID;

/** Prepara las referencias que permiten reconocer una lectura de tarjeta y evitar que se repita por error. */
final class ClavesRfid1 {

    private ClavesRfid1() {
    }

    static String hashClave(String clave) {
        return HexFormat.of().formatHex(digest("SHA-256", clave.getBytes(StandardCharsets.UTF_8)));
    }

    static String huellaSolicitud(String tipoEntidad, String codigoPersona) {
        byte[] tipo = tipoEntidad.getBytes(StandardCharsets.UTF_8);
        byte[] codigo = codigoPersona.getBytes(StandardCharsets.UTF_8);
        ByteBuffer campos = ByteBuffer.allocate(Integer.BYTES * 2 + tipo.length + codigo.length);
        campos.putInt(tipo.length).put(tipo).putInt(codigo.length).put(codigo);
        return HexFormat.of().formatHex(digest("SHA-256", campos.array()));
    }

    static String huellaUid(String uidCanonico) {
        return HexFormat.of().formatHex(digest("SHA-256", uidCanonico.getBytes(StandardCharsets.US_ASCII)));
    }

    static String uuidV5(String capturaId, String requestId) {
        byte[] nombre = requestId.getBytes(StandardCharsets.US_ASCII);
        byte[] namespace = HexFormat.of().parseHex(capturaId);
        ByteBuffer entrada = ByteBuffer.allocate(namespace.length + nombre.length);
        entrada.put(namespace).put(nombre);
        byte[] hash = digest("SHA-1", entrada.array());
        hash[6] = (byte) ((hash[6] & 0x0f) | 0x50);
        hash[8] = (byte) ((hash[8] & 0x3f) | 0x80);
        ByteBuffer uuid = ByteBuffer.wrap(hash);
        return new UUID(uuid.getLong(), uuid.getLong()).toString();
    }

    private static byte[] digest(String algoritmo, byte[] valor) {
        try {
            return MessageDigest.getInstance(algoritmo).digest(valor);
        } catch (NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException("El algoritmo de huella no está disponible.", excepcion);
        }
    }
}
