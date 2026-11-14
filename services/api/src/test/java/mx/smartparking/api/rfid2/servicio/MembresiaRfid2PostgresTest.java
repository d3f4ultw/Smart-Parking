package mx.smartparking.api.rfid2.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import javax.sql.DataSource;
import mx.smartparking.api.clientes.membresia.modelo.ActualizacionStripe;
import mx.smartparking.api.historial.persistencia.RepositorioEventoAccesoJdbc;
import mx.smartparking.api.persistencia.membresia.RepositorioMembresias;
import mx.smartparking.api.persistencia.membresia.RepositorioMembresiasJdbc;
import mx.smartparking.api.rfid2.PlazoEntradaRfid2;
import mx.smartparking.api.rfid2.persistencia.LecturaRfid2ConflictException;
import mx.smartparking.api.rfid2.persistencia.RepositorioRfid2Jdbc;
import mx.smartparking.api.rfid2.persistencia.ResultadoEntradaRfid2;
import mx.smartparking.api.rfid3.persistencia.RepositorioRfid3Jdbc;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.aop.support.AopUtils;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Configuration;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.IllegalTransactionStateException;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;

/** Prueba membresías proyectadas por webhooks sin consultar ni pagar a Stripe. */
class MembresiaRfid2PostgresTest {
    private static final String PRICE_ID = "price_1USQ5HAqtHmR2qmyAWwUp5vy";
    private static final Instant AHORA = Instant.now().truncatedTo(ChronoUnit.MICROS);
    private static final AtomicLong SECUENCIA_EVENTOS = new AtomicLong();
    private static DataSource origen;
    private static JdbcTemplate jdbc;
    private static DataSourceTransactionManager administrador;
    private static RepositorioMembresiasJdbc membresias;

    @BeforeAll
    static void prepararBase() throws Exception {
        origen = HorarioRfid2PostgresTest.baseDescartable("rfid2_membresia_" + sufijo());
        jdbc = new JdbcTemplate(origen);
        administrador = new DataSourceTransactionManager(origen);
        membresias = new RepositorioMembresiasJdbc(jdbc, administrador);
        try (Connection conexion = origen.getConnection()) {
            assertTrue(conexion.getMetaData().getDatabaseProductVersion().contains("18.6"));
        }
        configurarSalida();
    }

    @Test
    void activaPagadaPermiteEntradaDesdeInicioInclusivo() {
        Cliente cliente = cliente();
        proyectar(cliente, "active", "paid", AHORA, AHORA.plusSeconds(3600), false);
        UUID lectura = UUID.randomUUID();
        assertEquals("AUTORIZADA", entrada(cliente, lectura, AHORA).resultado());
        assertEquals(1, abiertos(cliente));
        assertEquals("ACTIVA", membresias.consultarResumenMembresia(cliente.id()).estado());
        assertEquals("ACTIVA", tarjeta(cliente).get("estado"));
        assertNotNull(evento(lectura).get("movimiento_id"));
    }

    @Test
    void estadoActivoPersistidoNoEvitaVencimientoNiFinExclusivo() {
        for (Instant fin : List.of(AHORA.minusSeconds(1), AHORA)) {
            Cliente cliente = cliente();
            proyectar(cliente, "active", "paid", AHORA.minusSeconds(3600), fin, false);
            comprobarDenegacion(cliente, AHORA);
            assertEquals("ACTIVA", membresias.consultarResumenMembresia(cliente.id()).estado());
        }
    }

    @Test
    void periodoFuturoOAusenteNoConcedeAcceso() {
        Cliente futuro = cliente();
        proyectar(futuro, "active", "paid", AHORA.plusSeconds(1), AHORA.plusSeconds(3600), false);
        comprobarDenegacion(futuro, AHORA);
        Cliente sinPeriodo = cliente();
        proyectar(sinPeriodo, "active", "paid", null, null, false);
        comprobarDenegacion(sinPeriodo, AHORA);
    }

    @Test
    void cancelacionEfectivaDeniegaAunqueElPeriodoTengaFechaFutura() {
        Cliente cliente = cliente();
        proyectar(cliente, "canceled", "paid", AHORA.minusSeconds(3600), AHORA.plusSeconds(3600), false);
        assertEquals("CANCELADA", membresias.consultarResumenMembresia(cliente.id()).estado());
        comprobarDenegacion(cliente, AHORA);
    }

