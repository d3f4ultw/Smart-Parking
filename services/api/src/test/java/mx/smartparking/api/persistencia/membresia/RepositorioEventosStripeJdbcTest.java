package mx.smartparking.api.persistencia.membresia;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.sql.ResultSet;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.stubbing.Answer;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.SimpleTransactionStatus;

class RepositorioEventosStripeJdbcTest {

    private static final Instant AHORA = Instant.parse("2026-10-27T14:00:00Z");
    private static final String EVENT_ID = "evt_123abc";
    private static final String SESSION_ID = "cs_test_123abc";

    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final PlatformTransactionManager transacciones = mock(PlatformTransactionManager.class);
    private RepositorioEventosStripeJdbc repositorio;

    @BeforeEach
    void preparar() {
        when(transacciones.getTransaction(any(TransactionDefinition.class)))
                .thenReturn(new SimpleTransactionStatus());
        repositorio = new RepositorioEventosStripeJdbc(jdbc, transacciones);
    }

    @Test
    void registraUnEventoFirmadoComoNuevoSinGuardarPayload() {
        when(jdbc.update(contains("INSERT INTO stripe_evento_procesado"), any(Object[].class))).thenReturn(1);

        ResultadoEventoStripe resultado = repositorio.registrarEventoStripe(
                EVENT_ID, "checkout.session.completed", SESSION_ID, AHORA);

        assertEquals(ResultadoEventoStripe.NUEVO, resultado);
        verify(jdbc).update(contains("livemode"), any(Object[].class));
    }

    @Test
    void eventoYaAplicadoSeDevuelveComoDuplicado() {
        when(jdbc.update(contains("INSERT INTO stripe_evento_procesado"), any(Object[].class))).thenReturn(0);
        when(jdbc.query(contains("SELECT event_type, object_id, estado"), any(RowMapper.class),
                any(Object[].class))).thenAnswer(responderEvento("APLICADO"));

        ResultadoEventoStripe resultado = repositorio.registrarEventoStripe(
                EVENT_ID, "checkout.session.completed", SESSION_ID, AHORA);

        assertEquals(ResultadoEventoStripe.DUPLICADO, resultado);
    }

    @Test
    void eventoRecibidoPeroNoFinalizadoSePuedeReintentar() {
        when(jdbc.update(contains("INSERT INTO stripe_evento_procesado"), any(Object[].class))).thenReturn(0);
        when(jdbc.query(contains("SELECT event_type, object_id, estado"), any(RowMapper.class),
                any(Object[].class))).thenAnswer(responderEvento("RECIBIDO"));

        ResultadoEventoStripe resultado = repositorio.registrarEventoStripe(
                EVENT_ID, "checkout.session.completed", SESSION_ID, AHORA);

        assertEquals(ResultadoEventoStripe.REINTENTAR, resultado);
    }

    @Test
    void rechazaEventosFueraDeLaListaAntesDeEscribir() {
        assertThrows(IllegalArgumentException.class, () -> repositorio.registrarEventoStripe(
                EVENT_ID, "customer.created", "cus_123abc", AHORA));
    }

    private static Answer<List<Object>> responderEvento(String estado) {
        return invocacion -> {
            @SuppressWarnings("unchecked")
            RowMapper<Object> mapa = invocacion.getArgument(1);
            ResultSet rs = mock(ResultSet.class);
            when(rs.getString("event_type")).thenReturn("checkout.session.completed");
            when(rs.getString("object_id")).thenReturn(SESSION_ID);
            when(rs.getString("estado")).thenReturn(estado);
            return List.of(mapa.mapRow(rs, 0));
        };
    }
}
