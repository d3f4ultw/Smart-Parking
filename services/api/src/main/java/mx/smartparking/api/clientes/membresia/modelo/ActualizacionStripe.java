package mx.smartparking.api.clientes.membresia.modelo;

import java.time.Instant;
import java.util.UUID;

/**
 * Reúne los datos recibidos de Stripe después de comprobar que corresponden al cliente y al precio
 * guardados.
 */
public record ActualizacionStripe(
        String eventId,
        String eventType,
        Instant eventCreatedEn,
        String sessionId,
        UUID intentoId,
        String customerId,
        String subscriptionId,
        UUID clienteId,
        String priceId,
        String estadoSuscripcionStripe,
        String invoiceId,
        String estadoFacturaStripe,
        Instant periodoInicio,
        Instant periodoFin,
        boolean cancelAtPeriodEnd,
        Instant recibidoEn,
        boolean aplicable) {
}
