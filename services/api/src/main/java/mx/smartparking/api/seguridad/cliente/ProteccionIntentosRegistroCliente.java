package mx.smartparking.api.seguridad.cliente;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.stereotype.Component;

/** Limita las solicitudes de registro relacionadas con un mismo correo sin guardar ese correo. */
@Component
public final class ProteccionIntentosRegistroCliente {

    private static final int MAXIMO_CLAVES = 10_000;
    private static final int MAXIMAS_SOLICITUDES = 5;
    private static final Duration VENTANA = Duration.ofMinutes(15);
    private static final Duration BLOQUEO = Duration.ofMinutes(15);

    private final Clock reloj;
    private final Map<String, RegistroSolicitudes> registros = new LinkedHashMap<>(128, 0.75f, true);

    public ProteccionIntentosRegistroCliente() {
        this(Clock.systemUTC());
    }

    ProteccionIntentosRegistroCliente(Clock reloj) {
        this.reloj = reloj;
    }

    /** Permite hasta cinco solicitudes de registro durante el tiempo establecido y detiene la siguiente. */
    public synchronized boolean admitirSolicitud(String claveCorreoHash) {
        Instant ahora = reloj.instant();
        RegistroSolicitudes registro = registros.get(claveCorreoHash);
        if (registro != null && registro.bloqueadoHasta() != null) {
            if (ahora.isBefore(registro.bloqueadoHasta())) {
                return false;
            }
            registros.remove(claveCorreoHash);
            registro = null;
        }
        if (registro == null || !ahora.isBefore(registro.inicioVentana().plus(VENTANA))) {
            registros.remove(claveCorreoHash);
            asegurarCapacidad();
            registros.put(claveCorreoHash, new RegistroSolicitudes(ahora, 1, null));
            return true;
        }

        int solicitudes = registro.solicitudes() + 1;
        Instant bloqueadoHasta = solicitudes >= MAXIMAS_SOLICITUDES ? ahora.plus(BLOQUEO) : null;
        registros.put(claveCorreoHash,
                new RegistroSolicitudes(registro.inicioVentana(), solicitudes, bloqueadoHasta));
        return true;
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

    private record RegistroSolicitudes(Instant inicioVentana, int solicitudes, Instant bloqueadoHasta) {
    }
}
