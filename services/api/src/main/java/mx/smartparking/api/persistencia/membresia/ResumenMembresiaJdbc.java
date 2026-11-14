package mx.smartparking.api.persistencia.membresia;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.persistencia.CargadorSql;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;

/** Consulta la membresía guardada, el pago pendiente y si el cliente puede contratarla. */
final class ResumenMembresiaJdbc {

    private static final String CONSULTA = CargadorSql.cargar("membresias/consultar_resumen_membresia.sql");

    private ResumenMembresiaJdbc() {
    }

    static ResumenMembresiaPersistido consultar(JdbcTemplate jdbc, UUID clienteId) {
        List<ResumenMembresiaPersistido> filas = jdbc.query(CONSULTA,
                ResumenMembresiaJdbc::mapear, clienteId);
        return filas.stream().findFirst().orElseThrow(() ->
                new DataAccessResourceFailureException("No se encontró una cuenta CLIENTE activa."));
    }

    private static ResumenMembresiaPersistido mapear(ResultSet rs, int fila) throws SQLException {
        return new ResumenMembresiaPersistido(
                rs.getString("estado"), instante(rs, "periodo_inicio"), instante(rs, "periodo_fin"),
                instante(rs, "siguiente_cobro_en"), rs.getBoolean("cancelacion_al_final"),
                rs.getBoolean("puede_comprar"), rs.getObject("intento_checkout_pendiente_id", UUID.class),
                rs.getString("estado_checkout_pendiente"), instante(rs, "checkout_expira_en"));
    }

    private static Instant instante(ResultSet rs, String columna) throws SQLException {
        Timestamp marca = rs.getTimestamp(columna);
        return marca == null ? null : marca.toInstant();
    }
}
