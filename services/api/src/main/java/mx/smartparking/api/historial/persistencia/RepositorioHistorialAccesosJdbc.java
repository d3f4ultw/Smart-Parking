package mx.smartparking.api.historial.persistencia;

import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.ZoneId;
import java.util.List;
import mx.smartparking.api.persistencia.CargadorSql;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** Busca los accesos recientes y, cuando sea posible, los nombres asociados actualmente a las tarjetas. */
@Repository
public class RepositorioHistorialAccesosJdbc {

    private static final int TAMANO_PAGINA = 10;

    private final JdbcTemplate jdbc;
    private final String sqlConsultarZonaHoraria = CargadorSql.cargar("compartido/consultar_zona_horaria.sql");
    private final String sqlContarEventos = CargadorSql.cargar("historial/contar_eventos.sql");
    private final String sqlConsultarEventos = CargadorSql.cargar("historial/consultar_eventos.sql");

    public RepositorioHistorialAccesosJdbc(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** obtiene y valida la zona horaria activa para presentar las horas del historial. */
    public String consultarZonaHoraria() {
        String zona = jdbc.query(sqlConsultarZonaHoraria, (fila, numero) -> fila.getString(1)).stream().findFirst()
                .orElseThrow(() -> new DataAccessResourceFailureException(
                        "La zona horaria del estacionamiento no está disponible."));
        if (!ZoneId.getAvailableZoneIds().contains(zona)) {
            throw new DataAccessResourceFailureException("La zona horaria del estacionamiento no está disponible.");
        }
        return zona;
    }

    /** Obtiene el total y la página solicitada de la misma consulta para mantenerlos de acuerdo. */
    public ConsultaHistorialAccesos consultar(
            int pagina, String lector, String resultado, String zona, Instant desde, Instant hasta) {
        long offset = (long) (pagina - 1) * TAMANO_PAGINA;
        OffsetDateTime desdeUtc = fechaUtc(desde);
        OffsetDateTime hastaUtc = fechaUtc(hasta);
        long totalRegistros = jdbc.queryForObject(sqlContarEventos,
                Long.class, parametros(lector, resultado, desdeUtc, hastaUtc));
        List<FilaHistorialAcceso> filas = jdbc.query(sqlConsultarEventos, (fila, numero) -> {
            OffsetDateTime ocurrido = fila.getObject("ocurrido_en", OffsetDateTime.class);
            String nombre = fila.getString("nombre_persona");
            if (nombre != null && nombre.isBlank()) {
                nombre = null;
            }
            return new FilaHistorialAcceso(
                    fila.getLong("evento_id"), ocurrido.toInstant(), fila.getString("lector"),
                    fila.getString("resultado"), fila.getString("motivo"),
                    nombre == null ? null : fila.getString("tipo_persona"), nombre);
        }, parametros(lector, resultado, desdeUtc, hastaUtc, TAMANO_PAGINA, offset));
        boolean haySiguiente = offset + filas.size() < totalRegistros;
        return new ConsultaHistorialAccesos(zona, List.copyOf(filas), totalRegistros, haySiguiente);
    }

    private static Object[] parametros(String lector, String resultado, OffsetDateTime desde, OffsetDateTime hasta) {
        return new Object[] {lector, lector, resultado, resultado, desde, desde, hasta, hasta};
    }

    private static Object[] parametros(
            String lector, String resultado, OffsetDateTime desde, OffsetDateTime hasta, int limite, long offset) {
        Object[] parametros = parametros(lector, resultado, desde, hasta);
        return new Object[] {parametros[0], parametros[1], parametros[2], parametros[3],
                parametros[4], parametros[5], parametros[6], parametros[7], limite, offset};
    }

    private static OffsetDateTime fechaUtc(Instant fecha) {
        return fecha == null ? null : fecha.atOffset(ZoneOffset.UTC);
    }
}
