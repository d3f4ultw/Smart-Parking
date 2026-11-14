package mx.smartparking.api.rfid1.servicio;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import org.springframework.stereotype.Service;

/** Recuerda la última señal recibida del equipo que comunica el lector con el servidor. */
@Service
public final class ServicioEstadoConexionRfid1 {

    private static final Duration VIGENCIA_HEARTBEAT = Duration.ofSeconds(20);
    private final Clock reloj;
    private volatile Heartbeat ultimoHeartbeat;

    public ServicioEstadoConexionRfid1() {
        this(Clock.systemUTC());
    }

    ServicioEstadoConexionRfid1(Clock reloj) {
        this.reloj = reloj;
    }

    /** Registra si el dispositivo ESP32 respondió a la comprobación de conexión. */
    public void registrar(boolean conectado) {
        ultimoHeartbeat = new Heartbeat(conectado, reloj.instant());
    }

    /** Indica si el lector sigue conectado y lo marca como desconectado si no respondió a tiempo. */
    public EstadoConexion consultar() {
        Heartbeat ultimo = ultimoHeartbeat;
        if (ultimo == null) {
            return new EstadoConexion("DESCONOCIDO", null);
        }
        if (reloj.instant().isAfter(ultimo.actualizadoEn().plus(VIGENCIA_HEARTBEAT))) {
            return new EstadoConexion("DESCONECTADO", ultimo.actualizadoEn());
        }
        if (!ultimo.conectado()) {
            return new EstadoConexion("DESCONECTADO", ultimo.actualizadoEn());
        }
        return new EstadoConexion("CONECTADO", ultimo.actualizadoEn());
    }

    private record Heartbeat(boolean conectado, Instant actualizadoEn) {
    }

    public record EstadoConexion(String estado, Instant actualizadoEn) {
    }
}
