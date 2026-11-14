package mx.smartparking.api.rfid2;

import java.util.concurrent.TimeUnit;
import java.util.function.LongSupplier;
import org.springframework.dao.DataAccessResourceFailureException;

/**
 * Controla el tiempo disponible para decidir una entrada, desde la consulta de configuración hasta que
 * se guarda el resultado.
 */
public final class PlazoEntradaRfid2 {
    private static final long DURACION_NANOS = TimeUnit.SECONDS.toNanos(2);
    private final LongSupplier reloj;
    private final long inicio;

    public PlazoEntradaRfid2() {
        this(System::nanoTime);
    }

    public PlazoEntradaRfid2(LongSupplier reloj) {
        this.reloj = reloj;
        this.inicio = reloj.getAsLong();
    }

    /** Indica cuánto tiempo queda para decidir la entrada y rechaza la operación cuando el plazo terminó. */
    public long milisegundosRestantes() {
        long restante = DURACION_NANOS - (reloj.getAsLong() - inicio);
        if (restante < TimeUnit.MILLISECONDS.toNanos(1)) {
            throw new DataAccessResourceFailureException("El plazo para confirmar la entrada terminó.");
        }
        return TimeUnit.NANOSECONDS.toMillis(restante);
    }
}
