package mx.smartparking.api.clientes.membresia.modelo;

/** Indica si se preparó un pago nuevo o si se devolvió el resultado de una solicitud repetida. */
public record ResultadoInicioCheckout(boolean nuevo, RespuestaCheckoutMembresia respuesta) {
}
