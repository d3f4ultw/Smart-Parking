package mx.smartparking.api.rfid2.persistencia;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.sql.ResultSet;
import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import mx.smartparking.api.rfid2.PlazoEntradaRfid2;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionStatus;

class RepositorioRfid2JdbcTest {

    private static final UUID LECTURA = UUID.fromString("550e8400-e29b-41d4-a716-446655440000");

    @Test
    void relojSeConsultaDespuesDeBloqueoYComprobacionDeEntrada() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        PlatformTransactionManager manager = administrador();
        AtomicBoolean bloqueada = new AtomicBoolean();
        AtomicBoolean comprobada = new AtomicBoolean();
        prepararAsociacion(jdbc, bloqueada);
        when(jdbc.queryForObject(contains("SELECT EXISTS"), eq(Boolean.class), any(Object[].class))).thenAnswer(invocacion -> {
            comprobada.set(true);
            return false;
        });
        when(jdbc.queryForObject(contains("SELECT MAX"), eq(OffsetDateTime.class), any()))
                .thenReturn(OffsetDateTime.parse("2026-01-01T06:00:00Z"));
        when(jdbc.queryForObject(contains("SELECT (SELECT count"), eq(Boolean.class), any())).thenReturn(false);
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1);
        Clock reloj = relojComprobado(bloqueada, comprobada, Instant.parse("2026-01-01T06:00:01Z"));
        var repositorio = new RepositorioRfid2Jdbc(jdbc, manager);

        assertEquals("AUTORIZADA", repositorio.registrarEntrada("12345678", LECTURA, reloj,
                ZoneId.of("America/Mexico_City"), hora -> true, 1L, new PlazoEntradaRfid2()).resultado());
        verify(manager).commit(any(TransactionStatus.class));
    }

    @Test
    void relojAnteriorALaUltimaSalidaFallaCerradoSinInsertar() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        PlatformTransactionManager manager = administrador();
        AtomicBoolean bloqueada = new AtomicBoolean();
        AtomicBoolean comprobada = new AtomicBoolean();
        prepararAsociacion(jdbc, bloqueada);
        when(jdbc.queryForObject(contains("SELECT EXISTS"), eq(Boolean.class), any(Object[].class))).thenAnswer(invocacion -> {
            comprobada.set(true);
            return false;
        });
        when(jdbc.queryForObject(contains("SELECT MAX"), eq(OffsetDateTime.class), any()))
                .thenReturn(OffsetDateTime.parse("2026-01-01T06:00:01Z"));
        Clock reloj = relojComprobado(bloqueada, comprobada, Instant.parse("2026-01-01T06:00:00Z"));
        var repositorio = new RepositorioRfid2Jdbc(jdbc, manager);

        DataAccessResourceFailureException error = assertThrows(DataAccessResourceFailureException.class,
                () -> repositorio.registrarEntrada(
                "12345678", LECTURA, reloj, ZoneOffset.UTC, hora -> true, 1L, new PlazoEntradaRfid2()));
        assertFalse(error.getMessage().contains("12345678"));
        verify(jdbc, never()).update(anyString(), any(Object[].class));
        verify(manager).rollback(any(TransactionStatus.class));
    }

    @Test
    void configuracionObsoletaFallaAntesDeBloquearLaTarjeta() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        PlatformTransactionManager manager = administrador();
        AtomicBoolean bloqueada = new AtomicBoolean();
        prepararAsociacion(jdbc, bloqueada);
        var repositorio = new RepositorioRfid2Jdbc(jdbc, manager);

        assertThrows(DataAccessResourceFailureException.class,
                () -> repositorio.registrarEntrada("12345678", LECTURA, Clock.systemUTC(),
                        ZoneOffset.UTC, hora -> true, 2L, new PlazoEntradaRfid2()));
        assertFalse(bloqueada.get());
        verify(jdbc, never()).update(anyString(), any(Object[].class));
        verify(manager).rollback(any(TransactionStatus.class));
    }

    @Test
    void capacidadCompletaDeniegaSinInsertarMovimiento() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        PlatformTransactionManager manager = administrador();
        AtomicBoolean bloqueada = new AtomicBoolean();
        prepararAsociacion(jdbc, bloqueada);
        when(jdbc.queryForObject(contains("SELECT EXISTS"), eq(Boolean.class), any(Object[].class)))
                .thenReturn(false);
        when(jdbc.queryForObject(contains("SELECT (SELECT count"), eq(Boolean.class), any())).thenReturn(true);
        var repositorio = new RepositorioRfid2Jdbc(jdbc, manager);

        ResultadoEntradaRfid2 resultado = repositorio.registrarEntrada("12345678", LECTURA,
                Clock.systemUTC(), ZoneOffset.UTC, hora -> true, 1L, new PlazoEntradaRfid2());
        assertEquals("DENEGADA", resultado.resultado());
        assertEquals("CAPACIDAD_COMPLETA", resultado.motivo());
        verify(jdbc, never()).query(contains("INSERT INTO movimiento_estacionamiento"),
                any(RowMapper.class), any(Object[].class));
        verify(manager).commit(any(TransactionStatus.class));
    }

    @Test
    void esperaDeConexionAgotaElPlazoAntesDeEjecutarSql() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        PlatformTransactionManager manager = mock(PlatformTransactionManager.class);
        AtomicLong nanos = new AtomicLong();
        PlazoEntradaRfid2 plazo = new PlazoEntradaRfid2(nanos::get);
        when(manager.getTransaction(any())).thenAnswer(invocacion -> {
            nanos.addAndGet(TimeUnit.SECONDS.toNanos(3));
            return mock(TransactionStatus.class);
        });
        var repositorio = new RepositorioRfid2Jdbc(jdbc, manager);
        assertThrows(DataAccessResourceFailureException.class, () -> repositorio.registrarEntrada(
                "12345678", LECTURA, Clock.systemUTC(), ZoneOffset.UTC, hora -> true, 1L, plazo));
        verifyNoSql(jdbc);
        verify(manager).rollback(any(TransactionStatus.class));
    }

    @Test
    void plazoAgotadoAntesDeMutarRevierteLaTransaccion() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        PlatformTransactionManager manager = administrador();
        AtomicLong nanos = new AtomicLong();
        PlazoEntradaRfid2 plazo = new PlazoEntradaRfid2(nanos::get);
        prepararAsociacion(jdbc, new AtomicBoolean());
        when(jdbc.queryForObject(contains("SELECT EXISTS"), eq(Boolean.class), any(Object[].class)))
                .thenReturn(false);
        when(jdbc.queryForObject(contains("SELECT (SELECT count"), eq(Boolean.class), any())).thenAnswer(invocacion -> {
            nanos.addAndGet(TimeUnit.SECONDS.toNanos(3));
            return false;
        });
        var repositorio = new RepositorioRfid2Jdbc(jdbc, manager);
        assertThrows(DataAccessResourceFailureException.class, () -> repositorio.registrarEntrada(
                "12345678", LECTURA, Clock.systemUTC(), ZoneOffset.UTC, hora -> true, 1L, plazo));
        verify(jdbc, never()).query(contains("INSERT INTO movimiento_estacionamiento"),
                any(RowMapper.class), any(Object[].class));
        verify(jdbc, never()).update(anyString(), any(Object[].class));
        verify(manager).rollback(any(TransactionStatus.class));
    }

    private static void verifyNoSql(JdbcTemplate jdbc) {
        verify(jdbc, never()).execute(anyString());
        verify(jdbc, never()).update(anyString(), any(Object[].class));
    }

    private static PlatformTransactionManager administrador() {
        PlatformTransactionManager manager = mock(PlatformTransactionManager.class);
        when(manager.getTransaction(any())).thenReturn(mock(TransactionStatus.class));
        return manager;
    }

    private static void prepararAsociacion(JdbcTemplate jdbc, AtomicBoolean bloqueada) {
        when(jdbc.query(contains("FROM configuracion_estacionamiento"), any(RowMapper.class)))
                .thenAnswer(invocacion -> {
                    ResultSet fila = mock(ResultSet.class);
                    when(fila.getObject("estacionamiento_id", UUID.class)).thenReturn(UUID.randomUUID());
                    when(fila.getLong("revision")).thenReturn(1L);
                    RowMapper<?> mapa = invocacion.getArgument(1);
                    return List.of(mapa.mapRow(fila, 0));
                });
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenAnswer(invocacion -> {
            String sql = invocacion.getArgument(0);
            if (sql.contains("FROM asociacion_tarjeta_rfid1")) {
                if (sql.contains("FOR UPDATE")) {
                    bloqueada.set(true);
                }
                ResultSet fila = mock(ResultSet.class);
                when(fila.getLong("asociacion_id")).thenReturn(1L);
                when(fila.getString("uid_canonico")).thenReturn("12345678");
                when(fila.getString("estado")).thenReturn("ACTIVA");
                when(fila.getObject("empleado_id")).thenReturn(1L);
                RowMapper<?> mapa = invocacion.getArgument(1);
                return List.of(mapa.mapRow(fila, 0));
            }
            if (sql.contains("SELECT id FROM empleado WHERE id = ? FOR UPDATE")) {
                return List.of(1L);
            }
            if (sql.contains("RETURNING movimiento_id")) {
                return List.of(1L);
            }
            return List.of();
        });
    }

    private static Clock relojComprobado(AtomicBoolean bloqueada, AtomicBoolean comprobada, Instant instante) {
        return new Clock() {
            @Override
            public ZoneId getZone() {
                return ZoneOffset.UTC;
            }

            @Override
            public Clock withZone(ZoneId zona) {
                return this;
            }

            @Override
            public Instant instant() {
                assertTrue(bloqueada.get());
                assertTrue(comprobada.get());
                return instante;
            }
        };
    }
}
