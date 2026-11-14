package mx.smartparking.api.clientes.membresia.servicio;

/**
 * Comunica que Stripe no pudo completar una operación sin mostrar al cliente detalles internos de la
 * respuesta.
 */
public final class StripeMembresiaException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    public StripeMembresiaException(String mensaje, Throwable causa) {
        super(mensaje, causa);
    }

    public StripeMembresiaException(String mensaje) {
        super(mensaje);
    }
}
