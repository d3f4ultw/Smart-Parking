package mx.smartparking.api.clientes.administracion.persistencia;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.sql.Connection;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import org.junit.jupiter.api.Assertions;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.PlatformTransactionManager;

@EnabledIfSystemProperty(named = "smartparking.integration.disposable", matches = "true")
class RepositorioClientesAdministracionPostgresTest {

    private static final String PRICE_ID = "price_1USQ5HAqtHmR2qmyAWwUp5vy";
    private static final Instant AHORA = Instant.parse("2026-10-27T14:00:00Z");

    @Test
    void paginaFiltraAntesDeLimitarYDevuelveLaProyeccionPersistida() throws Exception {
        JdbcTemplate jdbc = new JdbcTemplate(fuenteDescartable());
        confirmarFlywayDiez(jdbc);
        RepositorioClientesAdministracion repositorio = repositorio(jdbc);
        List<UUID> clientes = new ArrayList<>();
        List<String> codigosActivos = new ArrayList<>();
        UUID clienteSinMembresia = UUID.randomUUID();
        UUID clienteCancelado = UUID.randomUUID();
        try {
            for (int indice = 0; indice < 11; indice++) {
                UUID clienteId = UUID.randomUUID();
                clientes.add(clienteId);
                insertarCliente(jdbc, clienteId);
                codigosActivos.add(codigoDe(jdbc, clienteId));
                insertarMembresia(jdbc, clienteId, "active", "ACTIVA", false);
            }
            jdbc.update("UPDATE cuenta SET nombres = ?, primer_apellido = ? WHERE id = ?",
                    "Ana María", "Busqueda", clientes.getFirst());
            insertarCliente(jdbc, clienteSinMembresia);
            insertarCliente(jdbc, clienteCancelado);
            clientes.add(clienteSinMembresia);
            clientes.add(clienteCancelado);
            insertarMembresia(jdbc, clienteCancelado, "canceled", "CANCELADA", true);

            ResultadoPaginaClientes primera = repositorio.consultarPagina(1, 10, "activa", null);
            ResultadoPaginaClientes segunda = repositorio.consultarPagina(2, 10, "activa", null);

            assertEquals(10, primera.items().size());
            assertFalse(segunda.items().isEmpty());
            assertTrue(primera.totalRegistros() >= 11);
            assertEquals(primera.totalClientes(), segunda.totalClientes());
            ResultadoPaginaClientes fueraDeRango = repositorio.consultarPagina(
                    Integer.MAX_VALUE, 10, "activa", null);
            assertEquals(Math.max(primera.totalPaginas(), 1), fueraDeRango.pagina());
            assertTrue(primera.items().stream().allMatch(fila -> "ACTIVA".equals(fila.estadoMembresia())));
            assertTrue(segunda.items().stream().allMatch(fila -> "ACTIVA".equals(fila.estadoMembresia())));
            String ultimoCodigoPrimera = primera.items().get(primera.items().size() - 1).codigo();
            String primerCodigoSegunda = segunda.items().get(0).codigo();
            assertTrue(Long.parseLong(ultimoCodigoPrimera.substring(4))
                    < Long.parseLong(primerCodigoSegunda.substring(4)));

            String codigoActivo = codigosActivos.get(0);
            DetalleClientePersistido detalleActivo = repositorio.consultarDetalle(codigoActivo).orElseThrow();
            assertEquals(codigoActivo, detalleActivo.codigo());
            assertEquals("ACTIVA", detalleActivo.estadoMembresia());
            assertEquals(AHORA, detalleActivo.periodoInicio());
            assertEquals(AHORA.plusSeconds(2_592_000), detalleActivo.siguienteCobroEn());
            assertFalse(detalleActivo.cancelacionAlFinal());

            DetalleClientePersistido detalleSinMembresia = repositorio.consultarDetalle(
                    codigoDe(jdbc, clienteSinMembresia)).orElseThrow();
            assertEquals("SIN_MEMBRESIA", detalleSinMembresia.estadoMembresia());
            assertNull(detalleSinMembresia.periodoInicio());
            assertNull(detalleSinMembresia.periodoFin());
            assertNull(detalleSinMembresia.siguienteCobroEn());
            assertFalse(detalleSinMembresia.cancelacionAlFinal());

            ResultadoPaginaClientes canceladas = repositorio.consultarPagina(1, 10, "cancelada", null);
            assertTrue(canceladas.totalRegistros() >= 1);
            assertTrue(canceladas.items().stream().allMatch(fila -> "CANCELADA".equals(fila.estadoMembresia())));
            String codigoBusqueda = codigosActivos.getFirst();
            ResultadoPaginaClientes porNombre = repositorio.consultarPagina(
                    1, 10, "activa", "aNa mArÍa bUsQuEdA");
            assertEquals(1, porNombre.totalRegistros());
            assertEquals(codigoBusqueda, porNombre.items().getFirst().codigo());
            ResultadoPaginaClientes porCodigo = repositorio.consultarPagina(
                    1, 10, "activa", codigoBusqueda.toLowerCase(java.util.Locale.ROOT));
            assertEquals(1, porCodigo.totalRegistros());
            assertEquals(codigoBusqueda, porCodigo.items().getFirst().codigo());
            assertEquals(0, repositorio.consultarPagina(1, 10, "cancelada", codigoBusqueda)
                    .totalRegistros());
            ResultadoPaginaClientes sinMembresia = repositorio.consultarPagina(
                    1, 10, "sin-membresia", null);
            assertTrue(sinMembresia.items().stream().noneMatch(fila -> "ACTIVA".equals(fila.estadoMembresia())
                    || "CANCELADA".equals(fila.estadoMembresia())));
            assertTrue(repositorio.consultarDetalle("CLI-00001").isEmpty());
        } finally {
            clientes.forEach(clienteId -> limpiar(jdbc, clienteId));
        }
    }

