package mx.smartparking.api.accesos;

import java.security.SecureRandom;
import java.util.Base64;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.function.LongSupplier;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

/** Comprueba durante unos segundos si el dispositivo puede atender una salida manual sin abrir la barrera. */
@Component
public final class DetectorCapacidadSalidaManual {
    private static final long VIGENCIA_DESAFIO_NANOS = TimeUnit.SECONDS.toNanos(5);
    private static final long VIGENCIA_CAPACIDAD_NANOS = TimeUnit.SECONDS.toNanos(8);
    private static final int MAXIMO_DESAFIOS = 64;
    private final AutenticadorSalidaManual autenticador;
    private final LongSupplier reloj;
    private final SecureRandom aleatorio = new SecureRandom();
    private final Map<String, Long> desafios = new LinkedHashMap<>();
    private boolean confirmada;
    private long venceEn;
    private String bootConfirmado;

    @Autowired
    public DetectorCapacidadSalidaManual(AutenticadorSalidaManual autenticador) {
        this(autenticador, System::nanoTime);
    }

    DetectorCapacidadSalidaManual(AutenticadorSalidaManual autenticador, LongSupplier reloj) {
        this.autenticador = autenticador;
        this.reloj = reloj;
    }

    /**
     * Prepara una pregunta que vence pronto para comprobar el dispositivo; no contiene contraseñas ni
     * abre la barrera.
     */
    public synchronized String crearDesafio() {
        if (!autenticador.estaHabilitado()) { return null; }
        long ahora = reloj.getAsLong();
        desafios.entrySet().removeIf(entrada -> entrada.getValue() - ahora <= 0);
        while (desafios.size() >= MAXIMO_DESAFIOS) {
            Iterator<String> iterador = desafios.keySet().iterator();
            iterador.next();
            iterador.remove();
        }
        byte[] bytes = new byte[16];
        String nonce;
        do {
            aleatorio.nextBytes(bytes);
            nonce = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        } while (desafios.containsKey(nonce));
        desafios.put(nonce, ahora + VIGENCIA_DESAFIO_NANOS);
        return nonce;
    }

    /**
     * Revisa la respuesta del dispositivo y no permite volver a usar la misma pregunta, aunque la
     * respuesta sea incorrecta.
     */
    public synchronized boolean confirmar(String desafioId, String bootId, String firma) {
        long ahora = reloj.getAsLong();
        Long vencimiento = desafios.remove(desafioId);
        if (vencimiento == null || vencimiento - ahora <= 0
                || !autenticador.verificarPrueba(bootId, desafioId, firma)) {
            invalidar();
            return false;
        }
        confirmada = true;
        bootConfirmado = bootId;
        venceEn = ahora + VIGENCIA_CAPACIDAD_NANOS;
        return true;
    }

    /** Si el dispositivo se desconecta, se descarta cualquier comprobación pendiente. */
    public synchronized void invalidar() {
        confirmada = false;
        bootConfirmado = null;
        desafios.clear();
    }

    /** Indica si la comprobación sigue vigente y cuánto tiempo falta para que deje de ser válida. */
    public synchronized Disponibilidad disponibilidad() {
        if (!autenticador.estaHabilitado() || !confirmada) { return new Disponibilidad(false, 0); }
        long nanos = venceEn - reloj.getAsLong();
        if (nanos <= 0) {
            confirmada = false;
            return new Disponibilidad(false, 0);
        }
        long milisegundos = Math.min(8000, TimeUnit.NANOSECONDS.toMillis(nanos));
        if (milisegundos <= 0) {
            confirmada = false;
            return new Disponibilidad(false, 0);
        }
        return new Disponibilidad(true, milisegundos);
    }

    /** Acepta una orden solo si el dispositivo no se ha reiniciado desde que confirmó que estaba disponible. */
    public synchronized boolean disponibleParaBoot(String bootId) {
        if (!disponibilidad().disponible()) { return false; }
        if (!bootId.equals(bootConfirmado)) {
            invalidar();
            return false;
        }
        return true;
    }

    public record Disponibilidad(boolean disponible, long vigenciaRestanteMs) { }
}
