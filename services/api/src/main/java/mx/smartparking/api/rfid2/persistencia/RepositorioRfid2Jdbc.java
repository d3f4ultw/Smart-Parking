package mx.smartparking.api.rfid2.persistencia;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalTime;
import java.time.ZoneId;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.function.Predicate;
import mx.smartparking.api.historial.persistencia.RepositorioEventoAccesoJdbc;
import mx.smartparking.api.persistencia.CargadorSql;
import mx.smartparking.api.persistencia.membresia.RepositorioMembresias;
import mx.smartparking.api.persistencia.membresia.RepositorioMembresiasJdbc;
import mx.smartparking.api.persistencia.membresia.ResumenMembresiaPersistido;
import mx.smartparking.api.rfid2.PlazoEntradaRfid2;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Guarda las entradas sin duplicar lecturas repetidas y evita que cambios simultáneos produzcan
 * registros incompatibles.
 */
@Repository
public class RepositorioRfid2Jdbc implements RepositorioRfid2 {

    private static final int ESPACIO_BLOQUEO_RFID2 = 0x52464932;
    private static final RowMapper<Asociacion> MAPA_ASOCIACION = RepositorioRfid2Jdbc::mapearAsociacion;
    private static final RowMapper<String> MAPA_UID = (rs, fila) -> rs.getString(1);
    private static final RowMapper<Long> MAPA_MOVIMIENTO = (rs, fila) -> rs.getLong(1);
    private final String sqlBloquearLecturaAdvisory =
            CargadorSql.cargar("compartido/bloquear_lectura_advisory.sql");
    private final String sqlBuscarUidPorLectura = CargadorSql.cargar("rfid2/buscar_uid_por_lectura.sql");
    private final String sqlBuscarAsociacionPorUid = CargadorSql.cargar("rfid2/buscar_asociacion_por_uid.sql");
    private final String sqlBloquearAsociacionPorUid = CargadorSql.cargar("rfid2/bloquear_asociacion_por_uid.sql");
    private final String sqlBloquearConfiguracion = CargadorSql.cargar("rfid2/bloquear_configuracion.sql");
    private final String sqlBloquearCliente = CargadorSql.cargar("compartido/bloquear_cliente.sql");
    private final String sqlBloquearEmpleado = CargadorSql.cargar("compartido/bloquear_empleado.sql");
    private final String sqlConsultarEntradaAbierta = CargadorSql.cargar("rfid2/consultar_entrada_abierta.sql");
    private final String sqlConsultarUltimaSalida = CargadorSql.cargar("rfid2/consultar_ultima_salida.sql");
    private final String sqlConsultarCapacidadCompleta =
            CargadorSql.cargar("rfid2/consultar_capacidad_completa.sql");
    private final String sqlRegistrarMovimiento = CargadorSql.cargar("rfid2/registrar_movimiento.sql");
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transaccion;
    private final RepositorioEventoAccesoJdbc eventosAcceso;
    private final RepositorioMembresias membresias;

    @Autowired
    public RepositorioRfid2Jdbc(
            JdbcTemplate jdbc,
            PlatformTransactionManager administradorTransacciones,
            RepositorioEventoAccesoJdbc eventosAcceso,
            RepositorioMembresias membresias) {
        this.jdbc = jdbc;
        this.transaccion = new TransactionTemplate(administradorTransacciones);
        this.transaccion.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
        this.transaccion.setTimeout(2);
        this.eventosAcceso = eventosAcceso;
        this.membresias = membresias;
    }

    /** Permite preparar el acceso a los datos de entrada con los componentes proporcionados directamente. */
    public RepositorioRfid2Jdbc(JdbcTemplate jdbc, PlatformTransactionManager administradorTransacciones,
            RepositorioEventoAccesoJdbc eventosAcceso) {
        this(jdbc, administradorTransacciones, eventosAcceso,
                new RepositorioMembresiasJdbc(jdbc, administradorTransacciones));
    }