    @Test
    void triggerAsignaCodigosUnicosEnAltasConcurrentesYNoReciclaNumeros() throws Exception {
        JdbcTemplate jdbc = new JdbcTemplate(fuenteDescartable());
        confirmarFlywayDiez(jdbc);
        int cantidad = 16;
        List<UUID> clientes = java.util.stream.IntStream.range(0, cantidad)
                .mapToObj(indice -> UUID.randomUUID()).toList();
        ExecutorService ejecutores = Executors.newFixedThreadPool(8);
        CountDownLatch listos = new CountDownLatch(8);
        CountDownLatch iniciar = new CountDownLatch(1);
        List<Future<?>> tareas = new ArrayList<>();
        try {
            for (UUID clienteId : clientes) {
                tareas.add(ejecutores.submit(() -> {
                    listos.countDown();
                    iniciar.await();
                    insertarCliente(jdbc, clienteId);
                    return null;
                }));
            }
            assertTrue(listos.await(10, java.util.concurrent.TimeUnit.SECONDS));
            iniciar.countDown();
            for (Future<?> tarea : tareas) {
                tarea.get(30, java.util.concurrent.TimeUnit.SECONDS);
            }

            String placeholders = placeholders(cantidad);
            List<Long> numeros = jdbc.queryForList("SELECT numero FROM cliente_codigo_publico "
                    + "WHERE cliente_id IN (" + placeholders + ") ORDER BY numero",
                    Long.class, clientes.toArray());
            assertEquals(cantidad, numeros.size());
            assertEquals(cantidad, new HashSet<>(numeros).size());
            assertEquals(0, jdbc.queryForObject("SELECT count(*) "
                    + "FROM cuenta c LEFT JOIN cliente_codigo_publico p ON p.cliente_id = c.id "
                    + "WHERE c.id IN (" + placeholders + ") AND p.cliente_id IS NULL",
                    Integer.class, clientes.toArray()));

            UUID eliminado = clientes.get(0);
            long numeroAnterior = numeroDe(jdbc, eliminado);
            limpiar(jdbc, eliminado);
            UUID posterior = UUID.randomUUID();
            insertarCliente(jdbc, posterior);
            clientes = new ArrayList<>(clientes);
            clientes.add(posterior);
            assertTrue(numeroDe(jdbc, posterior) > numeroAnterior);
        } finally {
            iniciar.countDown();
            ejecutores.shutdownNow();
            clientes.forEach(clienteId -> limpiar(jdbc, clienteId));
        }
    }

    private static RepositorioClientesAdministracion repositorio(JdbcTemplate jdbc) {
        PlatformTransactionManager transacciones = new DataSourceTransactionManager(jdbc.getDataSource());
        return new RepositorioClientesAdministracionJdbc(jdbc, transacciones);
    }

