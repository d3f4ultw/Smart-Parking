package mx.smartparking.api.persistencia.membresia;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.sql.Connection;
import java.time.Instant;
import java.util.UUID;
import mx.smartparking.api.clientes.membresia.modelo.ActualizacionStripe;
import org.junit.jupiter.api.Assertions;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

@EnabledIfSystemProperty(named = "smartparking.integration.disposable", matches = "true")
class RepositorioMembresiasPostgresTest {

    private static final String PRICE_ID = "price_1USQ5HAqtHmR2qmyAWwUp5vy";
    private static final Instant AHORA = Instant.parse("2026-10-27T14:00:00Z");

    @Test
    void reconciliaEventosYEstadosDeCheckoutEnPostgresDescartable() throws Exception {
        DriverManagerDataSource fuente = fuenteDescartable();
        try (Connection conexion = fuente.getConnection()) {
            assertEquals(18, conexion.getMetaData().getDatabaseMajorVersion());
            assertTrue(conexion.getMetaData().getDatabaseProductVersion().contains("18.6"));
        }
        JdbcTemplate jdbc = new JdbcTemplate(fuente);
        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM flyway_schema_history WHERE version = '9' AND success
                """, Integer.class));
        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM flyway_schema_history WHERE version = '10' AND success
                """, Integer.class));
        RepositorioMembresiasJdbc repositorio = new RepositorioMembresiasJdbc(
                jdbc, new DataSourceTransactionManager(fuente));
        UUID clienteId = UUID.randomUUID();
        UUID clienteExpiracionId = UUID.randomUUID();
        String eventoId = "evt_" + UUID.randomUUID().toString().replace("-", "");
        String customerId = "cus_" + UUID.randomUUID().toString().replace("-", "");
        String suscripcionId = "sub_" + UUID.randomUUID().toString().replace("-", "");
        UUID intentoExpiracionId = null;
        String eventoInvalido = null;
        try {
            insertarCliente(jdbc, clienteId);
            insertarCliente(jdbc, clienteExpiracionId);
            repositorio.reservarClienteStripe(clienteId, AHORA);
            repositorio.marcarClienteStripeIndeterminado(clienteId, AHORA.plusSeconds(60));
            ClienteStripePersistido clienteIndeterminado = repositorio.consultarClienteStripe(clienteId).orElseThrow();
            assertEquals("INDETERMINADO", clienteIndeterminado.estado());
            assertEquals(AHORA, clienteIndeterminado.actualizadaEn());
            repositorio.asociarCustomer(clienteId, customerId, AHORA.plusSeconds(61));
            ReservaCheckout reserva = repositorio.reservarCheckout(
                    clienteId, "a".repeat(64), "b".repeat(64), PRICE_ID, AHORA);
            assertEquals(EstadoReservaCheckout.NUEVA, reserva.resultado());
            UUID intentoId = reserva.intento().intentoId();
            String sessionId = "cs_test_" + UUID.randomUUID().toString().replace("-", "");
            assertEquals(ResultadoEventoStripe.NUEVO,
                    repositorio.registrarEventoStripe(eventoId, "checkout.session.completed", sessionId, AHORA));
            assertFalse(repositorio.aplicarActualizacionStripe(new ActualizacionStripe(
                    eventoId, "checkout.session.completed", AHORA, sessionId, intentoId, customerId,
                    suscripcionId, clienteId, PRICE_ID, "incomplete", null, null, null, null,
                    false, AHORA, true)).cambioVisible());

            IntentoCheckoutPersistido completado = repositorio.consultarCheckout(clienteId, intentoId).orElseThrow();
            assertEquals(EstadoCheckoutPersistido.COMPLETADO, completado.estado());
            assertEquals(sessionId, completado.sessionId());
            assertNull(completado.expiraEn());
            Instant expiraEn = AHORA.plusSeconds(3600);
            repositorio.asociarSesionCheckout(intentoId, sessionId, expiraEn, AHORA.plusSeconds(1));
            completado = repositorio.consultarCheckout(clienteId, intentoId).orElseThrow();
            assertEquals(EstadoCheckoutPersistido.COMPLETADO, completado.estado());
            assertEquals(expiraEn, completado.expiraEn());
            assertEquals(ResultadoEventoStripe.DUPLICADO,
                    repositorio.registrarEventoStripe(eventoId, "checkout.session.completed", sessionId, AHORA));
            assertEquals("PENDIENTE", repositorio.consultarResumenMembresia(clienteId).estado());
            assertFalse(repositorio.consultarResumenMembresia(clienteId).puedeComprar());

            String eventoActivo = "evt_" + UUID.randomUUID().toString().replace("-", "");
            assertEquals(ResultadoEventoStripe.NUEVO, repositorio.registrarEventoStripe(
                    eventoActivo, "customer.subscription.updated", suscripcionId, AHORA.plusSeconds(4)));
            ActualizacionStripe actualizacionActiva = new ActualizacionStripe(
                    eventoActivo, "customer.subscription.updated", AHORA.plusSeconds(4), null, null,
                    customerId, suscripcionId, clienteId, PRICE_ID, "active",
                    "in_" + UUID.randomUUID().toString().replace("-", ""), "paid",
                    AHORA, AHORA.plusSeconds(2_592_000), false, AHORA.plusSeconds(5), true);
            assertTrue(repositorio.aplicarActualizacionStripe(actualizacionActiva).cambioVisible());
            assertFalse(repositorio.aplicarActualizacionStripe(actualizacionActiva).cambioVisible());
            assertEquals("ACTIVA", repositorio.consultarResumenMembresia(clienteId).estado());

            eventoInvalido = "evt_" + UUID.randomUUID().toString().replace("-", "");
            String eventoFallidoId = eventoInvalido;
            assertEquals(ResultadoEventoStripe.NUEVO, repositorio.registrarEventoStripe(
                    eventoInvalido, "customer.subscription.updated", suscripcionId, AHORA.plusSeconds(2)));
            assertThrows(DataAccessException.class, () -> repositorio.aplicarActualizacionStripe(
                    new ActualizacionStripe(eventoFallidoId, "customer.subscription.updated", AHORA.plusSeconds(2),
                            null, intentoId, customerId, suscripcionId, clienteId, PRICE_ID, "no_valido", null,
                            null, null, null, false, AHORA.plusSeconds(2), true)));
            assertEquals("RECIBIDO", estadoEvento(jdbc, eventoFallidoId));
            assertEquals(ResultadoEventoStripe.REINTENTAR, repositorio.registrarEventoStripe(
                    eventoInvalido, "customer.subscription.updated", suscripcionId, AHORA.plusSeconds(3)));

            repositorio.reservarClienteStripe(clienteExpiracionId, AHORA);
            repositorio.asociarCustomer(clienteExpiracionId,
                    "cus_" + UUID.randomUUID().toString().replace("-", ""), AHORA);
            ReservaCheckout pendiente = repositorio.reservarCheckout(
                    clienteExpiracionId, "c".repeat(64), "d".repeat(64), PRICE_ID, AHORA);
            intentoExpiracionId = pendiente.intento().intentoId();
            String sesionExpirada = "cs_test_" + UUID.randomUUID().toString().replace("-", "");
            repositorio.asociarSesionCheckout(intentoExpiracionId, sesionExpirada, expiraEn, AHORA);
            repositorio.reconciliarCheckout(intentoExpiracionId, EstadoCheckoutPersistido.EXPIRADO,
                    sesionExpirada, expiraEn, false, AHORA.plusSeconds(2));
            assertEquals(EstadoCheckoutPersistido.RECONCILIANDO,
                    repositorio.consultarCheckout(clienteExpiracionId, intentoExpiracionId).orElseThrow().estado());
            repositorio.reconciliarCheckout(intentoExpiracionId, EstadoCheckoutPersistido.EXPIRADO,
                    sesionExpirada, expiraEn, true, AHORA.plusSeconds(3));
            assertEquals(EstadoCheckoutPersistido.EXPIRADO,
                    repositorio.consultarCheckout(clienteExpiracionId, intentoExpiracionId).orElseThrow().estado());
        } finally {
            limpiar(jdbc, clienteId, eventoId, eventoInvalido);
            limpiar(jdbc, clienteExpiracionId);
        }
    }

    private static DriverManagerDataSource fuenteDescartable() {
        String host = variable("TEST_POSTGRES_HOST");
        String port = variable("TEST_POSTGRES_PORT");
        String database = variable("TEST_POSTGRES_DB");
        String user = variable("TEST_POSTGRES_USER");
        String password = variable("TEST_POSTGRES_PASSWORD");
        assertEquals("db", host);
        assertEquals("5432", port);
        assertTrue(database.equals("smartparking_clientes_fase3")
                || database.matches("smartparking_test_[a-zA-Z0-9_-]+"));
        DriverManagerDataSource fuente = new DriverManagerDataSource();
        fuente.setUrl("jdbc:postgresql://" + host + ":" + port + "/" + database);
        fuente.setUsername(user);
        fuente.setPassword(password);
        return fuente;
    }

    private static String variable(String nombre) {
        String valor = System.getenv(nombre);
        Assertions.assertNotNull(valor, "Falta " + nombre + " para PostgreSQL descartable.");
        assertFalse(valor.isBlank(), "Falta " + nombre + " para PostgreSQL descartable.");
        return valor;
    }

    private static void insertarCliente(JdbcTemplate jdbc, UUID id) {
        Instant ahora = AHORA;
        String correo = id + "@example.test";
        jdbc.update("""
                INSERT INTO cuenta (
                    id, nombres, primer_apellido, correo, correo_normalizado, rol, estado,
                    hash_contrasena_acceso, revision_acceso, creada_en, actualizada_en)
                VALUES (?, 'Cliente sintético', 'Prueba', ?, ?, 'CLIENTE', 'ACTIVA', 'hash-sintetico', 1, ?, ?)
                """, id, correo, correo, java.sql.Timestamp.from(ahora), java.sql.Timestamp.from(ahora));
    }

    private static String estadoEvento(JdbcTemplate jdbc, String eventId) {
        return jdbc.queryForObject("SELECT estado FROM stripe_evento_procesado WHERE event_id = ?",
                String.class, eventId);
    }

    private static void limpiar(JdbcTemplate jdbc, UUID clienteId, String... eventIds) {
        for (String eventId : eventIds) {
            if (eventId == null) {
                continue;
            }
            jdbc.update("DELETE FROM stripe_evento_procesado WHERE event_id = ?", eventId);
        }
        jdbc.update("""
                DELETE FROM stripe_evento_procesado WHERE object_id IN (
                    SELECT stripe_subscription_id FROM suscripcion_cliente WHERE cliente_id = ?)
                """, clienteId);
        jdbc.update("DELETE FROM suscripcion_cliente WHERE cliente_id = ?", clienteId);
        jdbc.update("DELETE FROM intento_checkout WHERE cliente_id = ?", clienteId);
        jdbc.update("DELETE FROM cliente_stripe WHERE cliente_id = ?", clienteId);
        jdbc.update("DELETE FROM cliente_codigo_publico WHERE cliente_id = ?", clienteId);
        jdbc.update("DELETE FROM cuenta WHERE id = ?", clienteId);
    }
}