    /**
     * Permite preparar el acceso a los datos de entrada cuando no se dispone de la versión posterior
     * del registro.
     */
    public RepositorioRfid2Jdbc(JdbcTemplate jdbc, PlatformTransactionManager administradorTransacciones) {
        this(jdbc, administradorTransacciones, new RepositorioEventoAccesoJdbc(jdbc, null));
    }

    @Override
    public ResultadoEntradaRfid2 registrarEntrada(
            String uid, UUID lecturaId, Clock reloj, ZoneId zonaHoraria, Predicate<LocalTime> dentroDeHorario,
            long revisionConfiguracion, PlazoEntradaRfid2 plazo) {
        plazo.milisegundosRestantes();
        return transaccion.execute(estado -> {
            ResultadoEntradaRfid2 resultado = registrarEnTransaccion(
                    uid, lecturaId, reloj, zonaHoraria, dentroDeHorario, revisionConfiguracion, plazo);
            plazo.milisegundosRestantes();
            return resultado;
        });
    }

    private ResultadoEntradaRfid2 registrarEnTransaccion(
            String uid, UUID lecturaId, Clock reloj, ZoneId zonaHoraria, Predicate<LocalTime> dentroDeHorario,
            long revisionConfiguracion, PlazoEntradaRfid2 plazo) {
        // Los límites de espera solo afectan esta entrada; las demás operaciones conservan sus ajustes.
        long restante = plazo.milisegundosRestantes();
        jdbc.execute("SET LOCAL transaction_timeout = '" + restante + "ms'");
        restante = plazo.milisegundosRestantes();
        if (restante <= 100) {
            throw new DataAccessResourceFailureException("No queda plazo suficiente para confirmar la entrada.");
        }
        jdbc.execute("SET LOCAL lock_timeout = '" + Math.min(1500, restante - 100) + "ms'");
        jdbc.query(sqlBloquearLecturaAdvisory, rs -> null,
                ESPACIO_BLOQUEO_RFID2, claveBloqueo(lecturaId));
        Optional<String> uidAnterior = buscarUidPorLectura(lecturaId);
        if (uidAnterior.isPresent()) {
            return resultadoReplay(uid, uidAnterior.get(), reloj, zonaHoraria, dentroDeHorario);
        }

        // Todas las entradas nuevas y la activación de calibración comparten esta fila.
        UUID estacionamientoId = bloquearConfiguracion(revisionConfiguracion);

        // La identidad de la asociación es inmutable (V12). Cancelación bloquea la persona
        // antes que la tarjeta; respetamos el mismo orden también al insertar el movimiento.
        Optional<Asociacion> preliminar = jdbc.query(sqlBuscarAsociacionPorUid, MAPA_ASOCIACION, uid)
                .stream().findFirst();
        if (preliminar.isEmpty()) {
            return denegar(lecturaId, "TARJETA_DESCONOCIDA", null, reloj, plazo);
        }
        bloquearPersona(preliminar.get());

        Optional<Asociacion> encontrada = jdbc.query(sqlBloquearAsociacionPorUid, MAPA_ASOCIACION, uid)
                .stream().findFirst();
        if (encontrada.isEmpty()) {
            return denegar(lecturaId, "TARJETA_DESCONOCIDA", null, reloj, plazo);
        }
        Asociacion asociacion = encontrada.get();
        if (asociacion.asociacionId() != preliminar.get().asociacionId()
                || !java.util.Objects.equals(asociacion.clienteId(), preliminar.get().clienteId())
                || !java.util.Objects.equals(asociacion.empleadoId(), preliminar.get().empleadoId())) {
            throw new DataAccessResourceFailureException("La asociación cambió durante la entrada.");
        }

        // Otra solicitud de la misma lectura pudo guardarse mientras esta esperaba su turno.
        uidAnterior = buscarUidPorLectura(lecturaId);
        if (uidAnterior.isPresent()) {
            return resultadoReplay(uid, uidAnterior.get(), reloj, zonaHoraria, dentroDeHorario);
        }
        if (!"ACTIVA".equals(asociacion.estado())) {
            return denegar(lecturaId, "TARJETA_CANCELADA", asociacion.asociacionId(), reloj, plazo);
        }
        if (tieneEntradaAbierta(asociacion)) {
            return denegar(lecturaId, "ENTRADA_PENDIENTE", asociacion.asociacionId(), reloj, plazo);
        }

        // Se protege primero la cuenta y después la tarjeta, igual que al cancelarla o recibir avisos de pago.
        ResumenMembresiaPersistido membresia = asociacion.clienteId() == null ? null
                : membresias.consultarResumenParaAcceso(asociacion.clienteId());
        Instant instante = reloj.instant().truncatedTo(ChronoUnit.MICROS);
        OffsetDateTime ultimaSalida =
                jdbc.queryForObject(sqlConsultarUltimaSalida, OffsetDateTime.class, asociacion.asociacionId());
        if (ultimaSalida != null && instante.isBefore(ultimaSalida.toInstant())) {
            throw new DataAccessResourceFailureException("No se puede garantizar el orden del reloj para la entrada.");
        }
        var local = instante.atZone(zonaHoraria);
        if (!dentroDeHorario.test(local.toLocalTime())) {
            return denegar(lecturaId, "FUERA_DE_HORARIO", asociacion.asociacionId(), reloj, plazo);
        }
        if (asociacion.clienteId() != null && !membresiaVigente(membresia, instante)) {
            return denegar(lecturaId, "MEMBRESIA_NO_VIGENTE", asociacion.asociacionId(), reloj, plazo);
        }
        if (capacidadCompleta(estacionamientoId)) {
            return denegar(lecturaId, "CAPACIDAD_COMPLETA", asociacion.asociacionId(), reloj, plazo);
        }
        plazo.milisegundosRestantes();
        List<Long> movimientos = jdbc.query(sqlRegistrarMovimiento, MAPA_MOVIMIENTO,
                asociacion.asociacionId(), asociacion.tipoPersona(), asociacion.clienteId(),
                asociacion.empleadoId(), asociacion.uid(), lecturaId, local.toLocalDate(),
                local.toLocalTime(), OffsetDateTime.ofInstant(instante, ZoneOffset.UTC));
        if (movimientos.isEmpty()) {
            uidAnterior = buscarUidPorLectura(lecturaId);
            if (uidAnterior.isPresent()) {
                return resultadoReplay(uid, uidAnterior.get(), reloj, zonaHoraria, dentroDeHorario);
            }
            return denegar(lecturaId, "ENTRADA_PENDIENTE", asociacion.asociacionId(), reloj, plazo);
        }
        plazo.milisegundosRestantes();
        eventosAcceso.registrar(instante, "RFID2", "AUTORIZADA", null, lecturaId,
                asociacion.asociacionId(), movimientos.getFirst());
        return ResultadoEntradaRfid2.autorizada();
    }

