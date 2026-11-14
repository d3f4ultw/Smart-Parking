package mx.smartparking.api.persistencia;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.operadores.CuentaOperadorAdministrable;
import mx.smartparking.api.operadores.DatosRegistroOperador;
import mx.smartparking.api.operadores.EstadoCuentaOperador;
import mx.smartparking.api.operadores.Operador;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

/** Guarda el registro del operador sin duplicar solicitudes y consulta los datos permitidos. */
@Repository
public class RepositorioOperadoresJdbc implements RepositorioOperadores {

    private static final String SQL_SELECCION_OPERADORES = """
            SELECT a.id, a.nombres, a.primer_apellido, a.segundo_apellido, a.correo,
                   a.estado, a.empleado_id::text AS empleado_id_texto,
                   CASE WHEN a.empleado_id IS NULL THEN 'LEGADO_SIN_VINCULO' ELSE 'VINCULADO' END AS estado_conciliacion,
                   CASE
                       WHEN i.operador_id IS NULL THEN 'DESCONOCIDO'
                       WHEN i.consumido_en IS NOT NULL THEN 'CONSUMIDA'
                       WHEN CURRENT_TIMESTAMP >= i.vence_en THEN 'EXPIRADA'
                       ELSE i.estado_envio
                   END AS estado_invitacion,
                   CASE
                       WHEN i.operador_id IS NULL THEN FALSE
                       ELSE a.estado = 'PENDIENTE'
                           AND i.consumido_en IS NULL
                           AND emisiones.cantidad < 3
                           AND CURRENT_TIMESTAMP >= GREATEST(
                               i.generado_en + INTERVAL '60 seconds',
                               COALESCE(emisiones.ultima + INTERVAL '60 seconds',
                                   i.generado_en + INTERVAL '60 seconds'))
                   END AS puede_reemitir_invitacion
            FROM cuenta a
            LEFT JOIN invitacion_operador i ON i.operador_id = a.id
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS cantidad, MAX(ia.creada_en) AS ultima
                FROM idempotencia_accion_operador ia
                WHERE ia.operador_id = a.id
                  AND ia.operacion IN ('REEMITIR_INVITACION', 'REACTIVAR')
                  AND ia.creada_en > CURRENT_TIMESTAMP - INTERVAL '1 hour'
            ) emisiones ON TRUE
            """;

    private static final RowMapper<Operador> MAPA_OPERADOR = RepositorioOperadoresJdbc::mapearOperador;
    private static final RowMapper<CuentaOperadorAdministrable> MAPA_CUENTA_ADMINISTRABLE =
            RepositorioOperadoresJdbc::mapearCuentaAdministrable;

    private final JdbcTemplate jdbc;
    private final String sqlReservarRegistro = CargadorSql.cargar("operadores/reservar_registro.sql");
    private final String sqlBuscarComprobante = CargadorSql.cargar("operadores/buscar_comprobante_registro.sql");
    private final String sqlCrearOperadorPendiente = CargadorSql.cargar("operadores/crear_operador_pendiente.sql");
    private final String sqlCompletarRegistro = CargadorSql.cargar("operadores/completar_registro.sql");
    private final String sqlBuscarEmpleadoId = CargadorSql.cargar("operadores/buscar_empleado_id_operador.sql");
    private final String sqlBuscarCuentaVinculada = CargadorSql.cargar("operadores/buscar_cuenta_vinculada.sql");
    private final String sqlBloquearCuentaVinculada = CargadorSql.cargar("operadores/bloquear_cuenta_vinculada.sql");
    private final String sqlCrearOperadorVinculado = CargadorSql.cargar("operadores/crear_operador_vinculado.sql");
    private final String sqlReactivarCuentaVinculada = CargadorSql.cargar("operadores/reactivar_cuenta_vinculada.sql");
    private final String sqlActualizarCorreo = CargadorSql.cargar("operadores/actualizar_correo_operador.sql");
    private final String sqlVincularCuenta = CargadorSql.cargar("operadores/vincular_cuenta.sql");
    private final String sqlConsultarCorreoReservado = CargadorSql.cargar("operadores/consultar_correo_reservado.sql");
    private final String sqlBuscarCuentaAdministrable = CargadorSql.cargar("operadores/buscar_cuenta_administrable.sql");
    private final String sqlBloquearCuentaAdministrable = CargadorSql.cargar("operadores/bloquear_cuenta_administrable.sql");
    private final String sqlActualizarEstado = CargadorSql.cargar("operadores/actualizar_estado_operador.sql");

