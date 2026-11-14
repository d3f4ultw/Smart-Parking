package mx.smartparking.api.persistencia;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.empleados.Empleado;
import mx.smartparking.api.empleados.EstadoEmpleado;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

/** Consulta y guarda los datos permitidos del directorio de empleados. */
@Repository
public class RepositorioEmpleadosJdbc implements RepositorioEmpleados {

    private static final String SQL_EMPLEADO = """
            SELECT e.id, e.nombres, e.primer_apellido, e.segundo_apellido, e.estado, e.revision,
                   e.correo, c.id AS operador_id, c.estado AS operador_estado
            FROM empleado e
            LEFT JOIN cuenta c ON c.empleado_id = e.id
            """;
    private static final RowMapper<Empleado> MAPA_EMPLEADO = RepositorioEmpleadosJdbc::mapearEmpleado;
    private final JdbcTemplate jdbc;
    private final String sqlContarEmpleados = CargadorSql.cargar("empleados/contar_empleados.sql");
    private final String sqlReservarRegistro = CargadorSql.cargar("empleados/reservar_registro.sql");
    private final String sqlBuscarComprobante = CargadorSql.cargar("empleados/buscar_comprobante_registro.sql");
    private final String sqlCrearEmpleado = CargadorSql.cargar("empleados/crear_empleado.sql");
    private final String sqlCompletarRegistro = CargadorSql.cargar("empleados/completar_registro.sql");
    private final String sqlActualizarEstado = CargadorSql.cargar("empleados/actualizar_estado_empleado.sql");