    @Test
    void ausenciaDeMembresiaYCheckoutPendienteDeniegan() {
        Cliente sinMembresia = cliente();
        assertEquals("SIN_MEMBRESIA", membresias.consultarResumenMembresia(sinMembresia.id()).estado());
        comprobarDenegacion(sinMembresia, AHORA);
        Cliente checkout = cliente();
        membresias.reservarCheckout(checkout.id(), "a".repeat(64), "b".repeat(64), PRICE_ID, AHORA);
        assertEquals("PENDIENTE", membresias.consultarResumenMembresia(checkout.id()).estado());
        comprobarDenegacion(checkout, AHORA);
    }

    @Test
    void pagoFallidoIncompletoYEstadosSinDerechoDeniegan() {
        String[][] estados = {
            {"active", "open", "PAGO_VENCIDO"},
            {"active", "payment_failed", "PAGO_VENCIDO"},
            {"active", "uncollectible", "PAGO_VENCIDO"},
            {"active", null, "PENDIENTE"},
            {"past_due", "paid", "PAGO_VENCIDO"},
            {"unpaid", "paid", "PAGO_VENCIDO"},
            {"incomplete", "paid", "PENDIENTE"},
            {"trialing", "paid", "PENDIENTE"},
            {"incomplete_expired", "paid", "INACTIVA"},
            {"paused", "paid", "INACTIVA"}
        };
        for (String[] estado : estados) {
            Cliente cliente = cliente();
            proyectar(cliente, estado[0], estado[1], AHORA.minusSeconds(3600), AHORA.plusSeconds(3600), false);
            assertEquals(estado[2], membresias.consultarResumenMembresia(cliente.id()).estado());
            comprobarDenegacion(cliente, AHORA);
        }
    }

    @Test
    void cancelacionProgramadaPermiteHastaSuFinYDeniegaDesdeEseInstante() {
        Cliente vigente = cliente();
        Instant fin = AHORA.plusSeconds(60);
        proyectar(vigente, "active", "paid", AHORA.minusSeconds(3600), fin, true);
        assertTrue(membresias.consultarResumenMembresia(vigente.id()).cancelacionAlFinal());
        assertEquals("AUTORIZADA", entrada(vigente, UUID.randomUUID(), fin.minusNanos(1000)).resultado());
        Cliente vencida = cliente();
        proyectar(vencida, "active", "paid", AHORA.minusSeconds(3600), fin, true);
        comprobarDenegacion(vencida, fin);
        assertEquals("ACTIVA", membresias.consultarResumenMembresia(vencida.id()).estado());
    }

    @Test
    void rfid3PermiteSalirTrasVencimientoOCancelacionDeMembresia() {
        for (boolean cancelada : new boolean[] {false, true}) {
            Cliente cliente = cliente();
            proyectar(cliente, "active", "paid", AHORA.minusSeconds(3600), AHORA.plusSeconds(3600), false);
            assertEquals("AUTORIZADA", entrada(cliente, UUID.randomUUID(), AHORA.minusSeconds(10)).resultado());
            proyectar(cliente, cancelada ? "canceled" : "active", "paid", AHORA.minusSeconds(3600),
                    cancelada ? AHORA.plusSeconds(3600) : AHORA.minusSeconds(1), false);
            UUID salida = UUID.randomUUID();
            RepositorioRfid3Jdbc repositorio = new RepositorioRfid3Jdbc(jdbc, administrador,
                    new RepositorioEventoAccesoJdbc(jdbc, null));
            assertEquals("AUTORIZADA", repositorio.registrarSalida(cliente.uid(), salida).resultado());
            assertEquals(0, abiertos(cliente));
            assertEquals("AUTORIZADA", eventoSalida(salida).get("resultado"));
            assertEquals("ACTIVA", tarjeta(cliente).get("estado"));
        }
    }

