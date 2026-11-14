package mx.smartparking.api.rfid1.persistencia;

import static mx.smartparking.api.rfid1.persistencia.RepositorioTarjetasRfid.CandidatoRfid1Persistido;
import static mx.smartparking.api.rfid1.persistencia.RepositorioTarjetasRfid.ResultadoCancelacionTarjetaRfid1;
import static mx.smartparking.api.rfid1.persistencia.RepositorioTarjetasRfid.TarjetaRfid1Persistida;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import mx.smartparking.api.persistencia.CargadorSql;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

/** Consulta candidatos RFID, incluidos los no elegibles, y el historial de tarjetas sin cambiar datos personales. */
@Repository
public class RepositorioTarjetasRfidJdbc implements RepositorioTarjetasRfid {

    private static final int LIMITE_BUSQUEDA = 10;
    private static final RowMapper<TarjetaRfid1Persistida> MAPA_TARJETA = RepositorioTarjetasRfidJdbc::mapearTarjeta;
    private static final String ORIGEN_DIRECTORIO = """
            FROM asociacion_tarjeta_rfid1 AS tarjeta
            LEFT JOIN cliente_codigo_publico AS codigo ON codigo.cliente_id = tarjeta.cliente_id
            LEFT JOIN cuenta ON cuenta.id = tarjeta.cliente_id
            LEFT JOIN empleado ON empleado.id = tarjeta.empleado_id
            """;
    private static final String FILTRO_BUSQUEDA_DIRECTORIO = """
            (? = '' OR tarjeta.uid_canonico ILIKE ? ESCAPE '!'
                OR concat_ws(' ',
                    NULLIF(btrim(COALESCE(cuenta.nombres, empleado.nombres)), ''),
                    NULLIF(btrim(COALESCE(cuenta.primer_apellido, empleado.primer_apellido)), ''),
                    NULLIF(btrim(COALESCE(cuenta.segundo_apellido, empleado.segundo_apellido)), '')
                ) ILIKE ? ESCAPE '!'
                OR (CASE WHEN tarjeta.cliente_id IS NOT NULL
                    THEN 'CLI-' || lpad(codigo.numero::text, GREATEST(4, length(codigo.numero::text)), '0')
                    ELSE 'E-' || lpad(empleado.id::text, GREATEST(4, length(empleado.id::text)), '0')
                END) ILIKE ? ESCAPE '!')
            """;
    private static final String FILTRO_BUSQUEDA_DIRECTORIO_SIN_UID = """
            (? = '' OR concat_ws(' ',
                    NULLIF(btrim(COALESCE(cuenta.nombres, empleado.nombres)), ''),
                    NULLIF(btrim(COALESCE(cuenta.primer_apellido, empleado.primer_apellido)), ''),
                    NULLIF(btrim(COALESCE(cuenta.segundo_apellido, empleado.segundo_apellido)), '')
                ) ILIKE ? ESCAPE '!'
                OR (CASE WHEN tarjeta.cliente_id IS NOT NULL
                    THEN 'CLI-' || lpad(codigo.numero::text, GREATEST(4, length(codigo.numero::text)), '0')
                    ELSE 'E-' || lpad(empleado.id::text, GREATEST(4, length(empleado.id::text)), '0')
                END) ILIKE ? ESCAPE '!')
            """;
    private final JdbcTemplate jdbc;
    private final String sqlBuscarPersonasCliente;
    private final String sqlBuscarPersonasEmpleado;
    private final String sqlBuscarPersonasMixto;
    private final String sqlBuscarTarjetaConUid;
    private final String sqlBuscarTarjetaSinUid;
    private final String sqlBuscarDestinoTarjeta;
    private final String sqlBloquearClienteTarjeta;
    private final String sqlBloquearEmpleadoTarjeta;
    private final String sqlBuscarEstadoTarjetaBloqueada;
    private final String sqlCancelarTarjeta;

