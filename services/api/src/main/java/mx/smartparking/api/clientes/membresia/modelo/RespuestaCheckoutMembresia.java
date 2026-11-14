package mx.smartparking.api.clientes.membresia.modelo;

import java.time.Instant;
import java.util.UUID;

/** Contiene la respuesta al comenzar un pago o repetir la misma solicitud. */
public record RespuestaCheckoutMembresia(
        UUID intentoId,
        String estado,
        String checkoutUrl,
        Instant expiraEn) {
}
