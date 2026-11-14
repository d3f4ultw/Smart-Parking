package mx.smartparking.api.clientes.administracion.persistencia;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.OptionalLong;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/** Busca los clientes y la información de membresía guardada para el panel de administración. */
@Repository
public class RepositorioClientesAdministracionJdbc implements RepositorioClientesAdministracion {

    private static final int TAMANO_MAXIMO_PAGINA = 100;
    private static final String PROYECCION_CLIENTES = """
            WITH clientes AS (
                SELECT cp.numero, c.nombres, c.primer_apellido, c.segundo_apellido,
                       COALESCE(s.estado, CASE WHEN p.intento_id IS NULL
                                               THEN 'SIN_MEMBRESIA' ELSE 'PENDIENTE' END) AS estado_membresia,
                       s.periodo_inicio, s.periodo_fin,
                       CASE WHEN s.estado = 'ACTIVA' AND s.cancel_at_period_end = FALSE
                            THEN s.periodo_fin ELSE NULL END AS siguiente_cobro_en,
                       COALESCE(s.cancel_at_period_end, FALSE) AS cancelacion_al_final
                FROM cuenta c
                JOIN cliente_codigo_publico cp ON cp.cliente_id = c.id
                LEFT JOIN LATERAL (
                    SELECT estado, periodo_inicio, periodo_fin, cancel_at_period_end
                    FROM suscripcion_cliente
                    WHERE cliente_id = c.id
                    ORDER BY CASE WHEN estado IN ('PENDIENTE', 'ACTIVA', 'PAGO_VENCIDO')
                                  THEN 0 ELSE 1 END,
                             evento_creado_en DESC, stripe_subscription_id DESC
                    LIMIT 1
                ) s ON TRUE
                LEFT JOIN LATERAL (
                    SELECT intento_id
                    FROM intento_checkout
                    WHERE cliente_id = c.id
                      AND estado IN ('RESERVADO', 'ABIERTO', 'RECONCILIANDO', 'INDETERMINADO')
                    ORDER BY creado_en DESC, intento_id DESC
                    LIMIT 1
                ) p ON TRUE
                WHERE c.rol = 'CLIENTE'
            )
            """;

    private static final RowMapper<ClienteFilaPersistido> MAPA_FILA = (rs, fila) ->
            new ClienteFilaPersistido(
                    codigoPublico(rs.getLong("numero")), rs.getString("nombres"),
                    rs.getString("primer_apellido"), rs.getString("segundo_apellido"),
                    rs.getString("estado_membresia"));

    private static final RowMapper<DetalleClientePersistido> MAPA_DETALLE = (rs, fila) ->
            new DetalleClientePersistido(
                    codigoPublico(rs.getLong("numero")), rs.getString("nombres"),
                    rs.getString("primer_apellido"), rs.getString("segundo_apellido"),
                    rs.getString("estado_membresia"), instante(rs, "periodo_inicio"),
                    instante(rs, "periodo_fin"), instante(rs, "siguiente_cobro_en"),
                    rs.getBoolean("cancelacion_al_final"));

    private final JdbcTemplate jdbc;
    private final TransactionTemplate transaccionLectura;

    public RepositorioClientesAdministracionJdbc(
            JdbcTemplate jdbc, PlatformTransactionManager administradorTransacciones) {
        this.jdbc = jdbc;
        transaccionLectura = new TransactionTemplate(administradorTransacciones);
        transaccionLectura.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        transaccionLectura.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
        transaccionLectura.setReadOnly(true);
    }

