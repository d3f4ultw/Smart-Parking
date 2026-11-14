package mx.smartparking.api.clientes.membresia.modelo;

import java.time.Instant;
import java.util.UUID;

/** Reúne el pago que el cliente inició y que todavía está pendiente. */
public record CheckoutPendientePortal(UUID intentoId, String estado, Instant expiraEn) {
}
