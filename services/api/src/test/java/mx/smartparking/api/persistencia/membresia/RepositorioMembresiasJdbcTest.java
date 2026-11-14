package mx.smartparking.api.persistencia.membresia;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.stubbing.Answer;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.SimpleTransactionStatus;

class RepositorioMembresiasJdbcTest {

    private static final String PRICE_ID = "price_1USQ5HAqtHmR2qmyAWwUp5vy";
    private static final Instant AHORA = Instant.parse("2026-10-27T14:00:00Z");

    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final PlatformTransactionManager transacciones = mock(PlatformTransactionManager.class);
    private RepositorioMembresiasJdbc repositorio;

    @BeforeEach
    void preparar() {
        when(transacciones.getTransaction(any(TransactionDefinition.class)))
                .thenReturn(new SimpleTransactionStatus());
        repositorio = new RepositorioMembresiasJdbc(jdbc, transacciones);
    }

    @Test
    void reservarCustomerReutilizaLaReservaDurableSinCambiarSuMarcaTemporal() throws SQLException {
        UUID clienteId = UUID.randomUUID();
        Instant primeraReserva = AHORA.minusSeconds(60);
        ClienteStripePersistido cliente = new ClienteStripePersistido(
                clienteId, null, "RESERVADO", primeraReserva);
        responderBloqueoCliente(clienteId);
        when(jdbc.update(contains("INSERT INTO cliente_stripe"), any(Object[].class))).thenReturn(0);
        when(jdbc.query(contains("FROM cliente_stripe WHERE cliente_id"), any(RowMapper.class),
                any(Object[].class))).thenReturn(List.of(cliente));

        ClienteStripePersistido respuesta = repositorio.reservarClienteStripe(clienteId, AHORA);

        assertEquals(cliente, respuesta);
        assertEquals(primeraReserva, respuesta.actualizadaEn());
        verify(jdbc).update(contains("ON CONFLICT (cliente_id) DO NOTHING"), any(Object[].class));
    }

    @Test
    void reservaCheckoutReproduceElMismoIntentoCuandoClaveYHuellaCoinciden() throws SQLException {
        UUID clienteId = UUID.randomUUID();
        UUID intentoId = UUID.randomUUID();
        String claveHash = "a".repeat(64);
        String huella = "b".repeat(64);
        IntentoCheckoutPersistido intento = new IntentoCheckoutPersistido(
                intentoId, clienteId, EstadoCheckoutPersistido.ABIERTO,
                "cs_test_replay123", PRICE_ID, AHORA.plusSeconds(3600), AHORA);
        responderBloqueoCliente(clienteId);
        when(jdbc.query(contains("WHERE cliente_id = ? AND clave_hash = ?"), any(RowMapper.class),
                any(Object[].class))).thenReturn(List.of(intento));
        when(jdbc.queryForObject(contains("SELECT huella_solicitud"), eq(String.class),
                any(Object[].class))).thenReturn(huella);

        ReservaCheckout reserva = repositorio.reservarCheckout(clienteId, claveHash, huella, PRICE_ID, AHORA);

        assertEquals(EstadoReservaCheckout.REPLAY, reserva.resultado());
        assertEquals(intento, reserva.intento());
        verify(jdbc, never()).update(contains("INSERT INTO intento_checkout"), any(Object[].class));
    }

    @Test
    void reservaCheckoutRechazaUnaHuellaDistintaParaLaMismaClave() throws SQLException {
        UUID clienteId = UUID.randomUUID();
        UUID intentoId = UUID.randomUUID();
        IntentoCheckoutPersistido intento = new IntentoCheckoutPersistido(
                intentoId, clienteId, EstadoCheckoutPersistido.RESERVADO,
                null, PRICE_ID, null, AHORA);
        responderBloqueoCliente(clienteId);
        when(jdbc.query(contains("WHERE cliente_id = ? AND clave_hash = ?"), any(RowMapper.class),
                any(Object[].class))).thenReturn(List.of(intento));
        when(jdbc.queryForObject(contains("SELECT huella_solicitud"), eq(String.class),
                any(Object[].class))).thenReturn("c".repeat(64));

        ReservaCheckout reserva = repositorio.reservarCheckout(
                clienteId, "a".repeat(64), "b".repeat(64), PRICE_ID, AHORA);

        assertEquals(EstadoReservaCheckout.IDEMPOTENCIA_REUTILIZADA, reserva.resultado());
        assertEquals(intento, reserva.intento());
        verify(jdbc, never()).update(contains("INSERT INTO intento_checkout"), any(Object[].class));
    }

    @Test
    void reservaCheckoutAplicaElLimiteDeCincoSolicitudesEnQuinceMinutos() throws SQLException {
        UUID clienteId = UUID.randomUUID();
        responderBloqueoCliente(clienteId);
        when(jdbc.query(contains("WHERE cliente_id = ? AND clave_hash = ?"), any(RowMapper.class),
                any(Object[].class))).thenReturn(List.of());
        when(jdbc.queryForObject(contains("FROM suscripcion_cliente"), eq(Integer.class),
                any(Object[].class))).thenReturn(0);
        when(jdbc.query(contains("ORDER BY creado_en DESC, intento_id DESC LIMIT 1"), any(RowMapper.class),
                any(Object[].class))).thenReturn(List.of());
        when(jdbc.queryForObject(contains("FROM intento_checkout WHERE cliente_id = ? AND creado_en >= ?"),
                eq(Integer.class), any(Object[].class))).thenReturn(5);

        ReservaCheckout reserva = repositorio.reservarCheckout(
                clienteId, "a".repeat(64), "b".repeat(64), PRICE_ID, AHORA);

        assertEquals(EstadoReservaCheckout.LIMITE_ALCANZADO, reserva.resultado());
        verify(jdbc, never()).update(contains("INSERT INTO intento_checkout"), any(Object[].class));
    }

    @Test
    void rechazaPrecioDistintoAntesDeAbrirTransaccion() {
        assertThrows(IllegalArgumentException.class, () -> repositorio.reservarCheckout(
                UUID.randomUUID(), "a".repeat(64), "b".repeat(64), "price_otro", AHORA));
        verify(transacciones, never()).getTransaction(any(TransactionDefinition.class));
    }

    private void responderBloqueoCliente(UUID clienteId) throws SQLException {
        when(jdbc.query(contains("SELECT id FROM cuenta"), any(RowMapper.class), any(Object[].class)))
                .thenAnswer(mapearCuenta(clienteId));
    }

    private static Answer<List<UUID>> mapearCuenta(UUID clienteId) {
        return invocacion -> {
            @SuppressWarnings("unchecked")
            RowMapper<UUID> mapa = invocacion.getArgument(1);
            ResultSet rs = mock(ResultSet.class);
            when(rs.getObject("id", UUID.class)).thenReturn(clienteId);
            return List.of(mapa.mapRow(rs, 0));
        };
    }
}
