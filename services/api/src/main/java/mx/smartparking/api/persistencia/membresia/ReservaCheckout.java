package mx.smartparking.api.persistencia.membresia;

/** Reúne el resultado de preparar un pago, incluidos los casos en que no puede iniciarse. */
public record ReservaCheckout(EstadoReservaCheckout resultado, IntentoCheckoutPersistido intento) {
}
