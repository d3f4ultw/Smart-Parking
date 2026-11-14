package mx.smartparking.api.activacion;

/** Reúne el resultado de pedir otra invitación y la versión actual de los datos del operador. */
public record ResultadoReemisionInvitacionOperador(
        RespuestaReemisionInvitacionOperador respuesta,
        long revisionAcceso) {
}
