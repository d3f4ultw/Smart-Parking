package mx.smartparking.api.persistencia.membresia;

/** Indica los estados que se guardan para un intento de pago y sus actualizaciones recibidas de Stripe. */
public enum EstadoCheckoutPersistido {
    RESERVADO,
    ABIERTO,
    RECONCILIANDO,
    COMPLETADO,
    EXPIRADO,
    FALLIDO,
    INDETERMINADO
}