    public RepositorioTarjetasRfidJdbc(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
        this.sqlBuscarPersonasCliente = CargadorSql.cargar("rfid1/buscar_personas_cliente.sql");
        this.sqlBuscarPersonasEmpleado = CargadorSql.cargar("rfid1/buscar_personas_empleado.sql");
        this.sqlBuscarPersonasMixto = CargadorSql.cargar("rfid1/buscar_personas_mixto.sql");
        this.sqlBuscarTarjetaConUid = CargadorSql.cargar("rfid1/buscar_tarjeta_con_uid.sql");
        this.sqlBuscarTarjetaSinUid = CargadorSql.cargar("rfid1/buscar_tarjeta_sin_uid.sql");
        this.sqlBuscarDestinoTarjeta = CargadorSql.cargar("rfid1/buscar_destino_tarjeta.sql");
        this.sqlBloquearClienteTarjeta = CargadorSql.cargar("compartido/bloquear_cliente.sql");
        this.sqlBloquearEmpleadoTarjeta = CargadorSql.cargar("compartido/bloquear_empleado.sql");
        this.sqlBuscarEstadoTarjetaBloqueada = CargadorSql.cargar("rfid1/buscar_estado_tarjeta_bloqueada.sql");
        this.sqlCancelarTarjeta = CargadorSql.cargar("rfid1/cancelar_tarjeta.sql");
    }

    @Override
    public List<CandidatoRfid1Persistido> buscarPersonas(String tipoEntidad, String busqueda, int limite) {
        if (busqueda == null || busqueda.strip().codePointCount(0, busqueda.strip().length()) < 2 || limite <= 0) {
            return List.of();
        }
        int cantidad = Math.min(limite, LIMITE_BUSQUEDA);
        String patron = "%" + busqueda.strip() + "%";
        return switch (tipoEntidad == null ? "" : tipoEntidad) {
            case "CLIENTE" -> jdbc.query(sqlBuscarPersonasCliente, (rs, fila) -> new CandidatoRfid1Persistido(
                    "CLIENTE", codigoCliente(rs.getLong("numero")), nombreCompleto(rs),
                    rs.getString("estado"), rs.getBoolean("tiene_activa"), rs.getString("estado_membresia")),
                    patron, cantidad);
            case "EMPLEADO" -> jdbc.query(sqlBuscarPersonasEmpleado, (rs, fila) -> new CandidatoRfid1Persistido(
                    "EMPLEADO", codigoEmpleado(rs.getLong("id")), nombreCompleto(rs),
                    rs.getString("estado"), rs.getBoolean("tiene_activa"), rs.getString("estado_membresia")),
                    patron, cantidad);
            case "MIXTO" -> jdbc.query(sqlBuscarPersonasMixto, (rs, fila) -> {
                    String tipo = rs.getString("tipo_entidad");
                    String codigo = "CLIENTE".equals(tipo)
                            ? codigoCliente(rs.getLong("numero"))
                            : codigoEmpleado(rs.getLong("numero"));
                    return new CandidatoRfid1Persistido(
                            tipo, codigo, nombreCompleto(rs), rs.getString("estado"),
                            rs.getBoolean("tiene_activa"), rs.getString("estado_membresia"));
                }, patron, cantidad, patron, cantidad, cantidad);
            default -> List.of();
        };
    }

    @Override
    public List<TarjetaRfid1Persistida> listarTarjetas(
            String tipoEntidad, String estado, String busqueda, int offset, int limite) {
        return listarTarjetas(tipoEntidad, estado, busqueda, offset, limite, true);
    }

