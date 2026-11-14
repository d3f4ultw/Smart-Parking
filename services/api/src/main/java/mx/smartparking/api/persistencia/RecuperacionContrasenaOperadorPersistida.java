package mx.smartparking.api.persistencia;

import java.time.Instant;
import java.util.UUID;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;

/** Reúne el estado de una recuperación de contraseña sin guardar el código original del enlace. */
public record RecuperacionContrasenaOperadorPersistida(
        UUID operadorId,
        String tokenHash,
        Instant generadoEn,
        Instant venceEn,
        Instant consumidoEn,
        EstadoEnvioInvitacion estadoEnvio,
        Instant intentoIniciadoEn) {
}
