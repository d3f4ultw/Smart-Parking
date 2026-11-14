package mx.smartparking.api.activacion;

/** Indica qué ocurrió al intentar enviar una sola vez la invitación actual por correo. */
public enum EstadoEnvioInvitacion {
    ENVIANDO,
    ENVIADO,
    FALLIDO,
    DESCONOCIDO,
    DESHABILITADO
}