    @Override
    public List<TarjetaRfid1Persistida> listarTarjetas(
            String tipoEntidad, String estado, String busqueda, int offset, int limite, boolean incluirUid) {
        if (offset < 0 || limite <= 0) {
            return List.of();
        }
        String filtroTipo = filtroTipo(tipoEntidad);
        String filtroEstado = filtroEstado(estado);
        String termino = busqueda == null ? "" : busqueda;
        String patron = patronBusqueda(termino);
        String proyeccionUid = incluirUid ? "tarjeta.uid_canonico" : "NULL::text AS uid_canonico";
        String filtroBusqueda = incluirUid
                ? FILTRO_BUSQUEDA_DIRECTORIO : FILTRO_BUSQUEDA_DIRECTORIO_SIN_UID;
        Object[] parametrosBusqueda = incluirUid
                ? new Object[] {termino, patron, patron, patron, limite, offset}
                : new Object[] {termino, patron, patron, limite, offset};
        return jdbc.query("""
                SELECT tarjeta.asociacion_id, %s, tarjeta.estado,
                       tarjeta.asociada_en, tarjeta.cancelada_en,
                       (tarjeta.cliente_id IS NOT NULL) AS es_cliente,
                       codigo.numero AS numero_cliente, empleado.id AS numero_empleado,
                       COALESCE(cuenta.nombres, empleado.nombres) AS nombres,
                       COALESCE(cuenta.primer_apellido, empleado.primer_apellido) AS primer_apellido,
                       COALESCE(cuenta.segundo_apellido, empleado.segundo_apellido) AS segundo_apellido
                %s
                WHERE %s AND %s AND %s
                ORDER BY tarjeta.asociada_en DESC, tarjeta.asociacion_id DESC
                LIMIT ? OFFSET ?
                """.formatted(proyeccionUid, ORIGEN_DIRECTORIO, filtroTipo, filtroEstado, filtroBusqueda),
                MAPA_TARJETA, parametrosBusqueda);
    }

    @Override
    public long contarTarjetas(String tipoEntidad, String estado, String busqueda) {
        return contarTarjetas(tipoEntidad, estado, busqueda, true);
    }

    @Override
    public long contarTarjetas(String tipoEntidad, String estado, String busqueda, boolean incluirUid) {
        String termino = busqueda == null ? "" : busqueda;
        String patron = patronBusqueda(termino);
        String filtroBusqueda = incluirUid
                ? FILTRO_BUSQUEDA_DIRECTORIO : FILTRO_BUSQUEDA_DIRECTORIO_SIN_UID;
        Object[] parametrosBusqueda = incluirUid
                ? new Object[] {termino, patron, patron, patron}
                : new Object[] {termino, patron, patron};
        Long total = jdbc.queryForObject("""
                SELECT count(*)
                %s
                WHERE %s AND %s AND %s
                """.formatted(ORIGEN_DIRECTORIO, filtroTipo(tipoEntidad), filtroEstado(estado),
                        filtroBusqueda), Long.class, parametrosBusqueda);
        return total == null ? 0 : total;
    }

    private static String patronBusqueda(String termino) {
        return "%" + termino.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%";
    }

    @Override
    public Optional<TarjetaRfid1Persistida> buscarTarjeta(long asociacionId) {
        return buscarTarjeta(asociacionId, true);
    }

    @Override
    public Optional<TarjetaRfid1Persistida> buscarTarjeta(long asociacionId, boolean incluirUid) {
        String sql = incluirUid ? sqlBuscarTarjetaConUid : sqlBuscarTarjetaSinUid;
        return jdbc.query(sql, MAPA_TARJETA, asociacionId).stream().findFirst();
    }

