package mx.smartparking.api.persistencia.membresia;

import java.time.Instant;
import java.util.UUID;

/** Guarda la relación entre un cliente y su cuenta de prueba en Stripe. */
public record ClienteStripePersistido(UUID clienteId, String customerId, String estado, Instant actualizadaEn) {
}
