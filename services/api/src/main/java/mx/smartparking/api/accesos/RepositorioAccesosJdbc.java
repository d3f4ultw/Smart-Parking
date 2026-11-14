package mx.smartparking.api.accesos;

import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.persistencia.CargadorSql;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** Consulta la capacidad configurada y las visitas abiertas del estacionamiento. */
@Repository
public class RepositorioAccesosJdbc {
    private static final String ORIGEN_VISITAS = """
            FROM movimiento_estacionamiento movimiento
            JOIN asociacion_tarjeta_rfid1 tarjeta ON tarjeta.asociacion_id = movimiento.asociacion_id
            LEFT JOIN cliente_codigo_publico codigo ON codigo.cliente_id = movimiento.cliente_id
            LEFT JOIN cuenta ON cuenta.id = movimiento.cliente_id
            LEFT JOIN empleado ON empleado.id = movimiento.empleado_id
            """;
    private static final String CODIGO_PERSONA = """
            CASE WHEN movimiento.tipo_persona = 'CLIENTE'
                 THEN 'CLI-' || lpad(codigo.numero::text, GREATEST(4, length(codigo.numero::text)), '0')
                 ELSE 'E-' || lpad(empleado.id::text, GREATEST(4, length(empleado.id::text)), '0')
            END
            """;
    private static final String NOMBRE_PERSONA = """
            CASE WHEN movimiento.tipo_persona = 'CLIENTE'
                 THEN concat_ws(' ', cuenta.nombres, cuenta.primer_apellido, cuenta.segundo_apellido)
                 ELSE concat_ws(' ', empleado.nombres, empleado.primer_apellido, empleado.segundo_apellido)
            END
            """;
    private static final String FILTRO_VISITAS = """
            movimiento.instante_salida IS NULL
            AND (? = '' OR (%s) ILIKE ? ESCAPE '!' OR (%s) ILIKE ? ESCAPE '!')
            """.formatted(NOMBRE_PERSONA, CODIGO_PERSONA);
    private final String sqlConsultarCapacidad = CargadorSql.cargar("accesos/consultar_capacidad.sql");
    private final String sqlConsultarZonaHoraria = CargadorSql.cargar("accesos/consultar_zona_horaria.sql");
    private final JdbcTemplate jdbc;

    public RepositorioAccesosJdbc(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * Consulta en un mismo momento los lugares configurados y los ocupados para presentar cifras
     * coherentes.
     */
    public Capacidad consultarCapacidad() {
        List<Capacidad> filas = jdbc.query(sqlConsultarCapacidad,
                (rs, fila) -> new Capacidad(rs.getLong("capacidad"), rs.getLong("dentro")));
        if (filas.size() != 1) {
            throw new DataAccessResourceFailureException("La capacidad no está disponible.");
        }
        return filas.getFirst();
    }

    public String consultarZonaHoraria() {
        List<String> zonas = jdbc.query(sqlConsultarZonaHoraria, (rs, fila) -> rs.getString(1));
        if (zonas.size() != 1 || zonas.getFirst() == null) {
            throw new DataAccessResourceFailureException("La zona horaria no está disponible.");
        }
        return zonas.getFirst();
    }

    /**
     * Incluye las visitas de tarjetas canceladas sin consultar el número de tarjeta ni otros
     * identificadores privados.
     */
    public Pagina consultarDentro(int pagina, String busqueda) {
        long offset = (long) (pagina - 1) * 10;
        String patron = "%" + busqueda.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%";
        Long total = jdbc.queryForObject("SELECT count(*) " + ORIGEN_VISITAS + " WHERE " + FILTRO_VISITAS,
                Long.class, busqueda, patron, patron);
        if (total == null) {
            throw new DataAccessResourceFailureException("No se pudo contar las visitas abiertas.");
        }
        List<Visita> items = jdbc.query("""
                SELECT movimiento.movimiento_id, movimiento.tipo_persona,
                       movimiento.instante_entrada, tarjeta.estado AS estado_tarjeta,
                       solicitud.operacion_id,
                       CASE WHEN solicitud.estado = 'PENDIENTE' AND solicitud.vence_en <= clock_timestamp()
                                THEN 'ANULADA'
                            WHEN solicitud.estado = 'EMITIDA'
                                 AND solicitud.emitida_en + interval '10 seconds' <= clock_timestamp()
                                THEN 'INCIERTA'
                            ELSE solicitud.estado END AS estado_manual,
                       (%s) AS nombre_persona, (%s) AS codigo_persona
                %s
                LEFT JOIN LATERAL (
                    SELECT operacion_id, estado, vence_en, emitida_en
                    FROM solicitud_salida_manual WHERE movimiento_id = movimiento.movimiento_id
                    ORDER BY creada_en DESC, operacion_id DESC LIMIT 1
                ) solicitud ON true
                WHERE %s
                ORDER BY movimiento.instante_entrada DESC, movimiento.movimiento_id DESC
                LIMIT 10 OFFSET ?
                """.formatted(NOMBRE_PERSONA, CODIGO_PERSONA, ORIGEN_VISITAS, FILTRO_VISITAS),
                (rs, fila) -> new Visita(
                rs.getLong("movimiento_id"),
                rs.getString("tipo_persona"),
                rs.getString("nombre_persona"),
                rs.getString("codigo_persona"),
                rs.getString("estado_tarjeta"),
                rs.getObject("instante_entrada", OffsetDateTime.class).toInstant(),
                rs.getObject("operacion_id", UUID.class), rs.getString("estado_manual")), busqueda, patron, patron, offset);
        return new Pagina(List.copyOf(items), total, offset + items.size() < total);
    }

    public record Capacidad(long total, long dentro) { }
    public record Visita(long id, String tipoPersona, String nombrePersona, String codigoPersona,
                         String estadoTarjeta, Instant entrada, UUID operacionId, String estadoManual) {
        public Visita(long id, String tipoPersona, String nombrePersona, String codigoPersona,
                      String estadoTarjeta, Instant entrada) {
            this(id, tipoPersona, nombrePersona, codigoPersona, estadoTarjeta, entrada, null, null);
        }
    }
    public record Pagina(List<Visita> items, long total, boolean haySiguiente) { }
}