    private ResultadoEntradaRfid2 denegar(UUID lecturaId, String motivo, Long asociacionId, Clock reloj,
            PlazoEntradaRfid2 plazo) {
        Instant ocurridoEn = reloj.instant().truncatedTo(ChronoUnit.MICROS);
        plazo.milisegundosRestantes();
        eventosAcceso.registrar(ocurridoEn, "RFID2", "DENEGADA", motivo, lecturaId, asociacionId, null);
        return ResultadoEntradaRfid2.denegada(motivo);
    }

    private static boolean membresiaVigente(ResumenMembresiaPersistido membresia, Instant instante) {
        // La cancelación al final conserva el acceso solo durante el periodo pagado.
        return membresia != null && "ACTIVA".equals(membresia.estado())
                && membresia.periodoInicio() != null && membresia.periodoFin() != null
                && !instante.isBefore(membresia.periodoInicio()) && instante.isBefore(membresia.periodoFin());
    }

    private Optional<String> buscarUidPorLectura(UUID lecturaId) {
        return jdbc.query(sqlBuscarUidPorLectura, MAPA_UID, lecturaId).stream().findFirst();
    }

    private UUID bloquearConfiguracion(long revisionEsperada) {
        List<ConfiguracionAforo> filas = jdbc.query(sqlBloquearConfiguracion, (rs, fila) -> new ConfiguracionAforo(
                rs.getObject("estacionamiento_id", UUID.class), rs.getLong("revision")));
        if (filas.size() != 1 || filas.getFirst().estacionamientoId() == null
                || filas.getFirst().revision() != revisionEsperada) {
            throw new DataAccessResourceFailureException("La configuración cambió durante la entrada.");
        }
        return filas.getFirst().estacionamientoId();
    }

