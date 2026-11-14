package mx.smartparking.api.activacion;

/** Indica que se alcanzó el límite de solicitudes para una cuenta y cuánto tiempo debe esperar. */
public final class ErrorLimitacionAccionOperador extends RuntimeException {

    private final String codigo;
    private final long retryAfterSeconds;

    public ErrorLimitacionAccionOperador(String codigo, String mensaje, long retryAfterSeconds) {
        super(mensaje);
        this.codigo = codigo;
        this.retryAfterSeconds = Math.max(1, retryAfterSeconds);
    }

    public String codigo() {
        return codigo;
    }

    public long retryAfterSeconds() {
        return retryAfterSeconds;
    }
}
