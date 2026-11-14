package mx.smartparking.api.persistencia;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import java.util.Optional;
import mx.smartparking.api.empleados.Empleado;
import mx.smartparking.api.empleados.coordinacion.EmpleadoEnlaceOperador;
import mx.smartparking.api.empleados.coordinacion.PuertoEmpleadosOperador;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

/** Consulta y guarda los datos del empleado que se necesitan para administrar su cuenta vinculada. */
@Repository
public class RepositorioEmpleadosOperadorJdbc implements PuertoEmpleadosOperador {

    private static final RowMapper<EmpleadoEnlaceOperador> MAPA = RepositorioEmpleadosOperadorJdbc::mapear;
    private final JdbcTemplate jdbc;
    private final String sqlConsultarEmpleado = CargadorSql.cargar("operadores/consultar_empleado_vinculado.sql");
    private final String sqlBloquearEmpleado = CargadorSql.cargar("operadores/bloquear_empleado_vinculado.sql");
    private final String sqlActualizarCorreoEmpleado = CargadorSql.cargar("operadores/actualizar_correo_empleado.sql");
    private final String sqlActualizarEstadoEmpleado = CargadorSql.cargar("operadores/actualizar_estado_empleado.sql");
    private final String sqlIncrementarRevisionEmpleado = CargadorSql.cargar("operadores/incrementar_revision_empleado.sql");

    public RepositorioEmpleadosOperadorJdbc(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<EmpleadoEnlaceOperador> bloquearPorId(long empleadoId) {
        List<EmpleadoEnlaceOperador> encontrados = jdbc.query(
                sqlBloquearEmpleado, MAPA, empleadoId);
        return encontrados.stream().findFirst();
    }

    @Override
    public Optional<EmpleadoEnlaceOperador> consultarPorId(long empleadoId) {
        List<EmpleadoEnlaceOperador> encontrados = jdbc.query(
                sqlConsultarEmpleado, MAPA, empleadoId);
        return encontrados.stream().findFirst();
    }

    @Override
    public boolean actualizarCorreoYRevision(
            long empleadoId, String correo, String correoNormalizado, long revisionEsperada) {
        return jdbc.update(sqlActualizarCorreoEmpleado, correo, correoNormalizado, empleadoId, revisionEsperada) == 1;
    }

    @Override
    public boolean actualizarEstadoYRevision(long empleadoId, String estado, long revisionEsperada) {
        return jdbc.update(sqlActualizarEstadoEmpleado, estado, empleadoId, revisionEsperada) == 1;
    }

    @Override
    public boolean incrementarRevision(long empleadoId, long revisionEsperada) {
        return jdbc.update(sqlIncrementarRevisionEmpleado, empleadoId, revisionEsperada) == 1;
    }

    private static EmpleadoEnlaceOperador mapear(ResultSet rs, int fila) throws SQLException {
        long id = rs.getLong("id");
        return new EmpleadoEnlaceOperador(
                id,
                Empleado.codigoDe(id),
                rs.getString("estado"),
                rs.getLong("revision"),
                rs.getString("correo"),
                rs.getString("correo_normalizado"));
    }
}