    @Override
    public ResultadoPaginaClientes consultarPagina(
            int pagina, int tamanoPagina, String filtro, String busqueda) {
        if (pagina < 1 || tamanoPagina < 1 || tamanoPagina > TAMANO_MAXIMO_PAGINA) {
            throw new IllegalArgumentException("La página o su tamaño no son válidos.");
        }
        String condicion = condicionFiltro(filtro);
        List<Object> parametrosFiltro = new ArrayList<>();
        if (busqueda != null && !busqueda.isBlank()) {
            String patron = patronBusqueda(busqueda);
            condicion += " " + """
                    AND (concat_ws(' ', nombres, primer_apellido, segundo_apellido) ILIKE ? ESCAPE E'\\\\'
                         OR ('CLI-' || lpad(numero::text, greatest(4, length(numero::text)), '0'))
                            ILIKE ? ESCAPE E'\\\\')
                    """;
            parametrosFiltro.add(patron);
            parametrosFiltro.add(patron);
        }
        String condicionConsulta = condicion;
        return transaccionLectura.execute(estado -> {
            long totalClientes = contar("SELECT count(*) FROM cuenta WHERE rol = 'CLIENTE'");
            long totalRegistros = contar(PROYECCION_CLIENTES
                    + " SELECT count(*) FROM clientes WHERE " + condicionConsulta, parametrosFiltro.toArray());
            int totalPaginas = totalPaginas(totalRegistros, tamanoPagina);
            int paginaEfectiva = Math.min(pagina, Math.max(totalPaginas, 1));
            long desplazamiento = Math.multiplyExact((long) paginaEfectiva - 1, tamanoPagina);
            List<Object> parametrosPagina = new ArrayList<>(parametrosFiltro);
            parametrosPagina.add(tamanoPagina);
            parametrosPagina.add(desplazamiento);
            List<ClienteFilaPersistido> items = jdbc.query(PROYECCION_CLIENTES + """
                    SELECT numero, nombres, primer_apellido, segundo_apellido, estado_membresia
                    FROM clientes
                    WHERE """ + " " + condicionConsulta + " ORDER BY numero ASC LIMIT ? OFFSET ?",
                    MAPA_FILA, parametrosPagina.toArray());
            return new ResultadoPaginaClientes(
                    items, paginaEfectiva, totalClientes, totalRegistros, totalPaginas);
        });
    }

    @Override
    public Optional<DetalleClientePersistido> consultarDetalle(String codigoPublico) {
        OptionalLong numero = numeroDeCodigo(codigoPublico);
        if (numero.isEmpty()) {
            return Optional.empty();
        }
        return transaccionLectura.execute(estado -> jdbc.query(PROYECCION_CLIENTES + """
                SELECT numero, nombres, primer_apellido, segundo_apellido, estado_membresia,
                       periodo_inicio, periodo_fin, siguiente_cobro_en, cancelacion_al_final
                FROM clientes
                WHERE numero = ?
                """, MAPA_DETALLE, numero.getAsLong()).stream().findFirst());
    }

    private long contar(String consulta, Object... parametros) {
        Long total = jdbc.queryForObject(consulta, Long.class, parametros);
        return total == null ? 0 : total;
    }

    private static String patronBusqueda(String busqueda) {
        String literal = busqueda.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
        return "%" + literal + "%";
    }

    private static String condicionFiltro(String filtro) {
        String normalizado = filtro == null ? "todos" : filtro.strip().toLowerCase(Locale.ROOT);
        return switch (normalizado) {
            case "todos" -> "TRUE";
            case "activa" -> "estado_membresia = 'ACTIVA'";
            case "cancelada" -> "estado_membresia = 'CANCELADA'";
            case "sin-membresia" -> "estado_membresia IN "
                    + "('SIN_MEMBRESIA', 'PENDIENTE', 'PAGO_VENCIDO', 'INACTIVA')";
            default -> throw new IllegalArgumentException("El filtro de membresía no es válido.");
        };
    }

    private static OptionalLong numeroDeCodigo(String codigoPublico) {
        if (codigoPublico == null || !codigoPublico.matches("CLI-[0-9]{4,}")) {
            return OptionalLong.empty();
        }
        try {
            long numero = Long.parseLong(codigoPublico.substring(4));
            return numero > 0 && codigoPublico.equals(codigoPublico(numero))
                    ? OptionalLong.of(numero) : OptionalLong.empty();
        } catch (NumberFormatException excepcion) {
            return OptionalLong.empty();
        }
    }

    private static String codigoPublico(long numero) {
        return String.format(Locale.ROOT, "CLI-%04d", numero);
    }

    private static int totalPaginas(long totalRegistros, int tamanoPagina) {
        long paginas = totalRegistros / tamanoPagina;
        if (totalRegistros % tamanoPagina != 0) {
            paginas++;
        }
        return Math.toIntExact(paginas);
    }

    private static Instant instante(ResultSet rs, String columna) throws SQLException {
        Timestamp marca = rs.getTimestamp(columna);
        return marca == null ? null : marca.toInstant();
    }
}
