package mx.smartparking.api.rfid3.persistencia;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.TransactionSystemException;

class RepositorioRfid3JdbcTest {

    private static final String UID = "12345678";
    private static final UUID LECTURA = UUID.fromString("550e8400-e29b-41d4-a716-446655440000");

    @Test
    void replayConfirmadoNoConsultaEstadoNiZona() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        PlatformTransactionManager manager = administrador();
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of(UID));
        var repositorio = new RepositorioRfid3Jdbc(jdbc, manager, Clock.systemUTC());

        assertEquals("AUTORIZADA", repositorio.registrarSalida(UID, LECTURA).resultado());
        verify(manager).commit(any(TransactionStatus.class));
        verify(jdbc).query(anyString(), any(RowMapper.class), any(Object[].class));
    }

    @Test
    void replayConOtraTarjetaRevierteYProduceConflicto() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        PlatformTransactionManager manager = administrador();
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of(UID));
        var repositorio = new RepositorioRfid3Jdbc(jdbc, manager, Clock.systemUTC());

        assertThrows(LecturaRfid3ConflictException.class, () -> repositorio.registrarSalida("87654321", LECTURA));
        verify(manager).rollback(any(TransactionStatus.class));
    }

    @Test
    void fechaYHoraSeDerivanDelMismoInstanteTruncadoEnLaZonaConfigurada() throws SQLException {
        JdbcTemplate jdbc = jdbcConMovimiento();
        PlatformTransactionManager manager = administrador();
        Clock reloj = Clock.fixed(Instant.parse("2026-01-01T06:00:00.000000999Z"), ZoneOffset.UTC);
        var repositorio = new RepositorioRfid3Jdbc(jdbc, manager, reloj);

        assertEquals("AUTORIZADA", repositorio.registrarSalida(UID, LECTURA).resultado());
        ArgumentCaptor<Object[]> parametros = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).update(anyString(), parametros.capture());
        assertEquals(LocalDate.of(2026, 1, 1), parametros.getValue()[0]);
        assertEquals(LocalTime.MIDNIGHT, parametros.getValue()[1]);
        assertEquals(OffsetDateTime.parse("2026-01-01T06:00:00Z"), parametros.getValue()[2]);
        assertEquals(LECTURA, parametros.getValue()[3]);
    }

    @Test
    void medianocheYTransicionDeOffsetUsanLaZonaDelInstante() throws SQLException {
        comprobarHoraSalida("2026-01-01T05:59:59.999999Z", "America/Mexico_City",
                LocalDate.of(2025, 12, 31), LocalTime.of(23, 59, 59, 999999000));
        comprobarHoraSalida("2026-01-01T06:00:00Z", "America/Mexico_City",
                LocalDate.of(2026, 1, 1), LocalTime.MIDNIGHT);
        comprobarHoraSalida("2026-11-01T05:59:59Z", "America/New_York",
                LocalDate.of(2026, 11, 1), LocalTime.of(1, 59, 59));
        comprobarHoraSalida("2026-11-01T06:00:00Z", "America/New_York",
                LocalDate.of(2026, 11, 1), LocalTime.of(1, 0));
    }

    @Test
    void unFalloDeCommitNoEntregaAutorizacion() throws SQLException {
        JdbcTemplate jdbc = jdbcConMovimiento();
        PlatformTransactionManager manager = administrador();
        doThrow(new TransactionSystemException("Fallo simulado de commit"))
                .when(manager).commit(any(TransactionStatus.class));
        var repositorio = new RepositorioRfid3Jdbc(jdbc, manager, Clock.systemUTC());

        assertThrows(TransactionSystemException.class, () -> repositorio.registrarSalida(UID, LECTURA));
        verify(jdbc).update(anyString(), any(Object[].class));
    }

    @Test
    void zonaInvalidaFallaComoErrorOperacionalSinExponerLaTarjeta() throws SQLException {
        JdbcTemplate jdbc = jdbcConMovimiento();
        when(jdbc.query(contains("zona_horaria"), any(RowMapper.class))).thenReturn(List.of("Zona/Desconocida"));
        PlatformTransactionManager manager = administrador();
        var repositorio = new RepositorioRfid3Jdbc(jdbc, manager, Clock.systemUTC());

        DataAccessResourceFailureException error = assertThrows(DataAccessResourceFailureException.class,
                () -> repositorio.registrarSalida(UID, LECTURA));
        assertFalse(error.getMessage().contains(UID));
        verify(manager).rollback(any(TransactionStatus.class));
    }

    @Test
    void movimientoNoActualizadoFallaComoErrorOperacionalSinExponerLaTarjeta() throws SQLException {
        JdbcTemplate jdbc = jdbcConMovimiento();
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(0);
        PlatformTransactionManager manager = administrador();
        var repositorio = new RepositorioRfid3Jdbc(jdbc, manager, Clock.systemUTC());

        DataAccessResourceFailureException error = assertThrows(DataAccessResourceFailureException.class,
                () -> repositorio.registrarSalida(UID, LECTURA));
        assertFalse(error.getMessage().contains(UID));
        verify(manager).rollback(any(TransactionStatus.class));
    }

    @Test
    void relojAnteriorALaEntradaFallaAntesDelUpdateSinExponerLaTarjeta() throws SQLException {
        JdbcTemplate jdbc = jdbcConMovimiento();
        when(jdbc.query(contains("SELECT movimiento_id"), any(RowMapper.class), any(Object[].class)))
                .thenAnswer(invocacion -> movimiento(invocacion.getArgument(1), "2026-01-01T06:00:01Z"));
        PlatformTransactionManager manager = administrador();
        Clock reloj = Clock.fixed(Instant.parse("2026-01-01T06:00:00Z"), ZoneOffset.UTC);
        var repositorio = new RepositorioRfid3Jdbc(jdbc, manager, reloj);

        DataAccessResourceFailureException error = assertThrows(DataAccessResourceFailureException.class,
                () -> repositorio.registrarSalida(UID, LECTURA));
        assertFalse(error.getMessage().contains(UID));
        verify(jdbc, never()).update(anyString(), any(Object[].class));
        verify(manager).rollback(any(TransactionStatus.class));
    }

    @Test
    void conflictoDeUnicidadEspecificoConsultaReplaySoloDespuesDelRollback() throws SQLException {
        JdbcTemplate jdbc = jdbcConMovimiento();
        PlatformTransactionManager manager = administrador();
        AtomicBoolean rollback = new AtomicBoolean();
        doAnswer(invocacion -> { rollback.set(true); return null; }).when(manager).rollback(any());
        AtomicInteger consultas = new AtomicInteger();
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenAnswer(invocacion -> {
            String sql = invocacion.getArgument(0);
            if (sql.contains("uid_historico")) {
                if (consultas.incrementAndGet() > 3) {
                    assertTrue(rollback.get());
                    return List.of(UID);
                }
                return List.of();
            }
            return responderConsulta(invocacion.getArgument(1), sql);
        });
        doThrow(new DuplicateKeyException("Fallo simulado", new SQLException(
                "violates unique constraint \"movimiento_estacionamiento_salida_lectura_uq\"", "23505")))
                .when(jdbc).update(anyString(), any(Object[].class));
        var repositorio = new RepositorioRfid3Jdbc(jdbc, manager, Clock.systemUTC());

        assertEquals("AUTORIZADA", repositorio.registrarSalida(UID, LECTURA).resultado());
        assertEquals(4, consultas.get());
        verify(manager).rollback(any(TransactionStatus.class));
        verify(manager).commit(any(TransactionStatus.class));
    }

    @Test
    void otraRestriccionNoSeConvierteEnReplay() throws SQLException {
        JdbcTemplate jdbc = jdbcConMovimiento();
        PlatformTransactionManager manager = administrador();
        doThrow(new DuplicateKeyException("Fallo simulado", new SQLException(
                "violates unique constraint \"otra_restriccion\"", "23505")))
                .when(jdbc).update(anyString(), any(Object[].class));
        var repositorio = new RepositorioRfid3Jdbc(jdbc, manager, Clock.systemUTC());

        assertThrows(DuplicateKeyException.class, () -> repositorio.registrarSalida(UID, LECTURA));
        verify(manager).rollback(any(TransactionStatus.class));
    }

    private static PlatformTransactionManager administrador() {
        PlatformTransactionManager manager = mock(PlatformTransactionManager.class);
        when(manager.getTransaction(any())).thenReturn(mock(TransactionStatus.class));
        return manager;
    }

    private static JdbcTemplate jdbcConMovimiento() throws SQLException {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.query(contains("zona_horaria"), any(RowMapper.class))).thenReturn(List.of("America/Mexico_City"));
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenAnswer(invocacion -> {
            String sql = invocacion.getArgument(0);
            if (sql.contains("uid_historico")) {
                return List.of();
            }
            return responderConsulta(invocacion.getArgument(1), sql);
        });
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1);
        return jdbc;
    }

    private static void comprobarHoraSalida(String valor, String zona, LocalDate fecha, LocalTime hora)
            throws SQLException {
        JdbcTemplate jdbc = jdbcConMovimiento();
        when(jdbc.query(contains("zona_horaria"), any(RowMapper.class))).thenReturn(List.of(zona));
        Clock reloj = Clock.fixed(Instant.parse(valor), ZoneOffset.UTC);
        var repositorio = new RepositorioRfid3Jdbc(jdbc, administrador(), reloj);

        assertEquals("AUTORIZADA", repositorio.registrarSalida(UID, LECTURA).resultado());
        ArgumentCaptor<Object[]> parametros = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).update(anyString(), parametros.capture());
        assertEquals(fecha, parametros.getValue()[0]);
        assertEquals(hora, parametros.getValue()[1]);
        assertEquals(Instant.parse(valor), ((OffsetDateTime) parametros.getValue()[2]).toInstant());
    }

    private static List<?> responderConsulta(RowMapper<?> mapa, String sql) throws SQLException {
        if (sql.contains("solicitud_salida_manual")) {
            return List.of();
        }
        if (sql.contains("asociacion_tarjeta_rfid1")) {
            ResultSet fila = mock(ResultSet.class);
            when(fila.getLong(1)).thenReturn(1L);
            when(fila.getString(2)).thenReturn("ACTIVA");
            return List.of(mapa.mapRow(fila, 0));
        }
        if (sql.contains("movimiento_id")) {
            return movimiento(mapa, "2025-12-01T00:00:00Z");
        }
        if (sql.contains("zona_horaria")) {
            return List.of("America/Mexico_City");
        }
        throw new AssertionError("Consulta inesperada");
    }

    private static List<?> movimiento(RowMapper<?> mapa, String entrada) throws SQLException {
        ResultSet fila = mock(ResultSet.class);
        when(fila.getLong(1)).thenReturn(1L);
        when(fila.getObject(2, OffsetDateTime.class)).thenReturn(OffsetDateTime.parse(entrada));
        return List.of(mapa.mapRow(fila, 0));
    }
}
