package mx.smartparking.api.rfid3.persistencia;

import java.sql.SQLException;
import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.historial.persistencia.RepositorioEventoAccesoJdbc;
import mx.smartparking.api.persistencia.CargadorSql;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/** Guarda el fin de las visitas y reconoce los resultados de salidas que ya fueron confirmadas. */
@Repository
public class RepositorioRfid3Jdbc implements RepositorioRfid3 {

    // Este número distingue las lecturas de salida de otras operaciones que pueden ocurrir al mismo tiempo.
    private static final int ESPACIO_BLOQUEO_RFID3 = 0x52464933;
    private static final int LIMITE_TRANSACCION_SEGUNDOS = 2;
    private static final String RESTRICCION_SALIDA = "movimiento_estacionamiento_salida_lectura_uq";

    private final String sqlBloquearLecturaAdvisory =
            CargadorSql.cargar("compartido/bloquear_lectura_advisory.sql");
    private final String sqlBuscarUidPorSalida = CargadorSql.cargar("rfid3/buscar_uid_por_salida.sql");
    private final String sqlBloquearAsociacionPorUid = CargadorSql.cargar("rfid3/bloquear_asociacion_por_uid.sql");
    private final String sqlBuscarMovimientoAbierto = CargadorSql.cargar("rfid3/buscar_movimiento_abierto.sql");
    private final String sqlBloquearSolicitudesSalidaManual =
            CargadorSql.cargar("rfid3/bloquear_solicitudes_salida_manual.sql");
    private final String sqlAnularSolicitudPendiente = CargadorSql.cargar("rfid3/anular_solicitud_pendiente.sql");
    private final String sqlConsultarZonaHoraria = CargadorSql.cargar("compartido/consultar_zona_horaria.sql");
    private final String sqlCerrarMovimiento = CargadorSql.cargar("rfid3/cerrar_movimiento.sql");

    private final JdbcTemplate jdbc;
    private final TransactionTemplate transaccion;
    private final Clock reloj;
    private final RepositorioEventoAccesoJdbc eventosAcceso;

    @Autowired
    public RepositorioRfid3Jdbc(
            JdbcTemplate jdbc,
            PlatformTransactionManager administrador,
            RepositorioEventoAccesoJdbc eventosAcceso) {
        this(jdbc, administrador, Clock.systemUTC(), eventosAcceso);
    }

    RepositorioRfid3Jdbc(JdbcTemplate jdbc, PlatformTransactionManager administrador, Clock reloj) {
        this(jdbc, administrador, reloj, new RepositorioEventoAccesoJdbc(jdbc, null));
    }

    RepositorioRfid3Jdbc(
            JdbcTemplate jdbc,
            PlatformTransactionManager administrador,
            Clock reloj,
            RepositorioEventoAccesoJdbc eventosAcceso) {
        this.jdbc = jdbc;
        this.reloj = reloj;
        this.eventosAcceso = eventosAcceso;
        this.transaccion = new TransactionTemplate(administrador);
        this.transaccion.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        this.transaccion.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
        this.transaccion.setTimeout(LIMITE_TRANSACCION_SEGUNDOS);
    }

    @Override
    public ResultadoSalidaRfid3 registrarSalida(String uid, UUID lecturaId) {
        try {
            // La decisión se devuelve cuando el cambio ya quedó guardado.
            return transaccion.execute(estado -> cerrarEnTransaccion(uid, lecturaId));
        } catch (RuntimeException excepcion) {
            if (!esConflictoUnicidadSalida(excepcion)) {
                throw excepcion;
            }
            // Tras terminar el intento fallido, se consulta si la misma salida ya quedó guardada.
            Optional<String> anterior = transaccion.execute(estado -> buscarUidPorSalida(lecturaId));
            if (anterior == null || anterior.isEmpty()) {
                throw excepcion;
            }
            return resultadoReplay(uid, anterior.get());
        }
    }

