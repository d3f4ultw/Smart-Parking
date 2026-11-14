package mx.smartparking.api.historial.persistencia;

import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.eventos.PublicadorAccesoAdministracion;
import mx.smartparking.api.persistencia.CargadorSql;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

/**
 * Guarda la decisión de una lectura sin el número de tarjeta y conserva referencias a la
 * relación de la tarjeta y a la visita cuando existen.
 */
@Repository
public class RepositorioEventoAccesoJdbc {

    private final JdbcTemplate jdbc;
    private final PublicadorAccesoAdministracion publicador;
    private final String sqlRegistrar = CargadorSql.cargar("historial/registrar_evento_acceso.sql");

    public RepositorioEventoAccesoJdbc(JdbcTemplate jdbc, PublicadorAccesoAdministracion publicador) {
        this.jdbc = jdbc;
        this.publicador = publicador;
    }

    /**
     * Guarda la decisión de una lectura de entrada o salida. Si se repite sin cambiar el resultado,
     * el motivo ni su relación con la tarjeta y la visita, conserva la hora anterior y no prepara
     * otro aviso.
     */
    public void registrar(
            Instant ocurridoEn,
            String lector,
            String resultado,
            String motivo,
            UUID lecturaId,
            Long asociacionId,
            Long movimientoId) {
        exigirTransaccionActiva();
        List<Long> cambios;
        try {
            cambios = jdbc.query(sqlRegistrar, (fila, numero) -> fila.getLong(1),
                    OffsetDateTime.ofInstant(ocurridoEn, ZoneOffset.UTC), lector, resultado, motivo, lecturaId,
                    asociacionId, movimientoId);
        } catch (RuntimeException excepcion) {
            throw new DataAccessResourceFailureException("No se pudo guardar la decisión de acceso.", excepcion);
        }
        if (!cambios.isEmpty() && publicador != null) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    publicador.publicar();
                }
            });
        }
    }

    private void exigirTransaccionActiva() {
        if (!TransactionSynchronizationManager.isActualTransactionActive()
                || !TransactionSynchronizationManager.isSynchronizationActive()) {
            // Esta excepción se usa al revisar el registro por separado, sin enviar avisos.
            if (publicador == null) {
                return;
            }
            throw new DataAccessResourceFailureException("La decisión de acceso requiere una transacción activa.");
        }
    }
}
