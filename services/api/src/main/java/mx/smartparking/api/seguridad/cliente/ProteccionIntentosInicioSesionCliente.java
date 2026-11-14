package mx.smartparking.api.seguridad.cliente;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.stereotype.Component;

/**
 * Limita los intentos de entrada del cliente sin guardar su correo ni compartir el límite con el
 * propietario.
 */
@Component
public final class ProteccionIntentosInicioSesionCliente {

    private static final int MAXIMO_CLAVES = 10_000;
    private static final int MAXIMOS_FALLOS = 5;
    private static final Duration VENTANA = Duration.ofMinutes(15);
    private static final Duration BLOQUEO = Duration.ofMinutes(15);

    private final Clock reloj;
    private final Map<String, RegistroIntentos> registros = new LinkedHashMap<>(128, 0.75f, true);

    public ProteccionIntentosInicioSesionCliente() {
        this(Clock.systemUTC());
    }

    ProteccionIntentosInicioSesionCliente(Clock reloj) {
        this.reloj = reloj;
    }

    /** Indica si se han bloqueado temporalmente los intentos de entrada por fallos recientes. */
    public synchronized boolean estaBloqueado(String claveCorreoHash) {
        RegistroIntentos registro = registros.get(claveCorreoHash);
        if (registro == null) {
            return false;
        }
        Instant ahora = reloj.instant();
        if (registro.bloqueadoHasta() != null) {
            if (ahora.isBefore(registro.bloqueadoHasta())) {
                return true;
            }
            registros.remove(claveCorreoHash);
            return false;
        }
        if (!ahora.isBefore(registro.inicioVentana().plus(VENTANA))) {
            registros.remove(claveCorreoHash);
        }
        return false;
    }

    /** Registra el fallo y bloquea temporalmente nuevos intentos al llegar al quinto. */
    public synchronized void registrarFallo(String claveCorreoHash) {
        Instant ahora = reloj.instant();
        RegistroIntentos anterior = registros.get(claveCorreoHash);
        if (anterior == null || !ahora.isBefore(anterior.inicioVentana().plus(VENTANA))) {
            asegurarCapacidad();
            registros.put(claveCorreoHash, new RegistroIntentos(ahora, 1, null));
            return;
        }
        int fallos = anterior.fallos() + 1;
        Instant bloqueadoHasta = fallos >= MAXIMOS_FALLOS ? ahora.plus(BLOQUEO) : null;
        registros.put(claveCorreoHash, new RegistroIntentos(anterior.inicioVentana(), fallos, bloqueadoHasta));
    }

    /** Olvida los intentos fallidos cuando el cliente entra correctamente. */
    public synchronized void registrarExito(String claveCorreoHash) {
        registros.remove(claveCorreoHash);
    }

    private void asegurarCapacidad() {
        while (registros.size() >= MAXIMO_CLAVES) {
            Iterator<String> iterador = registros.keySet().iterator();
            if (!iterador.hasNext()) {
                return;
            }
            iterador.next();
            iterador.remove();
        }
    }

    private record RegistroIntentos(Instant inicioVentana, int fallos, Instant bloqueadoHasta) {
    }
}