    private static DriverManagerDataSource fuenteDescartable() throws Exception {
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
        try (Connection conexion = fuente.getConnection()) {
            assertEquals(18, conexion.getMetaData().getDatabaseMajorVersion());
            assertTrue(conexion.getMetaData().getDatabaseProductVersion().contains("18.6"));
        }
        return fuente;
    }

    private static void confirmarFlywayDiez(JdbcTemplate jdbc) {
        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM flyway_schema_history WHERE version = '10' AND success
                """, Integer.class));
    }

    private static void insertarCliente(JdbcTemplate jdbc, UUID id) {
        String correo = id + "@example.test";
        jdbc.update("""
                INSERT INTO cuenta (
                    id, nombres, primer_apellido, segundo_apellido, correo, correo_normalizado,
                    rol, estado, hash_contrasena_acceso, revision_acceso, creada_en, actualizada_en)
                VALUES (?, 'Cliente sintético', 'Prueba', NULL, ?, ?, 'CLIENTE', 'ACTIVA',
                        'hash-sintetico', 1, ?, ?)
                """, id, correo, correo, Timestamp.from(AHORA), Timestamp.from(AHORA));
    }

    private static void insertarMembresia(
            JdbcTemplate jdbc, UUID clienteId, String estadoStripe, String estado, boolean cancelarAlFinal) {
        String customerId = "cus_" + UUID.randomUUID().toString().replace("-", "");
        String subscriptionId = "sub_" + UUID.randomUUID().toString().replace("-", "");
        jdbc.update("""
                INSERT INTO cliente_stripe (
                    cliente_id, estado, stripe_customer_id, livemode, creada_en, actualizada_en)
                VALUES (?, 'ASOCIADO', ?, FALSE, ?, ?)
                """, clienteId, customerId, Timestamp.from(AHORA), Timestamp.from(AHORA));
        jdbc.update("""
                INSERT INTO suscripcion_cliente (
                    stripe_subscription_id, cliente_id, stripe_customer_id, price_id,
                    estado_stripe, estado, invoice_id, estado_factura_stripe,
                    periodo_inicio, periodo_fin, cancel_at_period_end, evento_creado_en,
                    actualizada_en, livemode)
                VALUES (?, ?, ?, ?, ?, ?, NULL, 'paid', ?, ?, ?, ?, ?, FALSE)
                """, subscriptionId, clienteId, customerId, PRICE_ID, estadoStripe, estado,
                Timestamp.from(AHORA), Timestamp.from(AHORA.plusSeconds(2_592_000)),
                cancelarAlFinal, Timestamp.from(AHORA), Timestamp.from(AHORA));
    }

    private static String codigoDe(JdbcTemplate jdbc, UUID clienteId) {
        long numero = numeroDe(jdbc, clienteId);
        return String.format(java.util.Locale.ROOT, "CLI-%04d", numero);
    }

    private static long numeroDe(JdbcTemplate jdbc, UUID clienteId) {
        return jdbc.queryForObject("""
                SELECT numero FROM cliente_codigo_publico WHERE cliente_id = ?
                """, Long.class, clienteId);
    }

    private static String placeholders(int cantidad) {
        return String.join(",", java.util.Collections.nCopies(cantidad, "?"));
    }

    private static void limpiar(JdbcTemplate jdbc, UUID clienteId) {
        jdbc.update("DELETE FROM suscripcion_cliente WHERE cliente_id = ?", clienteId);
        jdbc.update("DELETE FROM intento_checkout WHERE cliente_id = ?", clienteId);
        jdbc.update("DELETE FROM cliente_stripe WHERE cliente_id = ?", clienteId);
        jdbc.update("DELETE FROM cliente_codigo_publico WHERE cliente_id = ?", clienteId);
        jdbc.update("DELETE FROM cuenta WHERE id = ?", clienteId);
    }

    private static String variable(String nombre) {
        String valor = System.getenv(nombre);
        Assertions.assertNotNull(valor, "Falta " + nombre + " para PostgreSQL descartable.");
        assertFalse(valor.isBlank(), "Falta " + nombre + " para PostgreSQL descartable.");
        return valor;
    }
}
