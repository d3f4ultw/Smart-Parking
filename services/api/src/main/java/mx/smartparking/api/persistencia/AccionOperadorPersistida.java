package mx.smartparking.api.persistencia;

import java.time.Instant;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;

/** Conserva el resultado de una acción sobre un operador para devolverlo si se repite la solicitud. */
public record AccionOperadorPersistida(
        String operacion,
        Instant creadaEn,
        EstadoEnvioInvitacion estadoEnvio,
        Long revisionAcceso,
        Instant venceEn) {
}
