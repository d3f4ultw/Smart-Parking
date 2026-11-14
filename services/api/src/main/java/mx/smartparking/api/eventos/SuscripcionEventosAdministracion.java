package mx.smartparking.api.eventos;

import java.io.IOException;
import java.util.Map;
import java.util.TreeMap;
import java.util.UUID;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import org.springframework.http.MediaType;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * Guarda la información necesaria para enviar a una pantalla sus avisos pendientes durante el tiempo
 * permitido.
 */
final class SuscripcionEventosAdministracion {

    private static final String NOMBRE_EVENTO_HEARTBEAT = "empleado.heartbeat";

    final String idSesion;
    final PrincipalPropietario principal;
    final SseEmitter emisor;
    final UUID id;
    final Object candadoEntrega = new Object();
    final Map<Long, RegistroEventosAdministracion.Evento> eventosPendientes = new TreeMap<>();
    long ultimaSecuenciaEnviada;
    long ultimaSecuenciaHeartbeatEnviada;
    long ultimaSecuenciaHeartbeatConfirmada;
    long ultimaConfirmacionNanos;
    long ultimoHeartbeatNanos;
    boolean inicializada;
    boolean resincronizacionPendiente;
    boolean cerrada;

    SuscripcionEventosAdministracion(
            String idSesion,
            PrincipalPropietario principal,
            SseEmitter emisor,
            UUID id,
            long ahoraNanos) {
        this.idSesion = idSesion;
        this.principal = principal;
        this.emisor = emisor;
        this.id = id;
        ultimaConfirmacionNanos = ahoraNanos;
        ultimoHeartbeatNanos = ahoraNanos;
    }

    boolean concesionVencida(long ahoraNanos, long duracionConcesionNanos) {
        return ahoraNanos - ultimaConfirmacionNanos >= duracionConcesionNanos;
    }

    boolean heartbeatPendiente(long ahoraNanos, long intervaloHeartbeatNanos) {
        return inicializada && ahoraNanos - ultimoHeartbeatNanos >= intervaloHeartbeatNanos;
    }

    long siguienteSecuenciaHeartbeat() {
        if (ultimaSecuenciaHeartbeatEnviada == Long.MAX_VALUE) {
            throw new IllegalStateException("No pudimos completar la acción en este momento.");
        }
        return ultimaSecuenciaHeartbeatEnviada + 1;
    }

    void registrarHeartbeatEnviado(long secuencia, long ahoraNanos) {
        ultimaSecuenciaHeartbeatEnviada = secuencia;
        ultimoHeartbeatNanos = ahoraNanos;
    }

    boolean enviarHeartbeat(long ahoraNanos) {
        synchronized (candadoEntrega) {
            if (cerrada || !inicializada) {
                return true;
            }
            try {
                long secuencia = siguienteSecuenciaHeartbeat();
                emisor.send(crearEventoHeartbeat(id, secuencia));
                registrarHeartbeatEnviado(secuencia, ahoraNanos);
                return true;
            } catch (IOException | IllegalStateException excepcion) {
                return false;
            }
        }
    }

    static SseEmitter.SseEventBuilder crearEventoHeartbeat(UUID id, long secuencia) {
        return SseEmitter.event()
                .name(NOMBRE_EVENTO_HEARTBEAT)
                .data(Map.of("suscripcionId", id.toString(), "secuencia", secuencia), MediaType.APPLICATION_JSON);
    }

    boolean confirmarHeartbeat(long secuencia, long ahoraNanos, long duracionConcesionNanos) {
        synchronized (candadoEntrega) {
            if (cerrada || concesionVencida(ahoraNanos, duracionConcesionNanos)
                    || secuencia <= ultimaSecuenciaHeartbeatConfirmada
                    || secuencia != ultimaSecuenciaHeartbeatEnviada) {
                return false;
            }
            ultimaSecuenciaHeartbeatConfirmada = secuencia;
            ultimaConfirmacionNanos = ahoraNanos;
            return true;
        }
    }
}
