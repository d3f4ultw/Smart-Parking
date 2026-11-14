package mx.smartparking.api.transferencia;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.stereotype.Component;

/**
 * Limita los intentos de comprobar la contraseña administrativa y recuperar el permiso de cambio
 * de propietario; los intentos se recuerdan solo mientras la aplicación está en marcha.
 */
@Component
public class ProteccionIntentosTransferencia {

    private static final int MAXIMO_FALLOS = 5;
    private static final int MAXIMO_ORIGENES = 10_000;
    private static final Duration VENTANA = Duration.ofMinutes(1);
    private static final Duration BLOQUEO = Duration.ofMinutes(1);

    private final Map<ClaveIntentos, EstadoIntentos> intentos = new LinkedHashMap<>(128, 0.75f, true);
    private final Clock reloj;

    public ProteccionIntentosTransferencia() {
        this(Clock.systemUTC());
    }

    ProteccionIntentosTransferencia(Clock reloj) {
        this.reloj = reloj;
    }

    /** Indica si se permite otro intento para esa operación y desde ese origen. */
    public synchronized boolean permitido(Operacion operacion, String origenRemoto) {
        Instant ahora = reloj.instant();
        limpiarExpirados(ahora);
        ClaveIntentos clave = clave(operacion, origenRemoto);
        EstadoIntentos estado = intentos.get(clave);
        if (estado == null) {
            return true;
        }
        if (estado.bloqueadoHasta() != null) {
            if (ahora.isBefore(estado.bloqueadoHasta())) {
                return false;
            }
            intentos.remove(clave);
            return true;
        }
        return ahora.isBefore(estado.inicioVentana().plus(VENTANA));
    }

    /** Cuenta cada intento rechazado y establece una espera temporal al llegar al quinto. */
    public synchronized void registrarFallo(Operacion operacion, String origenRemoto) {
        Instant ahora = reloj.instant();
        limpiarExpirados(ahora);
        ClaveIntentos clave = clave(operacion, origenRemoto);
        EstadoIntentos estado = intentos.get(clave);
        if (estado == null || !ahora.isBefore(estado.inicioVentana().plus(VENTANA))) {
            estado = new EstadoIntentos(ahora, 0, null);
        }
        int fallos = estado.fallos() + 1;
        Instant bloqueoHasta = fallos >= MAXIMO_FALLOS ? ahora.plus(BLOQUEO) : null;
        intentos.put(clave, new EstadoIntentos(estado.inicioVentana(), fallos, bloqueoHasta));
        while (intentos.size() > MAXIMO_ORIGENES) {
            Iterator<ClaveIntentos> iterador = intentos.keySet().iterator();
            if (iterador.hasNext()) {
                iterador.next();
                iterador.remove();
            }
        }
    }

    /** Cuando un intento es correcto, olvida los fallos anteriores de esa misma operación y origen. */
    public synchronized void registrarExito(Operacion operacion, String origenRemoto) {
        intentos.remove(clave(operacion, origenRemoto));
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

    private static ClaveIntentos clave(Operacion operacion, String origenRemoto) {
        String origen = origenRemoto == null || origenRemoto.isBlank() || origenRemoto.length() > 128
                ? "origen-desconocido"
                : origenRemoto.strip();
        return new ClaveIntentos(operacion, origen);
    }

    public enum Operacion {
        INICIO,
        RECUPERACION,
        GRANT
    }

    private record ClaveIntentos(Operacion operacion, String origenRemoto) {
    }

    private record EstadoIntentos(Instant inicioVentana, int fallos, Instant bloqueadoHasta) {
    }
}
