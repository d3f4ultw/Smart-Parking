package mx.smartparking.api.correo;

import mx.smartparking.api.activacion.EstadoEnvioInvitacion;

/** Define cómo se envía por correo una invitación para activar una cuenta de operador. */
public interface NotificadorInvitacionOperador {

    /** Indica si el envío de correos está habilitado. */
    boolean estaHabilitado();

    /**
     * Intenta enviar la invitación una sola vez y devuelve el resultado sin interrumpir la operación
     * si falla el correo.
     */
    EstadoEnvioInvitacion enviar(String correo, String enlaceActivacion);
}
