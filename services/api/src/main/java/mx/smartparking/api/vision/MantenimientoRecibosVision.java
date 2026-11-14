package mx.smartparking.api.vision;

import java.util.List;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.TransactionException;

/**
 * Elimina por grupos los registros antiguos de observaciones, incluso cuando la cámara deja de enviar
 * datos.
 */
@Component
public class MantenimientoRecibosVision {
    private static final Logger LOG = LoggerFactory.getLogger(MantenimientoRecibosVision.class);
    private static final int MAXIMO_FUENTES_POR_CICLO = 16;
    private final JdbcTemplate jdbc;
    private final ServicioVision servicio;
    private UUID ultimaFuente;

    public MantenimientoRecibosVision(JdbcTemplate jdbc, ServicioVision servicio,
            @Value("${smartparking.vision.limpieza-intervalo-ms:30000}") long intervaloMs) {
        if (intervaloMs < 1000 || intervaloMs > 3_600_000) {
            throw new IllegalArgumentException("El intervalo de limpieza Vision no es válido.");
        }
        this.jdbc = jdbc;
        this.servicio = servicio;
    }

    /** Limpia los datos antiguos de cada cámara por separado para que sus operaciones no interfieran. */
    @Scheduled(fixedDelayString = "${smartparking.vision.limpieza-intervalo-ms:30000}",
            initialDelayString = "${smartparking.vision.limpieza-intervalo-ms:30000}")
    public synchronized void limpiarPeriodicamente() {
        List<UUID> fuentes = siguientesFuentes();
        if (fuentes.isEmpty() && ultimaFuente != null) {
            ultimaFuente = null;
            fuentes = siguientesFuentes();
        }
        int eliminados = 0;
        for (UUID fuente : fuentes) {
            try {
                eliminados += servicio.limpiarRecibos(fuente);
            } catch (DataAccessException | TransactionException excepcion) {
                LOG.warn("No se pudo limpiar un lote de recibos Vision; se reintentará.");
            }
            ultimaFuente = fuente;
        }
        if (eliminados > 0) {
            LOG.info("Se retiraron {} recibos Vision vencidos.", eliminados);
        }
    }

    private List<UUID> siguientesFuentes() {
        if (ultimaFuente == null) {
            return jdbc.query("SELECT fuente_id FROM vision_fuente ORDER BY fuente_id LIMIT ?",
                    (rs, numero) -> rs.getObject(1, UUID.class), MAXIMO_FUENTES_POR_CICLO);
        }
        return jdbc.query("SELECT fuente_id FROM vision_fuente WHERE fuente_id > ? ORDER BY fuente_id LIMIT ?",
                (rs, numero) -> rs.getObject(1, UUID.class), ultimaFuente, MAXIMO_FUENTES_POR_CICLO);
    }
}
