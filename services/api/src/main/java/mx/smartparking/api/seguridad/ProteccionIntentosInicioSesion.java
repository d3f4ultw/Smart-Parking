package mx.smartparking.api.seguridad;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.stereotype.Component;

/** Limita los intentos fallidos de entrada para cada correo durante un tiempo determinado. */
@Component
public class ProteccionIntentosInicioSesion {

    private static final int MAXIMO_CORREOS = 10_000;
    private static final int MAXIMOS_INTENTOS_FALLIDOS = 5;
    private static final Duration DURACION_VENTANA = Duration.ofMinutes(15);
    private static final Duration DURACION_BLOQUEO = Duration.ofMinutes(15);

    private final Clock reloj;
    private final Map<String, RegistroIntentos> registros = new LinkedHashMap<>(128, 0.75f, true);

    /** Crea la protección usando el reloj del sistema. */
    public ProteccionIntentosInicioSesion() {
        this(Clock.systemUTC());
    }

    ProteccionIntentosInicioSesion(Clock reloj) {
        this.reloj = reloj;
    }

    /** Indica si el correo permanece bloqueado por fallos recientes. */
    public synchronized boolean estaBloqueado(String correoNormalizado) {
        RegistroIntentos registro = registros.get(correoNormalizado);
        if (registro == null) {
            return false;
        }

        Instant ahora = reloj.instant();
        if (registro.bloqueadoHasta() != null) {
            if (ahora.isBefore(registro.bloqueadoHasta())) {
                return true;
            }
            registros.remove(correoNormalizado);
            return false;
        }

        if (!ahora.isBefore(registro.inicioVentana().plus(DURACION_VENTANA))) {
            registros.remove(correoNormalizado);
        }
        return false;
    }

    /** Registra un fallo y activa un bloqueo temporal al alcanzar el límite. */
    public synchronized void registrarFallo(String correoNormalizado) {
        Instant ahora = reloj.instant();
        RegistroIntentos registro = registros.get(correoNormalizado);

        if (registro == null || !ahora.isBefore(registro.inicioVentana().plus(DURACION_VENTANA))) {
            asegurarCapacidad();
            registros.put(correoNormalizado, new RegistroIntentos(ahora, 1, null));
            return;
        }

        int intentos = registro.intentosFallidos() + 1;
        Instant bloqueo = intentos >= MAXIMOS_INTENTOS_FALLIDOS
                ? ahora.plus(DURACION_BLOQUEO)
                : null;
        registros.put(correoNormalizado, new RegistroIntentos(registro.inicioVentana(), intentos, bloqueo));
    }

    /** Olvida los intentos fallidos cuando la persona entra correctamente. */
    public synchronized void registrarExito(String correoNormalizado) {
        registros.remove(correoNormalizado);
    }

    private void asegurarCapacidad() {
        while (registros.size() >= MAXIMO_CORREOS) {
            Iterator<String> iterador = registros.keySet().iterator();
            if (!iterador.hasNext()) {
                return;
            }
            iterador.next();
            iterador.remove();
        }
    }

    private record RegistroIntentos(Instant inicioVentana, int intentosFallidos, Instant bloqueadoHasta) {
    }
}
