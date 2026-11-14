package mx.smartparking.api.persistencia;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.operadores.AccionEmpleadoOperadorPersistida;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

/**
 * Guarda resultados sin datos secretos para responder a solicitudes repetidas sobre la relación de
 * empleado y operador.
 */
@Repository
public class RepositorioAccionesEmpleadoOperadorJdbc implements RepositorioAccionesEmpleadoOperador {

    private static final RowMapper<AccionEmpleadoOperadorPersistida> MAPA =
            RepositorioAccionesEmpleadoOperadorJdbc::mapear;
    private final JdbcTemplate jdbc;
    private final String sqlReservar = CargadorSql.cargar("operadores/reservar_accion_empleado_operador.sql");
    private final String sqlBloquear = CargadorSql.cargar("operadores/bloquear_accion_empleado_operador.sql");
    private final String sqlCompletar = CargadorSql.cargar("operadores/completar_accion_empleado_operador.sql");
    private final String sqlActualizarEstadoEnvio =
            CargadorSql.cargar("operadores/actualizar_estado_envio_accion_empleado_operador.sql");

    public RepositorioAccionesEmpleadoOperadorJdbc(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public boolean reservar(UUID duenoCuentaId, String claveHash, String huella, String operacion, long empleadoId) {
        return jdbc.update(sqlReservar, duenoCuentaId, claveHash, huella, operacion, empleadoId) == 1;
    }

    @Override
    public Optional<AccionEmpleadoOperadorPersistida> bloquear(UUID duenoCuentaId, String claveHash) {
        List<AccionEmpleadoOperadorPersistida> acciones =
                jdbc.query(sqlBloquear, MAPA, duenoCuentaId, claveHash);
        return acciones.stream().findFirst();
    }

    @Override
    public void completar(
            UUID duenoCuentaId,
            String claveHash,
            UUID operadorId,
            String estadoOperador,
            long revisionEmpleado,
            String estadoEnvio) {
        int filas = jdbc.update(
                sqlCompletar, operadorId, estadoOperador, revisionEmpleado, estadoEnvio, duenoCuentaId, claveHash);
        if (filas != 1) {
            throw new DataAccessResourceFailureException("No se pudo completar el recibo de administración.");
        }
    }

    @Override
    public void actualizarEstadoEnvio(UUID duenoCuentaId, String claveHash, String estadoEnvio) {
        jdbc.update(sqlActualizarEstadoEnvio, estadoEnvio, duenoCuentaId, claveHash);
    }

    private static AccionEmpleadoOperadorPersistida mapear(ResultSet rs, int fila) throws SQLException {
        Long revision = (Long) rs.getObject("revision_empleado");
        return new AccionEmpleadoOperadorPersistida(
                rs.getString("huella_solicitud").trim(),
                rs.getString("operacion"),
                rs.getLong("empleado_id"),
                rs.getString("estado"),
                rs.getObject("operador_id", UUID.class),
                rs.getString("estado_operador"),
                revision,
                rs.getString("estado_envio"));
    }
}
