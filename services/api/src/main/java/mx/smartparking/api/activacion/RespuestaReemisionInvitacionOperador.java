package mx.smartparking.api.activacion;

import java.time.Instant;

/** Indica al propietario qué ocurrió al pedir una nueva invitación para el operador. */
public record RespuestaReemisionInvitacionOperador(
        EstadoEnvioInvitacion estadoInvitacion,
        boolean puedeReemitirInvitacion,
        Instant reenvioDisponibleEn) {
}