    private ResultadoSalidaRfid3 cerrarEnTransaccion(String uid, UUID lecturaId) {
        Optional<String> anterior = buscarUidPorSalida(lecturaId);
        if (anterior.isPresent()) {
            return resultadoReplay(uid, anterior.get());
        }

        jdbc.query(sqlBloquearLecturaAdvisory, rs -> null,
                ESPACIO_BLOQUEO_RFID3, claveBloqueo(lecturaId));
        anterior = buscarUidPorSalida(lecturaId);
        if (anterior.isPresent()) {
            return resultadoReplay(uid, anterior.get());
        }

        Optional<Asociacion> asociacion = jdbc.query(sqlBloquearAsociacionPorUid,
                (rs, fila) -> new Asociacion(rs.getLong(1), rs.getString(2)), uid).stream().findFirst();
        anterior = buscarUidPorSalida(lecturaId);
        if (anterior.isPresent()) {
            return resultadoReplay(uid, anterior.get());
        }
        if (asociacion.isEmpty()) {
            return denegar(lecturaId, "TARJETA_DESCONOCIDA", null);
        }
        if (!"ACTIVA".equals(asociacion.get().estado())
                && !"CANCELADA".equals(asociacion.get().estado())) {
            return denegar(lecturaId, "TARJETA_CANCELADA", asociacion.get().id());
        }

        long asociacionId = asociacion.get().id();
        Optional<Movimiento> movimiento = jdbc.query(sqlBuscarMovimientoAbierto,
                (rs, fila) -> new Movimiento(rs.getLong(1),
                        rs.getObject(2, OffsetDateTime.class).toInstant()), asociacionId).stream().findFirst();
        if (movimiento.isEmpty()) {
            String motivo = "CANCELADA".equals(asociacion.get().estado())
                    ? "TARJETA_CANCELADA" : "SIN_ENTRADA_ABIERTA";
            return denegar(lecturaId, motivo, asociacionId);
        }

        // No se acepta otra salida si una solicitud manual fue enviada o su resultado es incierto.
        // El paso del tiempo no confirma que la barrera se haya cerrado.
        java.util.List<String> solicitudes = jdbc.query(sqlBloquearSolicitudesSalidaManual,
                (rs, fila) -> rs.getString(1), movimiento.get().id());
        if (solicitudes.stream().anyMatch(estado -> "EMITIDA".equals(estado) || "INCIERTA".equals(estado))) {
            return denegar(lecturaId, "SALIDA_MANUAL_EN_CURSO", asociacionId);
        }
        if (solicitudes.contains("PENDIENTE")) {
            jdbc.update(sqlAnularSolicitudPendiente, movimiento.get().id());
        }

        ZoneId zona = obtenerZona();
        Instant instante = reloj.instant().truncatedTo(ChronoUnit.MICROS);
        if (instante.isBefore(movimiento.get().instanteEntrada())) {
            throw new DataAccessResourceFailureException("No se puede garantizar el orden del reloj para la salida.");
        }
        var local = instante.atZone(zona);
        int actualizadas = jdbc.update(sqlCerrarMovimiento, local.toLocalDate(), local.toLocalTime(),
                OffsetDateTime.ofInstant(instante, ZoneOffset.UTC),
                lecturaId, movimiento.get().id(), asociacionId);
        if (actualizadas != 1) {
            throw new DataAccessResourceFailureException("No se pudo confirmar el movimiento de salida.");
        }
        eventosAcceso.registrar(instante, "RFID3", "AUTORIZADA", null, lecturaId,
                asociacionId, movimiento.get().id());
        return ResultadoSalidaRfid3.autorizada();
    }

    private ResultadoSalidaRfid3 denegar(UUID lecturaId, String motivo, Long asociacionId) {
        Instant ocurridoEn = reloj.instant().truncatedTo(ChronoUnit.MICROS);
        eventosAcceso.registrar(ocurridoEn, "RFID3", "DENEGADA", motivo, lecturaId, asociacionId, null);
        return ResultadoSalidaRfid3.denegada(motivo);
    }

    private Optional<String> buscarUidPorSalida(UUID lecturaId) {
        return jdbc.query(sqlBuscarUidPorSalida, (rs, fila) -> rs.getString(1), lecturaId).stream().findFirst();
    }

    private ZoneId obtenerZona() {
        Optional<String> zona = jdbc.query(sqlConsultarZonaHoraria,
                (rs, fila) -> rs.getString(1)).stream().findFirst();
        if (zona.isEmpty() || !ZoneId.getAvailableZoneIds().contains(zona.get())) {
            throw new DataAccessResourceFailureException("La zona horaria configurada no está disponible.");
        }
        return ZoneId.of(zona.get());
    }

    private static ResultadoSalidaRfid3 resultadoReplay(String uid, String anterior) {
        if (!uid.equals(anterior)) {
            throw new LecturaRfid3ConflictException();
        }
        return ResultadoSalidaRfid3.autorizada();
    }

    private static int claveBloqueo(UUID uuid) {
        long superior = uuid.getMostSignificantBits();
        long inferior = uuid.getLeastSignificantBits();
        return (int) (superior >>> 32) ^ (int) superior ^ (int) (inferior >>> 32) ^ (int) inferior;
    }

    private static boolean esConflictoUnicidadSalida(Throwable excepcion) {
        for (Throwable causa = excepcion; causa != null; causa = causa.getCause()) {
            if (causa instanceof SQLException sql) {
                for (SQLException detalle = sql; detalle != null; detalle = detalle.getNextException()) {
                    String mensaje = detalle.getMessage();
                    if ("23505".equals(detalle.getSQLState()) && mensaje != null
                            && mensaje.contains("\"" + RESTRICCION_SALIDA + "\"")) {
                        return true;
                    }
                }
            }
        }
        return false;
    }

    private record Asociacion(long id, String estado) { }

    private record Movimiento(long id, Instant instanteEntrada) { }
}
