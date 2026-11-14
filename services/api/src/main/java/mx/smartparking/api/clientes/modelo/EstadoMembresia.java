package mx.smartparking.api.clientes.modelo;

/**
 * Indica si una membresía está pendiente, activa, con un pago vencido, cancelada o inactiva,
 * o si el cliente todavía no tiene una.
 */
public enum EstadoMembresia {
    SIN_MEMBRESIA,
    PENDIENTE,
    ACTIVA,
    PAGO_VENCIDO,
    CANCELADA,
    INACTIVA
}
