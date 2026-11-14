package mx.smartparking.api.seguridad;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/**
 * Prepara una referencia para relacionar una lectura de tarjeta con su sesión sin guardar el
 * identificador original.
 */
public final class HuellaSesionPropietario {

    private HuellaSesionPropietario() {
    }

    /** Calcula una referencia protegida de la sesión sin guardar ni devolver su identificador original. */
    public static String calcular(String idSesion) {
        if (idSesion == null || idSesion.isBlank()) {
            throw new IllegalArgumentException("Se requiere una sesión vigente.");
        }
        try {
            byte[] bytes = idSesion.getBytes(StandardCharsets.UTF_8);
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException("No pudimos completar la acción en este momento.", excepcion);
        }
    }
}
