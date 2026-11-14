package mx.smartparking.api.persistencia.membresia;

/** Indica si el cliente puede iniciar el pago y si esa solicitud ya se había recibido. */
public enum EstadoReservaCheckout {
    NUEVA,
    REPLAY,
    IDEMPOTENCIA_REUTILIZADA,
    MEMBRESIA_NO_ELEGIBLE,
    CHECKOUT_PENDIENTE,
    LIMITE_ALCANZADO
}
