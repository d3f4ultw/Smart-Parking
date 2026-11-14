package mx.smartparking.ownerconsole.controlador.configuracion;

/** prepara mensajes que informan si se pudo enviar el correo después de guardar los cambios. */
public final class MensajesAvisoCorreo {

    private MensajesAvisoCorreo() {}

    public static String describir(String estado) {
        if (estado == null || estado.isBlank()) {
            estado = "DESCONOCIDO";
        }
        return switch (estado) {
            case "ENVIADO" -> "Se guardaron los cambios. El aviso se envió.";
            case "FALLIDO" -> "Se guardaron los cambios, pero no se pudo enviar el aviso.";
            case "DESHABILITADO" -> "Se guardaron los cambios. No se pudo enviar el aviso.";
            case "DESCONOCIDO" -> "Se guardaron los cambios. No pudimos saber si enviamos el aviso; no lo volveremos a enviar por nuestra cuenta.";
            default -> "Se guardaron los cambios, pero no pudimos confirmar el envío del aviso.";
        };
    }

    public static String describirBienvenida(String estado) {
        if (estado == null || estado.isBlank()) {
            estado = "DESCONOCIDO";
        }
        return switch (estado) {
            case "ENVIADO" -> "La configuración está lista y ya puedes entrar. "
                    + "Revisa tu correo para encontrar el mensaje de bienvenida.";
            case "FALLIDO" -> "La configuración está lista y ya puedes entrar, pero no pudimos enviar "
                    + "el mensaje de bienvenida.";
            case "DESHABILITADO" -> "La configuración está lista y ya puedes entrar. "
                    + "El mensaje de bienvenida no se envió.";
            case "DESCONOCIDO" -> "La configuración está lista y ya puedes entrar. "
                    + "Si no encuentras el mensaje de bienvenida, revisa el correo no deseado.";
            default -> "La configuración está lista y ya puedes entrar. "
                    + "Si no recibes el mensaje de bienvenida, revisa tu correo no deseado.";
        };
    }
}