    private void bloquearPersona(Asociacion asociacion) {
        if (asociacion.clienteId() != null) {
            List<UUID> personas = jdbc.query(sqlBloquearCliente,
                    (rs, fila) -> rs.getObject("id", UUID.class), asociacion.clienteId());
            if (personas.size() != 1) {
                throw new DataAccessResourceFailureException("La persona asociada no está disponible.");
            }
        } else {
            List<Long> personas = jdbc.query(sqlBloquearEmpleado,
                    (rs, fila) -> rs.getLong("id"), asociacion.empleadoId());
            if (personas.size() != 1) {
                throw new DataAccessResourceFailureException("La persona asociada no está disponible.");
            }
        }
    }

    private boolean tieneEntradaAbierta(Asociacion asociacion) {
        Boolean abierta = jdbc.queryForObject(sqlConsultarEntradaAbierta, Boolean.class,
                asociacion.clienteId(), asociacion.clienteId(),
                asociacion.empleadoId(), asociacion.empleadoId());
        return Boolean.TRUE.equals(abierta);
    }

    private boolean capacidadCompleta(UUID estacionamientoId) {
        Boolean completa = jdbc.queryForObject(sqlConsultarCapacidadCompleta, Boolean.class, estacionamientoId);
        if (completa == null) {
            throw new DataAccessResourceFailureException("No se pudo verificar la capacidad.");
        }
        return completa;
    }

    private static ResultadoEntradaRfid2 resultadoReplay(
            String uid, String uidAnterior, Clock reloj, ZoneId zonaHoraria, Predicate<LocalTime> dentroDeHorario) {
        if (!uid.equals(uidAnterior)) {
            throw new LecturaRfid2ConflictException();
        }
        // Si se repite una lectura fuera de horario, se conservan el registro y la visita ya confirmados.
        return dentroDeHorario.test(reloj.instant().atZone(zonaHoraria).toLocalTime())
                ? ResultadoEntradaRfid2.autorizada()
                : ResultadoEntradaRfid2.denegada("FUERA_DE_HORARIO");
    }

    private static int claveBloqueo(UUID uuid) {
        long superior = uuid.getMostSignificantBits();
        long inferior = uuid.getLeastSignificantBits();
        return (int) (superior >>> 32) ^ (int) superior ^ (int) (inferior >>> 32) ^ (int) inferior;
    }

    private static Asociacion mapearAsociacion(ResultSet rs, int fila) throws SQLException {
        UUID clienteId = rs.getObject("cliente_id", UUID.class);
        Long empleadoId = (Long) rs.getObject("empleado_id");
        return new Asociacion(rs.getLong("asociacion_id"), rs.getString("uid_canonico"),
                rs.getString("estado"), clienteId == null ? "EMPLEADO" : "CLIENTE", clienteId, empleadoId);
    }

    private record Asociacion(long asociacionId, String uid, String estado, String tipoPersona,
                              UUID clienteId, Long empleadoId) { }

    private record ConfiguracionAforo(UUID estacionamientoId, long revision) { }
}
