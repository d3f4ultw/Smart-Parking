package mx.smartparking.api.eventos;

import jakarta.annotation.PreDestroy;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/** Avisa a las pantallas que consulten de nuevo los accesos después de confirmar un cambio. */
@Component
public final class PublicadorAccesoAdministracion {

    private static final Logger LOG = LoggerFactory.getLogger(PublicadorAccesoAdministracion.class);
    private final ServicioEventosAdministracion eventos;
    private final ThreadPoolExecutor ejecutor = new ThreadPoolExecutor(
            2, 2, 0, TimeUnit.MILLISECONDS, new ArrayBlockingQueue<>(256), tarea -> {
                Thread hilo = new Thread(tarea, "smartparking-accesos-sse");
                hilo.setDaemon(true);
                return hilo;
            });

    public PublicadorAccesoAdministracion(ServicioEventosAdministracion eventos) {
        this.eventos = eventos;
    }

    /** Prepara un aviso de cambio sin retrasar ni deshacer una decisión de acceso que ya fue confirmada. */
    public void publicar() {
        try {
            ejecutor.execute(() -> {
                try {
                    eventos.publicarAccesoHistorialActualizado();
                } catch (RuntimeException excepcion) {
                    LOG.warn("No se pudo publicar la actualización del historial de accesos.");
                }
            });
        } catch (RuntimeException excepcion) {
            LOG.warn("Se omitió una invalidación del historial de accesos por saturación del emisor.");
        }
    }

    @PreDestroy
    public void detener() {
        ejecutor.shutdownNow();
    }
}
