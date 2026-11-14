package mx.smartparking.api.clientes.controlador;

import java.net.IDN;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Locale;

/** Revisa y prepara los datos que escribe el cliente antes de registrar su cuenta o permitirle entrar. */
final class ValidadorClientes {

    private static final int MAXIMO_CORREO = 254;
    private static final int MAXIMOS_NOMBRES = 120;
    private static final int MAXIMO_APELLIDO = 80;
    private static final int MINIMOS_PUNTOS_CONTRASENA = 10;
    private static final String INVALIDO = "\u0000";

    private ValidadorClientes() {
    }

    static DatosRegistro validarRegistro(
            String nombres,
            String primerApellido,
            String segundoApellido,
            String correo,
            String contrasena) {
        String nombresLimpios = limpiarTexto(nombres, MAXIMOS_NOMBRES, false);
        String primerApellidoLimpio = limpiarTexto(primerApellido, MAXIMO_APELLIDO, false);
        String segundoApellidoLimpio = limpiarTexto(segundoApellido, MAXIMO_APELLIDO, true);
        if (nombresLimpios == null || primerApellidoLimpio == null || INVALIDO.equals(segundoApellidoLimpio)
                || !correoValido(correo) || !contrasenaValida(contrasena)) {
            return null;
        }
        return new DatosRegistro(nombresLimpios, primerApellidoLimpio, segundoApellidoLimpio);
    }

    static boolean correoValido(String correo) {
        if (correo.isEmpty() || correo.codePointCount(0, correo.length()) > MAXIMO_CORREO) {
            return false;
        }
        int arroba = correo.indexOf('@');
        if (arroba < 1 || arroba != correo.lastIndexOf('@') || arroba > 64 || arroba == correo.length() - 1) {
            return false;
        }
        String local = correo.substring(0, arroba);
        if (local.startsWith(".") || local.endsWith(".") || local.contains("..")
                || local.codePoints().anyMatch(punto -> !esCaracterLocalCorreo(punto))) {
            return false;
        }
        return dominioValido(correo.substring(arroba + 1));
    }

    static boolean contrasenaValida(String contrasena) {
        return contrasena != null
                && contrasena.codePointCount(0, contrasena.length()) >= MINIMOS_PUNTOS_CONTRASENA
                && contrasena.indexOf('\0') < 0;
    }

    static boolean contrasenaActualValida(String contrasena) {
        return contrasena != null && !contrasena.isEmpty() && contrasena.indexOf('\0') < 0;
    }

    static String normalizarCorreo(String correo) {
        return correo == null ? "" : correo.strip().toLowerCase(Locale.ROOT);
    }

    static String crearClaveHash(String correoNormalizado) {
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256")
                    .digest(correoNormalizado.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(hash);
        } catch (NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException("No pudimos completar esto ahora.", excepcion);
        }
    }

    private static String limpiarTexto(String valor, int maximoPuntos, boolean opcional) {
        if (valor == null) {
            return null;
        }
        if (opcional && valor.isBlank()) {
            return null;
        }
        String limpio = valor.strip();
        if (opcional && limpio.isEmpty()) {
            return null;
        }
        boolean valido = !limpio.isBlank() && limpio.codePointCount(0, limpio.length()) <= maximoPuntos
                && limpio.codePoints().noneMatch(Character::isISOControl);
        return valido ? limpio : opcional ? INVALIDO : null;
    }

    private static boolean dominioValido(String dominio) {
        try {
            String ascii = IDN.toASCII(dominio, IDN.USE_STD3_ASCII_RULES);
            if (ascii.length() > 253 || !ascii.contains(".")) {
                return false;
            }
            String[] etiquetas = ascii.split("\\.", -1);
            if (etiquetas.length < 2 || etiquetas[etiquetas.length - 1].length() < 2) {
                return false;
            }
            for (String etiqueta : etiquetas) {
                if (etiqueta.isEmpty() || etiqueta.length() > 63
                        || !etiqueta.matches("[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")) {
                    return false;
                }
            }
            return true;
        } catch (IllegalArgumentException excepcion) {
            return false;
        }
    }

    private static boolean esCaracterLocalCorreo(int punto) {
        return punto >= 'a' && punto <= 'z' || punto >= '0' && punto <= '9'
                || ".!#$%&'*+/=?^_`{|}~-".indexOf(punto) >= 0;
    }

    record DatosRegistro(String nombres, String primerApellido, String segundoApellido) {
    }
}
