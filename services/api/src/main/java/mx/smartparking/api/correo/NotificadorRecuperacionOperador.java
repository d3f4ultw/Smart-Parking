package mx.smartparking.api.correo;

import mx.smartparking.api.activacion.EstadoEnvioInvitacion;

/** Permite enviar también un enlace para que el operador recupere su contraseña. */
public interface NotificadorRecuperacionOperador extends NotificadorInvitacionOperador {

    /** Intenta enviar un único enlace para que el operador establezca su contraseña. */
    EstadoEnvioInvitacion enviarRecuperacion(String correo, String enlaceRecuperacion);
}
