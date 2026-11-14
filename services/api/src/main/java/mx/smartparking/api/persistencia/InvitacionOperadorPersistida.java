package mx.smartparking.api.persistencia;

import java.time.Instant;
import java.util.UUID;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;

/**
 * Reúne el identificador del operador, las fechas de la invitación y el estado de su envío.
 * Conserva una forma protegida de comprobar el enlace sin guardar su código original.
 */
public record InvitacionOperadorPersistida(
        UUID operadorId,
        String tokenHash,
        Instant generadoEn,
        Instant venceEn,
        Instant consumidoEn,
        EstadoEnvioInvitacion estadoEnvio,
        Instant intentoIniciadoEn) {
}
