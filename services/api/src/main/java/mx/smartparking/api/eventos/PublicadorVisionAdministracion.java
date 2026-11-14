package mx.smartparking.api.eventos;

import jakarta.annotation.PreDestroy;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

/** Agrupa los avisos de cambios de ocupación sin guardar la información observada por la cámara. */
@Component
public final class PublicadorVisionAdministracion {
    private static final Logger LOG = LoggerFactory.getLogger(PublicadorVisionAdministracion.class);
    private static final long VENTANA_MS = 1_000;
    private final Runnable publicar;
    private final ScheduledExecutorService ejecutor;
    private boolean pendiente;
    private boolean programado;
    private boolean cerrado;

    @Autowired
    public PublicadorVisionAdministracion(ServicioEventosAdministracion eventos) {
        this(eventos::publicarVisionActualizada, Executors.newSingleThreadScheduledExecutor(tarea -> {
            Thread hilo = new Thread(tarea, "smartparking-vision-eventos");
            hilo.setDaemon(true);
            return hilo;
        }));
    }

    PublicadorVisionAdministracion(Runnable publicar, ScheduledExecutorService ejecutor) {
        this.publicar = publicar;
        this.ejecutor = ejecutor;
    }

    /**
     * Prepara un aviso después de confirmar un cambio y agrupa varios cambios cercanos en un solo
     * aviso pendiente.
     */
    public synchronized void solicitar() {
        if (cerrado) return;
        pendiente = true;
        if (!programado) programar();
    }

    private void programar() {
        try {
            programado = true;
            ejecutor.schedule(this::publicarPendiente, VENTANA_MS, TimeUnit.MILLISECONDS);
        } catch (RuntimeException excepcion) {
            programado = false;
            LOG.warn("No se pudo programar la invalidación Vision; la lectura se reconciliará.", excepcion);
        }
    }

    private void publicarPendiente() {
        synchronized (this) {
            if (cerrado) return;
            pendiente = false;
        }
        try {
            publicar.run();
        } catch (RuntimeException excepcion) {
            LOG.warn("No se pudo publicar la invalidación Vision; la lectura se reconciliará.", excepcion);
        } finally {
            synchronized (this) {
                programado = false;
                if (pendiente && !cerrado) programar();
            }
        }
    }

    @PreDestroy
    public synchronized void detener() {
        cerrado = true;
        pendiente = false;
        ejecutor.shutdownNow();
    }
}