    @Test
    void replayPrevioAMembresiaConservaMovimientoEventoYConflicto() {
        Cliente cliente = cliente();
        proyectar(cliente, "active", "paid", AHORA.minusSeconds(3600), AHORA.plusSeconds(3600), false);
        UUID lectura = UUID.randomUUID();
        assertEquals("AUTORIZADA", entrada(cliente, lectura, AHORA).resultado());
        Map<String, Object> eventoOriginal = evento(lectura);
        Map<String, Object> movimientoOriginal = jdbc.queryForMap(
                "SELECT * FROM movimiento_estacionamiento WHERE lectura_id = ?", lectura);
        proyectar(cliente, "canceled", "paid", AHORA.minusSeconds(3600), AHORA.plusSeconds(3600), false);
        assertEquals("AUTORIZADA", entrada(cliente, lectura, AHORA.plusSeconds(7200)).resultado());
        assertEquals(eventoOriginal, evento(lectura));
        assertEquals(movimientoOriginal, jdbc.queryForMap(
                "SELECT * FROM movimiento_estacionamiento WHERE lectura_id = ?", lectura));
        assertEquals(1, abiertos(cliente));
        assertEquals("ENTRADA_PENDIENTE", entrada(cliente, UUID.randomUUID(), AHORA).motivo());
        Cliente otro = cliente();
        assertThrows(LecturaRfid2ConflictException.class, () -> entrada(otro, lectura, AHORA));
        assertEquals(0, abiertos(otro));
    }

    @Test
    void informacionNoDisponibleFallaCerradoYRevierteTransaccion() {
        Cliente cliente = cliente();
        RepositorioMembresias noDisponible = mock(RepositorioMembresias.class);
        when(noDisponible.consultarResumenParaAcceso(cliente.id()))
                .thenThrow(new DataAccessResourceFailureException("Proyección no disponible."));
        RepositorioRfid2Jdbc repositorio = new RepositorioRfid2Jdbc(jdbc, administrador,
                new RepositorioEventoAccesoJdbc(jdbc, null), noDisponible);
        UUID lectura = UUID.randomUUID();
        Map<String, Object> tarjetaOriginal = tarjeta(cliente);
        assertThrows(DataAccessResourceFailureException.class, () -> repositorio.registrarEntrada(
                cliente.uid(), lectura, Clock.fixed(AHORA, ZoneOffset.UTC), ZoneOffset.UTC, hora -> true, 1L, new PlazoEntradaRfid2()));
        assertEquals(0, abiertos(cliente));
        assertEquals(0, jdbc.queryForObject("SELECT COUNT(*) FROM evento_acceso WHERE lectura_id = ?",
                Integer.class, lectura));
        assertEquals(tarjetaOriginal, tarjeta(cliente));
    }

    @Test
    void proyeccionNulaDeniegaSinCrearMovimiento() {
        Cliente cliente = cliente();
        RepositorioRfid2Jdbc repositorio = new RepositorioRfid2Jdbc(jdbc, administrador,
                new RepositorioEventoAccesoJdbc(jdbc, null), mock(RepositorioMembresias.class));
        assertEquals("MEMBRESIA_NO_VIGENTE", repositorio.registrarEntrada(cliente.uid(), UUID.randomUUID(),
                Clock.fixed(AHORA, ZoneOffset.UTC), ZoneOffset.UTC, hora -> true, 1L, new PlazoEntradaRfid2()).motivo());
        assertEquals(0, abiertos(cliente));
    }

    @Test
    void cupoLlenoYMembresiaNoVigenteDenieganSinOcuparPlaza() {
        Cliente vigente = cliente();
        Cliente sinMembresia = cliente();
        proyectar(vigente, "active", "paid", AHORA.minusSeconds(60), AHORA.plusSeconds(3600), false);
        int antes = jdbc.queryForObject(
                "SELECT COUNT(*) FROM movimiento_estacionamiento WHERE instante_salida IS NULL", Integer.class);
        jdbc.update("UPDATE vision_zona SET activa = FALSE");
        try {
            UUID lecturaCupo = UUID.randomUUID();
            UUID lecturaMembresia = UUID.randomUUID();
            assertEquals("CAPACIDAD_COMPLETA", entrada(vigente, lecturaCupo, AHORA).motivo());
            assertEquals("MEMBRESIA_NO_VIGENTE", entrada(sinMembresia, lecturaMembresia, AHORA).motivo());
            assertEquals("CAPACIDAD_COMPLETA", evento(lecturaCupo).get("motivo"));
            assertEquals("MEMBRESIA_NO_VIGENTE", evento(lecturaMembresia).get("motivo"));
            assertEquals(0, abiertos(vigente));
            assertEquals(0, abiertos(sinMembresia));
            assertEquals(antes, jdbc.queryForObject(
                    "SELECT COUNT(*) FROM movimiento_estacionamiento WHERE instante_salida IS NULL", Integer.class));
        } finally {
            jdbc.update("UPDATE vision_zona SET activa = TRUE");
        }
    }

