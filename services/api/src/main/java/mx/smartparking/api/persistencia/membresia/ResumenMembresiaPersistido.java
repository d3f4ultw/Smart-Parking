package mx.smartparking.api.persistencia.membresia;

import java.time.Instant;
import java.util.UUID;

/** Reúne los datos guardados de la membresía actual o de la última que tuvo el cliente. */
public record ResumenMembresiaPersistido(
        String estado,
        Instant periodoInicio,
        Instant periodoFin,
        Instant siguienteCobroEn,
        boolean cancelacionAlFinal,
        boolean puedeComprar,
        UUID intentoCheckoutPendienteId,
        String estadoCheckoutPendiente,
        Instant checkoutExpiraEn) {
}
