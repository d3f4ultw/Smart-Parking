package mx.smartparking.api.eventos;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/** Avisa que cambió la lectura de una tarjeta sin modificar el resultado que ya fue guardado. */
@Component
public final class PublicadorCapturaRfid1 {

    private static final Logger LOG = LoggerFactory.getLogger(PublicadorCapturaRfid1.class);
    private final ServicioEventosAdministracion eventos;

    public PublicadorCapturaRfid1(ServicioEventosAdministracion eventos) {
        this.eventos = eventos;
    }

    /** Avisa cuando se confirma una lectura; si el aviso no llega, la lectura guardada se conserva. */
    public void publicarSiActualizada(boolean huboCambio) {
        if (!huboCambio) {
            return;
        }
        try {
            eventos.publicarCapturaRfid1Actualizada();
        } catch (RuntimeException excepcion) {
            LOG.warn("No se pudo publicar la invalidación de la captura RFID 1.");
        }
    }
}