    @Test
    void clientesConMembresiaVigenteCompitenPorLaUltimaPlaza() throws Exception {
        Cliente primero = cliente();
        Cliente segundo = cliente();
        proyectar(primero, "active", "paid", AHORA.minusSeconds(60), AHORA.plusSeconds(3600), false);
        proyectar(segundo, "active", "paid", AHORA.minusSeconds(60), AHORA.plusSeconds(3600), false);
        int antes = jdbc.queryForObject(
                "SELECT COUNT(*) FROM movimiento_estacionamiento WHERE instante_salida IS NULL", Integer.class);
        jdbc.update("UPDATE vision_zona SET activa = FALSE");
        jdbc.update("""
                UPDATE vision_zona SET activa = TRUE WHERE (fuente_id, vision_zone_id) IN
                (SELECT fuente_id, vision_zone_id FROM vision_zona ORDER BY vision_zone_id LIMIT ?)
                """, antes + 1);
        try (ExecutorService ejecutor = Executors.newFixedThreadPool(2);
                Connection bloqueo = origen.getConnection()) {
            bloqueo.setAutoCommit(false);
            try {
                try (PreparedStatement consulta = bloqueo.prepareStatement(
                        "SELECT id FROM configuracion_estacionamiento WHERE id = 1 FOR UPDATE")) {
                    consulta.executeQuery().close();
                }
                Future<ResultadoEntradaRfid2> entradaPrimera = ejecutor.submit(() -> entrada(primero, UUID.randomUUID(), AHORA));
                Future<ResultadoEntradaRfid2> entradaSegunda = ejecutor.submit(() -> entrada(segundo, UUID.randomUUID(), AHORA));
                long limite = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(1200);
                int esperas = 0;
                while (System.nanoTime() < limite) {
                    esperas = jdbc.queryForObject("SELECT COUNT(*) FROM pg_stat_activity "
                            + "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                            + "AND query LIKE '%FROM configuracion_estacionamiento%FOR UPDATE%'", Integer.class);
                    if (esperas >= 2) break;
                    Thread.sleep(10);
                }
                assertTrue(esperas >= 2, "Ambas entradas deben esperar el mutex de capacidad.");
                bloqueo.commit();
                List<ResultadoEntradaRfid2> resultados = List.of(
                        entradaPrimera.get(4, TimeUnit.SECONDS), entradaSegunda.get(4, TimeUnit.SECONDS));
                assertEquals(1, resultados.stream().filter(r -> "AUTORIZADA".equals(r.resultado())).count());
                assertEquals(1, resultados.stream().filter(r -> "CAPACIDAD_COMPLETA".equals(r.motivo())).count());
                assertEquals(1, abiertos(primero) + abiertos(segundo));
                assertEquals(antes + 1, jdbc.queryForObject(
                        "SELECT COUNT(*) FROM movimiento_estacionamiento WHERE instante_salida IS NULL", Integer.class));
            } finally {
                bloqueo.rollback();
                ejecutor.shutdownNow();
            }
        } finally {
            jdbc.update("UPDATE vision_zona SET activa = TRUE");
        }
    }

    @Test
    void inyeccionSpringExigeTransaccionYAutorizaConElMismoContrato() {
        try (AnnotationConfigApplicationContext contexto = new AnnotationConfigApplicationContext()) {
            contexto.register(TransaccionesDePrueba.class);
            contexto.registerBean(JdbcTemplate.class, () -> jdbc);
            contexto.registerBean(PlatformTransactionManager.class, () -> administrador);
            contexto.registerBean(RepositorioMembresiasJdbc.class);
            contexto.registerBean(RepositorioEventoAccesoJdbc.class, () -> new RepositorioEventoAccesoJdbc(jdbc, null));
            contexto.registerBean(RepositorioRfid2Jdbc.class);
            contexto.refresh();
            RepositorioMembresias proyeccion = contexto.getBean(RepositorioMembresias.class);
            assertTrue(AopUtils.isAopProxy(proyeccion));
            Cliente cliente = cliente();
            proyectar(cliente, "active", "paid", AHORA.minusSeconds(3600), AHORA.plusSeconds(3600), false);
            assertThrows(IllegalTransactionStateException.class, () -> proyeccion.consultarResumenParaAcceso(cliente.id()));
            assertEquals("AUTORIZADA", contexto.getBean(RepositorioRfid2Jdbc.class).registrarEntrada(cliente.uid(),
                    UUID.randomUUID(), Clock.fixed(AHORA, ZoneOffset.UTC), ZoneOffset.UTC, hora -> true, 1L, new PlazoEntradaRfid2()).resultado());
            assertEquals(1, abiertos(cliente));
        }
    }

    @Test
    void repeticionDeDenegacionConservaUnSoloEventoYPermiteRenovacionConNuevaLectura() {
        Cliente cliente = cliente();
        UUID lectura = UUID.randomUUID();
        assertEquals("MEMBRESIA_NO_VIGENTE", entrada(cliente, lectura, AHORA).motivo());
        Map<String, Object> original = evento(lectura);
        assertEquals("MEMBRESIA_NO_VIGENTE", entrada(cliente, lectura, AHORA.plusSeconds(1)).motivo());
        assertEquals(original, evento(lectura));
        assertEquals(1, jdbc.queryForObject("SELECT COUNT(*) FROM evento_acceso WHERE lectura_id = ?",
                Integer.class, lectura));
        assertEquals(0, abiertos(cliente));
        proyectar(cliente, "active", "paid", AHORA, AHORA.plusSeconds(3600), false);
        assertEquals("AUTORIZADA", entrada(cliente, UUID.randomUUID(), AHORA).resultado());
        assertEquals("ACTIVA", tarjeta(cliente).get("estado"));
    }

    @Test
    void cancelacionConcurrenteSeLeeDespuesDelBloqueoDelWebhook() throws Exception {
        comprobarEsperaPorMembresia(true);
    }

    @Test
    void vencimientoDuranteEsperaUsaHoraPosteriorAlBloqueo() throws Exception {
        comprobarEsperaPorMembresia(false);
    }

    @Test
    void v22Yv23ConservanHistoriaYAcotanAmbosMotivos() {
        String esquema = "rfid2_historico_" + sufijo();
        DataSource historico = HorarioRfid2PostgresTest.baseDescartable(esquema);
        Flyway.configure().dataSource(historico).schemas(esquema).defaultSchema(esquema)
                .target("21").cleanDisabled(true).load().migrate();
        JdbcTemplate anterior = new JdbcTemplate(historico);
        long empleado = anterior.queryForObject("INSERT INTO empleado (nombres, primer_apellido, estado) "
                + "VALUES ('Sintetico', 'Prueba', 'ACTIVO') RETURNING id", Long.class);
        String uid = sufijo().substring(0, 20).toUpperCase(Locale.ROOT);
        long asociacion = anterior.queryForObject("INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico, empleado_id) "
                + "VALUES (?, ?) RETURNING asociacion_id", Long.class, uid, empleado);
        anterior.update("""
                INSERT INTO movimiento_estacionamiento (asociacion_id, tipo_persona, empleado_id,
                    uid_historico, lectura_id, fecha_entrada, hora_entrada, instante_entrada)
                VALUES (?, 'EMPLEADO', ?, ?, ?, CURRENT_DATE, CURRENT_TIME, CURRENT_TIMESTAMP)
                """, asociacion, empleado, uid, UUID.randomUUID());
        String insertar = "INSERT INTO evento_acceso (ocurrido_en, lector, resultado, motivo, lectura_id, "
                + "asociacion_id, movimiento_id) VALUES (now(), ?, 'DENEGADA', ?, ?, ?, ?)";
        anterior.update(insertar, "RFID2", "FUERA_DE_HORARIO", UUID.randomUUID(), asociacion, null);
        assertThrows(DataIntegrityViolationException.class, () -> anterior.update(insertar, "RFID2",
                "MEMBRESIA_NO_VIGENTE", UUID.randomUUID(), asociacion, null));
        List<Map<String, Object>> movimientos = anterior.queryForList("SELECT * FROM movimiento_estacionamiento");
        List<Map<String, Object>> eventos = anterior.queryForList("SELECT * FROM evento_acceso ORDER BY evento_id");
        List<Map<String, Object>> migraciones = anterior.queryForList(
                "SELECT version, checksum, success FROM flyway_schema_history WHERE version IS NOT NULL ORDER BY version");
        Flyway.configure().dataSource(historico).schemas(esquema).defaultSchema(esquema)
                .target("23").cleanDisabled(true).load().migrate();
        assertEquals(movimientos, anterior.queryForList("SELECT * FROM movimiento_estacionamiento"));
        assertEquals(eventos, anterior.queryForList("SELECT * FROM evento_acceso ORDER BY evento_id"));
        assertEquals(migraciones, anterior.queryForList("SELECT version, checksum, success FROM flyway_schema_history "
                + "WHERE version IS NOT NULL AND version NOT IN ('22', '23') ORDER BY version"));
        assertEquals(2, anterior.queryForObject(
                "SELECT COUNT(*) FROM flyway_schema_history WHERE version IN ('22', '23') AND success", Integer.class));
        assertEquals(1, anterior.update(insertar, "RFID2", "CAPACIDAD_COMPLETA",
                UUID.randomUUID(), asociacion, null));
        assertEquals(1, anterior.update(insertar, "RFID2", "MEMBRESIA_NO_VIGENTE",
                UUID.randomUUID(), asociacion, null));
        assertThrows(DataIntegrityViolationException.class, () -> anterior.update(insertar, "RFID2",
                "MEMBRESIA_NO_VIGENTE", UUID.randomUUID(), null, null));
        assertThrows(DataIntegrityViolationException.class, () -> anterior.update(insertar, "RFID3",
                "MEMBRESIA_NO_VIGENTE", UUID.randomUUID(), asociacion, null));
        assertThrows(DataIntegrityViolationException.class, () -> anterior.update(insertar, "RFID2",
                "MEMBRESIA_NO_VIGENTE", UUID.randomUUID(), asociacion, movimientos.getFirst().get("movimiento_id")));
        assertThrows(DataIntegrityViolationException.class, () -> anterior.update(insertar, "RFID2",
                "MOTIVO_ARBITRARIO", UUID.randomUUID(), asociacion, null));
    }

    private static void comprobarEsperaPorMembresia(boolean cancelar) throws Exception {
        Cliente cliente = cliente();
        proyectar(cliente, "active", "paid", AHORA.minusSeconds(3600), AHORA.plusSeconds(60), false);
        AtomicReference<Instant> hora = new AtomicReference<>(AHORA);
        Clock reloj = new Clock() {
            public java.time.ZoneId getZone() { return ZoneOffset.UTC; }
            public Clock withZone(java.time.ZoneId zona) { return this; }
            public Instant instant() { return hora.get(); }
        };
        try (ExecutorService ejecutor = Executors.newSingleThreadExecutor(); Connection bloqueo = origen.getConnection()) {
            bloqueo.setAutoCommit(false);
            try {
                try (PreparedStatement consulta = bloqueo.prepareStatement("SELECT id FROM cuenta WHERE id = ? FOR UPDATE")) {
                    consulta.setObject(1, cliente.id());
                    consulta.executeQuery().close();
                }
                if (cancelar) {
                    try (PreparedStatement cambio = bloqueo.prepareStatement(
                            "UPDATE suscripcion_cliente SET estado = 'CANCELADA', estado_stripe = 'canceled' WHERE cliente_id = ?")) {
                        cambio.setObject(1, cliente.id());
                        cambio.executeUpdate();
                    }
                }
                Future<ResultadoEntradaRfid2> pendiente = ejecutor.submit(() -> new RepositorioRfid2Jdbc(jdbc,
                        administrador).registrarEntrada(cliente.uid(), UUID.randomUUID(), reloj, ZoneOffset.UTC, h -> true, 1L, new PlazoEntradaRfid2()));
                long limite = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
                boolean esperando = false;
                while (System.nanoTime() < limite) {
                    esperando = jdbc.queryForObject("SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                            + "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                            + "AND query LIKE '%FROM cliente_codigo_publico AS codigo%')", Boolean.class);
                    if (esperando) {
                        break;
                    }
                    Thread.sleep(10);
                }
                assertTrue(esperando, "RFID2 debe esperar el bloqueo que protege la proyección.");
                assertFalse(pendiente.isDone());
                if (!cancelar) {
                    hora.set(AHORA.plusSeconds(120));
                }
                bloqueo.commit();
                assertEquals("MEMBRESIA_NO_VIGENTE", pendiente.get(5, TimeUnit.SECONDS).motivo());
                assertEquals(0, abiertos(cliente));
            } finally {
                bloqueo.rollback();
                ejecutor.shutdownNow();
            }
        }
    }

    private static void comprobarDenegacion(Cliente cliente, Instant instante) {
        Map<String, Object> tarjetaOriginal = tarjeta(cliente);
        int ocupacion = jdbc.queryForObject("SELECT COUNT(*) FROM movimiento_estacionamiento WHERE instante_salida IS NULL",
                Integer.class);
        UUID lectura = UUID.randomUUID();
        assertEquals("MEMBRESIA_NO_VIGENTE", entrada(cliente, lectura, instante).motivo());
        assertEquals(0, abiertos(cliente));
        assertEquals(0, jdbc.queryForObject("SELECT COUNT(*) FROM movimiento_estacionamiento WHERE asociacion_id = ?",
                Integer.class, cliente.asociacionId()));
        assertEquals(ocupacion, jdbc.queryForObject(
                "SELECT COUNT(*) FROM movimiento_estacionamiento WHERE instante_salida IS NULL", Integer.class));
        assertEquals(tarjetaOriginal, tarjeta(cliente));
        Map<String, Object> evento = evento(lectura);
        assertEquals("DENEGADA", evento.get("resultado"));
        assertEquals("MEMBRESIA_NO_VIGENTE", evento.get("motivo"));
        assertEquals(cliente.asociacionId(), evento.get("asociacion_id"));
        assertNull(evento.get("movimiento_id"));
    }

    private static ResultadoEntradaRfid2 entrada(Cliente cliente, UUID lectura, Instant instante) {
        return new RepositorioRfid2Jdbc(jdbc, administrador).registrarEntrada(cliente.uid(), lectura,
                Clock.fixed(instante, ZoneOffset.UTC), ZoneOffset.UTC, hora -> true, 1L, new PlazoEntradaRfid2());
    }

    private static Cliente cliente() {
        UUID id = UUID.randomUUID();
        String correo = id + "@example.invalid";
        jdbc.update("""
                INSERT INTO cuenta (id, nombres, primer_apellido, correo, correo_normalizado, rol, estado,
                    hash_contrasena_acceso, revision_acceso, creada_en, actualizada_en)
                VALUES (?, 'Sintetico', 'Prueba', ?, ?, 'CLIENTE', 'ACTIVA', 'hash-sintetico', 1, now(), now())
                """, id, correo, correo);
        String uid = sufijo().substring(0, 20).toUpperCase(Locale.ROOT);
        long asociacion = jdbc.queryForObject("INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico, cliente_id) "
                + "VALUES (?, ?) RETURNING asociacion_id", Long.class, uid, id);
        String customer = "cus_" + sufijo();
        membresias.reservarClienteStripe(id, AHORA);
        membresias.asociarCustomer(id, customer, AHORA);
        return new Cliente(id, uid, asociacion, customer, "sub_" + sufijo());
    }

    private static void proyectar(Cliente cliente, String estado, String factura, Instant inicio, Instant fin,
            boolean cancelacionAlFinal) {
        String evento = "evt_" + sufijo();
        String tipo = "canceled".equals(estado) ? "customer.subscription.deleted" : "customer.subscription.updated";
        Instant creado = AHORA.plusSeconds(SECUENCIA_EVENTOS.incrementAndGet());
        membresias.registrarEventoStripe(evento, tipo, cliente.suscripcion(), creado);
        membresias.aplicarActualizacionStripe(new ActualizacionStripe(evento, tipo, creado, null, null,
                cliente.customer(), cliente.suscripcion(), cliente.id(), PRICE_ID, estado, "in_" + sufijo(), factura,
                inicio, fin, cancelacionAlFinal, creado, true));
    }

    private static int abiertos(Cliente cliente) {
        return jdbc.queryForObject("SELECT COUNT(*) FROM movimiento_estacionamiento "
                + "WHERE asociacion_id = ? AND instante_salida IS NULL", Integer.class, cliente.asociacionId());
    }

    private static Map<String, Object> tarjeta(Cliente cliente) {
        return jdbc.queryForMap("SELECT * FROM asociacion_tarjeta_rfid1 WHERE asociacion_id = ?", cliente.asociacionId());
    }

    private static Map<String, Object> evento(UUID lectura) {
        return jdbc.queryForMap("SELECT * FROM evento_acceso WHERE lector = 'RFID2' AND lectura_id = ?", lectura);
    }

    private static Map<String, Object> eventoSalida(UUID lectura) {
        return jdbc.queryForMap("SELECT * FROM evento_acceso WHERE lector = 'RFID3' AND lectura_id = ?", lectura);
    }

    private static String sufijo() {
        return UUID.randomUUID().toString().replace("-", "");
    }

    private static void configurarSalida() {
        if ("SIN_CONFIGURAR".equals(jdbc.queryForObject(
                "SELECT estado FROM configuracion_estacionamiento WHERE id = 1", String.class))) {
            UUID dueno = UUID.randomUUID();
            String correo = dueno + "@example.invalid";
            jdbc.update("""
                    INSERT INTO cuenta (id, nombres, primer_apellido, correo, correo_normalizado, rol, estado,
                        hash_contrasena_acceso, revision_acceso, creada_en, actualizada_en)
                    VALUES (?, 'Sintetico', 'Prueba', ?, ?, 'DUENO', 'ACTIVA', 'hash-sintetico', 1, now(), now())
                    """, dueno, correo, correo);
            jdbc.update("""
                    UPDATE configuracion_estacionamiento SET estado = 'CONFIGURADA', revision = 1, revision_propietario = 1,
                        estacionamiento_id = ?, dueno_cuenta_id = ?, hash_contrasena_administrativa = 'hash-sintetico',
                        nombre_estacionamiento = 'Prueba', tipo_estacionamiento = 'MIXTO', modo_horario = 'CONTINUO_24_7',
                        zona_horaria = 'America/Mexico_City' WHERE id = 1
                    """, UUID.randomUUID(), dueno);
        }
        UUID estacionamiento = jdbc.queryForObject(
                "SELECT estacionamiento_id FROM configuracion_estacionamiento WHERE id = 1", UUID.class);
        UUID fuente = UUID.randomUUID();
        jdbc.update("INSERT INTO vision_fuente (fuente_id, estacionamiento_id) VALUES (?, ?)", fuente, estacionamiento);
        for (int numero = 0; numero < 150; numero++) {
            UUID cajon = UUID.randomUUID();
            jdbc.update("INSERT INTO vision_cajon (cajon_id, estacionamiento_id, etiqueta) VALUES (?, ?, ?)",
                    cajon, estacionamiento, "M" + numero);
            jdbc.update("INSERT INTO vision_zona (fuente_id, vision_zone_id, cajon_id) VALUES (?, ?, ?)",
                    fuente, UUID.randomUUID(), cajon);
        }
    }

    private record Cliente(UUID id, String uid, long asociacionId, String customer, String suscripcion) { }

    @Configuration(proxyBeanMethods = false)
    @EnableTransactionManagement
    static class TransaccionesDePrueba { }
}