    public RepositorioOperadoresJdbc(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public ResultadoPaginaOperadores consultarPagina(
            int paginaSolicitada, int tamanoPagina, String busqueda, EstadoCuentaOperador estado) {
        StringBuilder condiciones = new StringBuilder(" WHERE a.rol = 'OPERADOR'");
        List<Object> parametros = new ArrayList<>();
        if (estado != null) {
            condiciones.append(" AND a.estado = ?");
            parametros.add(estado.name());
        }
        if (busqueda != null) {
            condiciones.append(" AND concat_ws(' ', a.nombres, a.primer_apellido, a.segundo_apellido, ")
                    .append("a.correo_normalizado) ILIKE ? ESCAPE E'\\\\'");
            parametros.add(patronBusqueda(busqueda));
        }
        Object[] parametrosConsulta = parametros.toArray();
        Long totalLeido = jdbc.queryForObject(
                "SELECT count(*) FROM cuenta a" + condiciones, Long.class, parametrosConsulta);
        long total = totalLeido == null ? 0 : totalLeido;
        long totalPaginas = total == 0 ? 0 : (total - 1) / tamanoPagina + 1;
        int pagina = total == 0 ? 1 : (int) Math.min(paginaSolicitada, totalPaginas);
        long desplazamiento = ((long) pagina - 1) * tamanoPagina;
        List<Operador> operadores = total == 0 ? List.of() : jdbc.query(
                SQL_SELECCION_OPERADORES + condiciones + """
                        ORDER BY a.creada_en DESC, a.id DESC
                        LIMIT ? OFFSET ?
                        """, MAPA_OPERADOR, agregarPaginacion(parametrosConsulta, tamanoPagina, desplazamiento));
        return new ResultadoPaginaOperadores(operadores, pagina, total, totalPaginas);
    }

    @Override
    public boolean reservarRegistro(UUID duenoCuentaId, String claveHash, String huellaSolicitud) {
        int filas = jdbc.update(sqlReservarRegistro, duenoCuentaId, claveHash, huellaSolicitud);
        return filas == 1;
    }

    @Override
    public Optional<ComprobanteRegistroOperador> buscarComprobante(UUID duenoCuentaId, String claveHash) {
        List<ComprobanteRegistroOperador> comprobantes = jdbc.query(
                sqlBuscarComprobante, (rs, fila) -> new ComprobanteRegistroOperador(
                rs.getString("huella_solicitud").trim(),
                rs.getString("estado"),
                rs.getObject("operador_id", UUID.class)), duenoCuentaId, claveHash);
        return comprobantes.stream().findFirst();
    }

    @Override
    public UUID crearOperadorPendiente(UUID operadorId, DatosRegistroOperador datos) {
        try {
            int filas = jdbc.update(sqlCrearOperadorPendiente, operadorId, datos.nombres(),
                    datos.primerApellido(), datos.segundoApellido(),
                    datos.correo(), datos.correo());
            if (filas != 1) {
                throw new DataAccessResourceFailureException("No se pudo crear la cuenta pendiente del operador.");
            }
            return operadorId;
        } catch (DuplicateKeyException excepcion) {
            throw new ErrorConfiguracion(HttpStatus.CONFLICT,
                    "Ya existe una cuenta con ese correo.", "CORREO_EN_USO");
        }
    }

    @Override
    public void completarRegistro(UUID duenoCuentaId, String claveHash, UUID operadorId) {
        int filas = jdbc.update(sqlCompletarRegistro, operadorId, duenoCuentaId, claveHash);
        if (filas != 1) {
            throw new DataAccessResourceFailureException("No se pudo completar el recibo de registro del operador.");
        }
    }

    @Override
    public Optional<Operador> buscarPorId(UUID operadorId) {
        List<Operador> encontrados = jdbc.query(SQL_SELECCION_OPERADORES + """
                WHERE a.id = ? AND a.rol = 'OPERADOR'
                """, MAPA_OPERADOR, operadorId);
        return encontrados.stream().findFirst();
    }

    @Override
    public Optional<Long> empleadoId(UUID operadorId) {
        List<Long> ids = jdbc.query(sqlBuscarEmpleadoId, (rs, fila) -> {
            Long id = (Long) rs.getObject("empleado_id");
            return id;
        }, operadorId);
        return ids.stream().findFirst();
    }

    @Override
    public Optional<CuentaOperadorAdministrable> buscarCuentaVinculada(long empleadoId) {
        return consultarCuentaVinculada(empleadoId, false);
    }

    @Override
    public Optional<CuentaOperadorAdministrable> bloquearCuentaVinculada(long empleadoId) {
        return consultarCuentaVinculada(empleadoId, true);
    }

    private Optional<CuentaOperadorAdministrable> consultarCuentaVinculada(long empleadoId, boolean bloquear) {
        String sql = bloquear ? sqlBloquearCuentaVinculada : sqlBuscarCuentaVinculada;
        List<CuentaOperadorAdministrable> encontrados = jdbc.query(sql, MAPA_CUENTA_ADMINISTRABLE, empleadoId);
        return encontrados.stream().findFirst();
    }

    @Override
    public UUID crearOperadorVinculado(UUID operadorId, long empleadoId) {
        try {
            return jdbc.queryForObject(sqlCrearOperadorVinculado, UUID.class, operadorId, empleadoId);
        } catch (DuplicateKeyException excepcion) {
            throw new ErrorConfiguracion(HttpStatus.CONFLICT,
                    "El correo ya está reservado para otra cuenta.", "CORREO_EN_USO");
        }
    }

    @Override
    public CuentaOperadorAdministrable reactivarCuentaVinculada(
            UUID operadorId, long empleadoId, String correo, String correoNormalizado, long revisionEsperada) {
        int filas;
        try {
            filas = jdbc.update(sqlReactivarCuentaVinculada, correo, correoNormalizado,
                    operadorId, empleadoId, revisionEsperada);
        } catch (DuplicateKeyException excepcion) {
            throw new ErrorConfiguracion(HttpStatus.CONFLICT,
                    "El correo ya está reservado para otra cuenta.", "CORREO_EN_USO");
        }
        if (filas != 1) {
            throw new ErrorConfiguracion(HttpStatus.CONFLICT,
                    "La cuenta cambió. Actualiza la información e inténtalo de nuevo.", "CUENTA_EN_CONFLICTO");
        }
        return bloquearCuentaAdministrable(operadorId).orElseThrow(() ->
                new DataAccessResourceFailureException("No se encontró la cuenta actualizada del operador."));
    }

    @Override
    public CuentaOperadorAdministrable actualizarCorreo(
            UUID operadorId, String correo, String correoNormalizado, long revisionEsperada) {
        try {
            int filas = jdbc.update(
                    sqlActualizarCorreo, correo, correoNormalizado, operadorId, revisionEsperada);
            if (filas != 1) {
                throw new ErrorConfiguracion(HttpStatus.CONFLICT,
                        "La cuenta cambió. Actualiza la información e inténtalo de nuevo.", "CUENTA_EN_CONFLICTO");
            }
        } catch (DuplicateKeyException excepcion) {
            throw new ErrorConfiguracion(HttpStatus.CONFLICT,
                    "El correo ya está reservado para otra cuenta.", "CORREO_EN_USO");
        }
        return bloquearCuentaAdministrable(operadorId).orElseThrow(() ->
                new DataAccessResourceFailureException("No se encontró la cuenta actualizada del operador."));
    }

    @Override
    public CuentaOperadorAdministrable vincularCuenta(UUID operadorId, long empleadoId, long revisionEsperada) {
        int filas;
        try {
            filas = jdbc.update(sqlVincularCuenta, empleadoId, operadorId, revisionEsperada);
        } catch (DuplicateKeyException excepcion) {
            throw new ErrorConfiguracion(HttpStatus.CONFLICT,
                    "El empleado o la cuenta ya están vinculados.", "VINCULO_OCUPADO");
        }
        if (filas != 1) {
            throw new ErrorConfiguracion(HttpStatus.CONFLICT,
                    "El empleado o la cuenta ya están vinculados.", "VINCULO_OCUPADO");
        }
        return bloquearCuentaAdministrable(operadorId).orElseThrow(() ->
                new DataAccessResourceFailureException("No se encontró la cuenta actualizada del operador."));
    }

    @Override
    public boolean correoReservado(String correoNormalizado, UUID excluirCuentaId) {
        Boolean reservado = jdbc.queryForObject(
                sqlConsultarCorreoReservado, Boolean.class,
                correoNormalizado, excluirCuentaId, excluirCuentaId);
        return Boolean.TRUE.equals(reservado);
    }

    @Override
    public Optional<CuentaOperadorAdministrable> buscarCuentaAdministrable(UUID operadorId) {
        List<CuentaOperadorAdministrable> encontrados = jdbc.query(
                sqlBuscarCuentaAdministrable, MAPA_CUENTA_ADMINISTRABLE, operadorId);
        return encontrados.stream().findFirst();
    }

    @Override
    public Optional<CuentaOperadorAdministrable> bloquearCuentaAdministrable(UUID operadorId) {
        List<CuentaOperadorAdministrable> encontrados = jdbc.query(
                sqlBloquearCuentaAdministrable, MAPA_CUENTA_ADMINISTRABLE, operadorId);
        return encontrados.stream().findFirst();
    }

    @Override
    public CuentaOperadorAdministrable actualizarEstado(
            UUID operadorId, EstadoCuentaOperador estado, long revisionEsperada, long revisionNueva) {
        try {
            int filas = jdbc.update(sqlActualizarEstado, estado.name(), revisionNueva, operadorId, revisionEsperada);
            if (filas != 1) {
                throw new DataAccessResourceFailureException("No se pudo actualizar el estado del operador.");
            }
        } catch (DuplicateKeyException excepcion) {
            throw new ErrorConfiguracion(HttpStatus.CONFLICT,
                    "Ya hay otra cuenta con ese correo.", "CORREO_EN_USO");
        }
        return bloquearCuentaAdministrable(operadorId).orElseThrow(() ->
                new DataAccessResourceFailureException("No se encontró la cuenta actualizada del operador."));
    }

    private static Object[] agregarPaginacion(Object[] parametros, int tamanoPagina, long desplazamiento) {
        Object[] resultado = java.util.Arrays.copyOf(parametros, parametros.length + 2);
        resultado[parametros.length] = tamanoPagina;
        resultado[parametros.length + 1] = desplazamiento;
        return resultado;
    }

    private static String patronBusqueda(String busqueda) {
        String literal = busqueda.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
        return "%" + literal + "%";
    }

    private static Operador mapearOperador(ResultSet rs, int fila) throws SQLException {
        return new Operador(
                rs.getObject("id", UUID.class),
                rs.getString("nombres"),
                rs.getString("primer_apellido"),
                rs.getString("segundo_apellido"),
                rs.getString("correo"),
                EstadoCuentaOperador.valueOf(rs.getString("estado")),
                rs.getString("estado_invitacion"),
                rs.getBoolean("puede_reemitir_invitacion"),
                rs.getString("empleado_id_texto"),
                rs.getString("estado_conciliacion"));
    }

    private static CuentaOperadorAdministrable mapearCuentaAdministrable(ResultSet rs, int fila)
            throws SQLException {
        Timestamp creada = rs.getTimestamp("creada_en");
        return new CuentaOperadorAdministrable(
                rs.getObject("id", UUID.class),
                rs.getString("nombres"),
                rs.getString("primer_apellido"),
                rs.getString("segundo_apellido"),
                rs.getString("correo"),
                EstadoCuentaOperador.valueOf(rs.getString("estado")),
                creada == null ? null : creada.toInstant(),
                rs.getLong("revision_acceso"),
                (Long) rs.getObject("empleado_id"));
    }
}
