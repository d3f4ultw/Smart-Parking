package mx.smartparking.api.activacion;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.stereotype.Component;

/** Limita los intentos fallidos con un mismo enlace y evita guardar el código original. */
@Component
public final class ProteccionIntentosActivacion {

    private static final int MAXIMO_FALLOS = 5;
    private static final int MAXIMO_TOKENS = 10_000;
    private static final Duration VENTANA = Duration.ofMinutes(15);
    private static final Duration BLOQUEO = Duration.ofMinutes(15);

    private final Map<String, EstadoIntentos> intentos = new LinkedHashMap<>(128, 0.75f, true);
    private final Clock reloj;

    public ProteccionIntentosActivacion() {
        this(Clock.systemUTC());
    }

    ProteccionIntentosActivacion(Clock reloj) {
        this.reloj = reloj;
    }

    /**
     * Indica si todavía se permite usar el enlace de invitación o recuperación después de los intentos
     * anteriores.
     */
    public synchronized boolean permitido(String tokenHash) {
        Instant ahora = reloj.instant();
        limpiarExpirados(ahora);
        EstadoIntentos estado = intentos.get(tokenHash);
        if (estado == null) {
            return true;
        }
        if (estado.bloqueadoHasta() != null) {
            return false;
        }
        return ahora.isBefore(estado.inicioVentana().plus(VENTANA));
    }

    /** Cuenta un rechazo y bloquea durante quince minutos al quinto fallo. */
    public synchronized void registrarFallo(String tokenHash) {
        Instant ahora = reloj.instant();
        limpiarExpirados(ahora);
        EstadoIntentos estado = intentos.get(tokenHash);
        if (estado != null && estado.bloqueadoHasta() != null
                && ahora.isBefore(estado.bloqueadoHasta())) {
            return;
        }
        if (estado == null || !ahora.isBefore(estado.inicioVentana().plus(VENTANA))) {
            estado = new EstadoIntentos(ahora, 0, null);
        }
        int fallos = estado.fallos() + 1;
        Instant bloqueoHasta = fallos >= MAXIMO_FALLOS ? ahora.plus(BLOQUEO) : null;
        intentos.put(tokenHash, new EstadoIntentos(estado.inicioVentana(), fallos, bloqueoHasta));
        while (intentos.size() > MAXIMO_TOKENS) {
            Iterator<String> iterador = intentos.keySet().iterator();
            if (iterador.hasNext()) {
                iterador.next();
                iterador.remove();
            }
        }
    }

    /** Olvida los intentos fallidos cuando la persona completa correctamente la acción del enlace. */
    public synchronized void registrarExito(String tokenHash) {
        intentos.remove(tokenHash);
    }

    private void limpiarExpirados(Instant ahora) {
        intentos.entrySet().removeIf(entrada -> {
            EstadoIntentos estado = entrada.getValue();
            if (estado.bloqueadoHasta() != null) {
                return !ahora.isBefore(estado.bloqueadoHasta());
            }
            return !ahora.isBefore(estado.inicioVentana().plus(VENTANA));
        });
    }

    private record EstadoIntentos(Instant inicioVentana, int fallos, Instant bloqueadoHasta) {
    }
}
