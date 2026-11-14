package mx.smartparking.api.eventos;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/** Avisa que cambió la lista de tarjetas una vez guardado el cambio, sin compartir datos privados. */
@Component
public final class PublicadorTarjetasRfid1 {

    private static final Logger LOG = LoggerFactory.getLogger(PublicadorTarjetasRfid1.class);
    private final ServicioEventosAdministracion eventos;

    public PublicadorTarjetasRfid1(ServicioEventosAdministracion eventos) {
        this.eventos = eventos;
    }

    /** Envía un aviso sin datos privados cuando se confirma un cambio en una tarjeta. */
    public void publicarSiActualizadas(boolean huboCambio) {
        if (!huboCambio) {
            return;
        }
        try {
            eventos.publicarTarjetasRfid1Actualizadas();
        } catch (RuntimeException excepcion) {
            LOG.warn("No se pudo publicar la invalidación del directorio RFID.");
        }
    }
}
