package mx.smartparking.api.clientes.membresia.modelo;

import java.time.Instant;
import java.util.UUID;

/** Contiene el estado de un pago que solo puede consultar el cliente que lo inició. */
public record RespuestaEstadoCheckoutMembresia(
        UUID intentoId,
        String estado,
        String checkoutUrl,
        Instant expiraEn) {
}