    public RepositorioEmpleadosJdbc(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public ResultadoPaginaEmpleados consultarPagina(int paginaSolicitada, int tamanoPagina) {
        Long totalLeido = jdbc.queryForObject(sqlContarEmpleados, Long.class);
        long total = totalLeido == null ? 0 : totalLeido;
        long paginas = total == 0 ? 0 : (total - 1) / tamanoPagina + 1;
        int pagina = total == 0 ? 1 : (int) Math.min(paginaSolicitada, paginas);
        long desplazamiento = ((long) pagina - 1) * tamanoPagina;
        List<Empleado> empleados = total == 0 ? List.of() : jdbc.query(SQL_EMPLEADO + """
                ORDER BY e.id ASC LIMIT ? OFFSET ?
                """, MAPA_EMPLEADO, tamanoPagina, desplazamiento);
        return new ResultadoPaginaEmpleados(empleados, pagina, total, paginas);
    }

    @Override
    public ResultadoPaginaEmpleados consultarElegiblesParaOperador(
            int paginaSolicitada, int tamanoPagina, String busqueda) {
        StringBuilder condiciones = new StringBuilder(" WHERE e.estado = 'ACTIVO' AND c.id IS NULL");
        List<Object> parametros = new java.util.ArrayList<>();
        if (busqueda != null) {
            condiciones.append(" AND (concat_ws(' ', e.nombres, e.primer_apellido, e.segundo_apellido) ")
                    .append("ILIKE ? ESCAPE E'\\\\' OR ('E-' || lpad(e.id::text, 4, '0')) ")
                    .append("ILIKE ? ESCAPE E'\\\\')");
            String patron = patronBusqueda(busqueda);
            parametros.add(patron);
            parametros.add(patron);
        }
        Object[] parametrosConsulta = parametros.toArray();
        String tablas = " FROM empleado e LEFT JOIN cuenta c ON c.empleado_id = e.id";
        Long totalLeido = jdbc.queryForObject(
                "SELECT count(*)" + tablas + condiciones, Long.class, parametrosConsulta);
        long total = totalLeido == null ? 0 : totalLeido;
        long paginas = total == 0 ? 0 : (total - 1) / tamanoPagina + 1;
        int pagina = total == 0 ? 1 : (int) Math.min(paginaSolicitada, paginas);
        long desplazamiento = ((long) pagina - 1) * tamanoPagina;
        List<Object> parametrosPagina = new java.util.ArrayList<>(parametros);
        parametrosPagina.add(tamanoPagina);
        parametrosPagina.add(desplazamiento);
        List<Empleado> empleados = total == 0 ? List.of() : jdbc.query(
                SQL_EMPLEADO + condiciones + " ORDER BY e.id ASC LIMIT ? OFFSET ?",
                MAPA_EMPLEADO, parametrosPagina.toArray());
        return new ResultadoPaginaEmpleados(empleados, pagina, total, paginas);
    }

    @Override
    public boolean reservarRegistro(UUID cuentaId, String claveHash, String huellaSolicitud) {
        int filas = jdbc.update(sqlReservarRegistro, cuentaId, claveHash, huellaSolicitud);
        return filas == 1;
    }

    @Override
    public Optional<ComprobanteRegistroEmpleado> buscarComprobante(UUID cuentaId, String claveHash) {
        List<ComprobanteRegistroEmpleado> comprobantes = jdbc.query(
                sqlBuscarComprobante, (rs, fila) -> new ComprobanteRegistroEmpleado(
                rs.getString("huella_solicitud").trim(),
                rs.getString("estado"),
                (Long) rs.getObject("empleado_id")), cuentaId, claveHash);
        return comprobantes.stream().findFirst();
    }

    @Override
    public long crearEmpleado(
            String nombres,
            String primerApellido,
            String segundoApellido,
            String correo,
            String correoNormalizado) {
        Long id = jdbc.queryForObject(
                sqlCrearEmpleado, Long.class, nombres, primerApellido, segundoApellido, correo, correoNormalizado);
        if (id == null) {
            throw new DataAccessResourceFailureException("No se recibió el identificador del empleado creado.");
        }
        return id;
    }

    @Override
    public void completarRegistro(UUID cuentaId, String claveHash, long empleadoId) {
        int filas = jdbc.update(sqlCompletarRegistro, empleadoId, cuentaId, claveHash);
        if (filas != 1) {
            throw new DataAccessResourceFailureException("No se pudo completar el recibo de registro.");
        }
    }

    @Override
    public Optional<Empleado> obtener(long id) {
        List<Empleado> encontrados = jdbc.query(SQL_EMPLEADO + " WHERE e.id = ?", MAPA_EMPLEADO, id);
        return encontrados.stream().findFirst();
    }

    @Override
    public Optional<Empleado> bloquearPorId(long id) {
        List<Empleado> encontrados = jdbc.query(SQL_EMPLEADO + " WHERE e.id = ? FOR UPDATE OF e", MAPA_EMPLEADO, id);
        return encontrados.stream().findFirst();
    }

    @Override
    public Empleado actualizarEstado(long id, EstadoEmpleado estado, long revision) {
        int filas = jdbc.update(sqlActualizarEstado, estado.name(), revision, id);
        if (filas != 1) {
            throw new DataAccessResourceFailureException("No se pudo actualizar el estado del empleado.");
        }
        return bloquearPorId(id).orElseThrow(() ->
                new DataAccessResourceFailureException("No se encontró el empleado actualizado."));
    }

    private static Empleado mapearEmpleado(ResultSet rs, int fila) throws SQLException {
        long id = rs.getLong("id");
        UUID operadorId = rs.getObject("operador_id", UUID.class);
        String estadoOperador = rs.getString("operador_estado");
        Empleado.OperadorVinculado operador = operadorId == null
                ? null
                : new Empleado.OperadorVinculado(operadorId, estadoOperador);
        long revision = rs.getLong("revision");
        return new Empleado(
                id,
                Empleado.codigoDe(id),
                rs.getString("nombres"),
                rs.getString("primer_apellido"),
                rs.getString("segundo_apellido"),
                EstadoEmpleado.valueOf(rs.getString("estado")),
                revision,
                Long.toString(id),
                Long.toString(revision),
                rs.getString("correo"),
                operador);
    }

    private static String patronBusqueda(String busqueda) {
        String literal = busqueda.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
        return "%" + literal + "%";
    }
}