    @Override
    public ResultadoCancelacionTarjetaRfid1 cancelarTarjeta(long asociacionId, Instant ahora) {
        DestinoTarjeta destino = jdbc.query(sqlBuscarDestinoTarjeta, (rs, fila) -> new DestinoTarjeta(
                rs.getObject("cliente_id", java.util.UUID.class), rs.getObject("empleado_id", Long.class)),
                asociacionId).stream().findFirst().orElse(null);
        if (destino == null) {
            return new ResultadoCancelacionTarjetaRfid1(null, "TARJETA_NO_ENCONTRADA", false);
        }
        if (destino.clienteId() != null) {
            jdbc.query(sqlBloquearClienteTarjeta,
                    (rs, fila) -> rs.getObject("id", java.util.UUID.class), destino.clienteId());
        } else {
            jdbc.query(sqlBloquearEmpleadoTarjeta,
                    (rs, fila) -> rs.getLong("id"), destino.empleadoId());
        }
        String estado = jdbc.query(sqlBuscarEstadoTarjetaBloqueada,
                (rs, fila) -> rs.getString("estado"), asociacionId).stream().findFirst().orElse(null);
        if (estado == null) {
            return new ResultadoCancelacionTarjetaRfid1(null, "TARJETA_NO_ENCONTRADA", false);
        }
        if ("CANCELADA".equals(estado)) {
            return new ResultadoCancelacionTarjetaRfid1("CANCELADA", null, true);
        }
        int filas = jdbc.update(sqlCancelarTarjeta, Timestamp.from(ahora), asociacionId);
        if (filas != 1) {
            throw new DataAccessResourceFailureException("No se pudo cancelar la tarjeta RFID.");
        }
        return new ResultadoCancelacionTarjetaRfid1("CANCELADA", null, false);
    }

    private static String filtroTipo(String tipoEntidad) {
        return switch (tipoEntidad == null || tipoEntidad.isBlank() ? "TODAS" : tipoEntidad) {
            case "TODAS" -> "TRUE";
            case "CLIENTE" -> "tarjeta.cliente_id IS NOT NULL";
            case "EMPLEADO" -> "tarjeta.empleado_id IS NOT NULL";
            case "MIXTO" -> "(tarjeta.cliente_id IS NOT NULL OR tarjeta.empleado_id IS NOT NULL)";
            default -> throw new IllegalArgumentException("El tipo de entidad RFID no es válido.");
        };
    }

    private static String filtroEstado(String estado) {
        return switch (estado == null || estado.isBlank() ? "TODAS" : estado) {
            case "TODAS" -> "TRUE";
            case "ACTIVA" -> "tarjeta.estado = 'ACTIVA'";
            case "CANCELADA" -> "tarjeta.estado = 'CANCELADA'";
            default -> throw new IllegalArgumentException("El estado de tarjeta RFID no es válido.");
        };
    }

    private static TarjetaRfid1Persistida mapearTarjeta(ResultSet rs, int fila) throws SQLException {
        boolean cliente = rs.getBoolean("es_cliente");
        long numero = rs.getLong(cliente ? "numero_cliente" : "numero_empleado");
        return new TarjetaRfid1Persistida(
                rs.getLong("asociacion_id"), rs.getString("uid_canonico"),
                cliente ? "CLIENTE" : "EMPLEADO", cliente ? codigoCliente(numero) : codigoEmpleado(numero),
                nombreCompleto(rs), rs.getString("estado"), instante(rs, "asociada_en"), instante(rs, "cancelada_en"));
    }

    private static String nombreCompleto(ResultSet rs) throws SQLException {
        return java.util.stream.Stream.of(
                rs.getString("nombres"), rs.getString("primer_apellido"), rs.getString("segundo_apellido"))
                .filter(valor -> valor != null && !valor.isBlank()).collect(java.util.stream.Collectors.joining(" "));
    }

    private static String codigoCliente(long numero) {
        return String.format(java.util.Locale.ROOT, "CLI-%04d", numero);
    }

    private static String codigoEmpleado(long numero) {
        return String.format(java.util.Locale.ROOT, "E-%04d", numero);
    }

    private static Instant instante(ResultSet rs, String columna) throws SQLException {
        Timestamp marca = rs.getTimestamp(columna);
        return marca == null ? null : marca.toInstant();
    }

    record DestinoTarjeta(java.util.UUID clienteId, Long empleadoId) {
    }
}
