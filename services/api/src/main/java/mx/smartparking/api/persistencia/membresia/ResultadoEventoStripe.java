package mx.smartparking.api.persistencia.membresia;

/** Indica qué ocurrió al guardar un aviso cuya procedencia ya se comprobó. */
public enum ResultadoEventoStripe {
    NUEVO,
    DUPLICADO,
    REINTENTAR
}
