package mx.smartparking.api.vision;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.net.URI;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicInteger;
import javax.sql.DataSource;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.vision.ContratosVision.*;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Configuration;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import org.springframework.transaction.support.TransactionTemplate;

/** Pruebas sobre un esquema nuevo en una base descartable dedicada y explícita. */
@EnabledIfSystemProperty(named = "vision.integration.disposable", matches = "true")
class ServicioVisionPostgresTest {
    private static final String HASH = "a".repeat(64);
    private static final Instant INICIO = Instant.parse("2026-11-02T12:00:00Z");
    private static AnnotationConfigApplicationContext contexto;
    private static JdbcTemplate jdbc;
    private static ServicioVision servicio;
    private static RelojMutable reloj;
    private static final AtomicInteger invalidaciones = new AtomicInteger();
    private UUID fuente;
    private UUID zonaA;
    private UUID zonaB;
    private UUID cajonA;
    private UUID cajonB;
    private SolicitudSesion apertura;
    private UUID sesion;

    @BeforeAll
    static void prepararBaseDescartable() {
        String url = System.getenv("VISION_TEST_JDBC_URL");
        String usuario = System.getenv("VISION_TEST_JDBC_USER");
        String password = System.getenv("VISION_TEST_JDBC_PASSWORD");
        if (url == null || usuario == null || password == null || !url.startsWith("jdbc:postgresql://")) {
            throw new IllegalStateException("Se requiere la conexión de prueba descartable explícita.");
        }
        URI destino = URI.create(url.substring("jdbc:".length()));
        if (!"db".equals(destino.getHost()) || destino.getPort() != 5432
                || !"/vision_phase_b_test".equals(destino.getPath()) || destino.getQuery() != null) {
            throw new IllegalStateException("La prueba solo admite db:5432/vision_phase_b_test en red aislada.");
        }
        DriverManagerDataSource comprobacion = new DriverManagerDataSource(url, usuario, password);
        if (!"vision_phase_b_test".equals(new JdbcTemplate(comprobacion)
                .queryForObject("SELECT current_database()", String.class))) {
            throw new IllegalStateException("La base conectada no es la base de prueba descartable.");
        }
        String esquema = "vision_t_" + UUID.randomUUID().toString().replace("-", "");
        Flyway.configure().dataSource(url, usuario, password).schemas(esquema).defaultSchema(esquema)
                .createSchemas(true).load().migrate();
        DataSource datos = new DriverManagerDataSource(url + "?currentSchema=" + esquema, usuario, password);
        jdbc = new JdbcTemplate(datos);
        UUID dueno = UUID.randomUUID();
        jdbc.update("""
                INSERT INTO cuenta (id, nombres, primer_apellido, correo, correo_normalizado, rol, estado,
                    hash_contrasena_acceso, revision_acceso, creada_en, actualizada_en)
                VALUES (?, 'Prueba', 'Sintetica', 'vision@example.invalid', 'vision@example.invalid',
                    'DUENO', 'ACTIVA', 'hash-prueba', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, dueno);
        jdbc.update("""
                UPDATE configuracion_estacionamiento SET estado = 'CONFIGURADA', estacionamiento_id = ?,
                    dueno_cuenta_id = ?, hash_contrasena_administrativa = 'hash-prueba',
                    nombre_estacionamiento = 'Prueba', tipo_estacionamiento = 'PRIVADO',
                    modo_horario = 'CONTINUO_24_7', zona_horaria = 'UTC' WHERE id = 1
                """, UUID.randomUUID(), dueno);
        reloj = new RelojMutable(INICIO);
        contexto = new AnnotationConfigApplicationContext();
        contexto.register(Transacciones.class);
        contexto.registerBean(DataSource.class, () -> datos);
        contexto.registerBean(JdbcTemplate.class, () -> jdbc);
        contexto.registerBean(PlatformTransactionManager.class, () -> new DataSourceTransactionManager(datos));
        contexto.registerBean(ServicioVision.class,
                () -> new ServicioVision(jdbc, reloj, 45, 15, 3, 30, 4096, invalidaciones::incrementAndGet));
        contexto.refresh();
        servicio = contexto.getBean(ServicioVision.class);
    }

    @AfterAll
    static void cerrarContexto() {
        if (contexto != null) {
            contexto.close();
        }
    }

    @BeforeEach
    void crearFuente() {
        reloj.poner(INICIO);
        fuente = UUID.randomUUID();
        zonaA = UUID.randomUUID();
        zonaB = UUID.randomUUID();
        servicio.registrarFuente(new SolicitudFuente(fuente));
        RespuestaCalibracion calibracion = servicio.activarCalibracion(fuente, calibracion(1L, HASH,
                new ZonaConfiguracion(zonaA, "C1", null), new ZonaConfiguracion(zonaB, "C2", null)));
        cajonA = calibracion.zonas().get(0).cajonId();
        cajonB = calibracion.zonas().get(1).cajonId();
        reloj.poner(INICIO.plusSeconds(1));
        apertura = new SolicitudSesion(fuente, UUID.randomUUID(), reloj.instant());
        sesion = servicio.abrirSesion(apertura).sesionId();
    }

    @Test
    void guardarSnapshotRevocaSesionYReiniciaSecuencia() {
        reloj.poner(INICIO.plusSeconds(2));
        servicio.observar(observacion(sesion, 1, UUID.randomUUID(), 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "OCUPADO"), new ZonaObservacion(zonaB, "LIBRE")));
        int antes = invalidaciones.get();
        reloj.poner(INICIO.plusSeconds(3));
        servicio.activarCalibracion(fuente, calibracion(1L, HASH,
                new ZonaConfiguracion(zonaA, "C1", cajonA), new ZonaConfiguracion(zonaB, "C2", cajonB)));
        assertEquals(antes + 1, invalidaciones.get());
        assertNull(jdbc.queryForObject("SELECT sesion_id FROM vision_fuente WHERE fuente_id = ?", UUID.class, fuente));
        assertEquals(0L, jdbc.queryForObject("SELECT ultima_secuencia FROM vision_fuente WHERE fuente_id = ?",
                Long.class, fuente));
        assertThrows(ErrorConfiguracion.class, () -> servicio.abrirSesion(apertura));
        reloj.poner(INICIO.plusSeconds(4));
        UUID siguiente = servicio.abrirSesion(new SolicitudSesion(fuente, UUID.randomUUID(), reloj.instant())).sesionId();
        assertNotEquals(sesion, siguiente);
    }

    @Test
    void falloDelCallbackNoRevierteElCommit() {
        ServicioVision conFallo = new ServicioVision(jdbc, reloj, 45, 15, 3, 30, 4096,
                () -> { throw new IllegalStateException("fallo sintético"); });
        TransactionTemplate transaccion = new TransactionTemplate(contexto.getBean(PlatformTransactionManager.class));
        reloj.poner(INICIO.plusSeconds(2));
        SolicitudObservacion primera = observacion(sesion, 1, UUID.randomUUID(), 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "OCUPADO"), new ZonaObservacion(zonaB, "LIBRE"));
        assertTrue(transaccion.execute(estado -> conFallo.observar(primera)).aceptada());
        assertEquals("OCUPADO", estado(cajonA).estado());
    }

    @Test
    void otraConexionSoloVeLasObservacionesDespuesDelCommit() throws Exception {
        reloj.poner(INICIO.plusSeconds(2));
        SolicitudObservacion primera = observacion(sesion, 1, UUID.randomUUID(), 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "LIBRE"), new ZonaObservacion(zonaB, "OCUPADO"));
        TransactionTemplate transaccion = new TransactionTemplate(contexto.getBean(PlatformTransactionManager.class));
        int antes = invalidaciones.get();
        String contar = "SELECT count(*) FROM vision_ocupacion WHERE fuente_id = ?";

        try (Connection conexionObservadora = contexto.getBean(DataSource.class).getConnection()) {
            conexionObservadora.setTransactionIsolation(Connection.TRANSACTION_READ_COMMITTED);
            assertTrue(conexionObservadora.getAutoCommit());
            JdbcTemplate observador = new JdbcTemplate(new SingleConnectionDataSource(conexionObservadora, true));
            Integer procesoObservador = observador.queryForObject("SELECT pg_backend_pid()", Integer.class);

            transaccion.executeWithoutResult(estado -> {
                assertTrue(servicio.observar(primera).aceptada());
                assertNotEquals(procesoObservador, jdbc.queryForObject("SELECT pg_backend_pid()", Integer.class));
                assertEquals(2L, jdbc.queryForObject(contar, Long.class, fuente));
                assertEquals(0L, observador.queryForObject(contar, Long.class, fuente));
                assertEquals(antes, invalidaciones.get());
                estado.setRollbackOnly();
            });
            assertEquals(0L, observador.queryForObject(contar, Long.class, fuente));
            assertEquals(antes, invalidaciones.get());

            transaccion.executeWithoutResult(estado -> {
                assertTrue(servicio.observar(primera).aceptada());
                assertNotEquals(procesoObservador, jdbc.queryForObject("SELECT pg_backend_pid()", Integer.class));
                assertEquals(2L, jdbc.queryForObject(contar, Long.class, fuente));
                assertEquals(0L, observador.queryForObject(contar, Long.class, fuente));
                assertEquals(antes, invalidaciones.get());
            });
            assertEquals(2L, observador.queryForObject(contar, Long.class, fuente));
            assertEquals("LIBRE", observador.queryForObject(
                    "SELECT ultimo_estado FROM vision_ocupacion WHERE cajon_id = ?", String.class, cajonA));
            assertEquals("OCUPADO", observador.queryForObject(
                    "SELECT ultimo_estado FROM vision_ocupacion WHERE cajon_id = ?", String.class, cajonB));
            assertEquals(antes + 1, invalidaciones.get());
        }
    }

    @Test
    void publicaSoloCambiosEfectivosConfirmadosYNoReplays() {
        reloj.poner(INICIO.plusSeconds(2));
        SolicitudObservacion primera = observacion(sesion, 1, UUID.randomUUID(), 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "LIBRE"), new ZonaObservacion(zonaB, "OCUPADO"));
        TransactionTemplate transaccion = new TransactionTemplate(contexto.getBean(PlatformTransactionManager.class));
        int antes = invalidaciones.get();
        transaccion.executeWithoutResult(estado -> {
            servicio.observar(primera);
            assertEquals(antes, invalidaciones.get());
            estado.setRollbackOnly();
        });
        assertEquals(antes, invalidaciones.get());
        servicio.observar(primera);
        assertEquals(antes + 1, invalidaciones.get());
        servicio.observar(primera);
        assertEquals(antes + 1, invalidaciones.get());
        reloj.poner(INICIO.plusSeconds(3));
        servicio.observar(observacion(sesion, 2, UUID.randomUUID(), 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "LIBRE"), new ZonaObservacion(zonaB, "OCUPADO")));
        assertEquals(antes + 1, invalidaciones.get());
        reloj.poner(INICIO.plusSeconds(49));
        servicio.observar(observacion(sesion, 3, UUID.randomUUID(), 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "LIBRE"), new ZonaObservacion(zonaB, "OCUPADO")));
        assertEquals(antes + 2, invalidaciones.get());
        ServicioVision.LecturaCajones lectura = servicio.consultarCajonesConVigencia();
        assertTrue(lectura.vigenciaRestanteMs() != null && lectura.vigenciaRestanteMs() >= 0
                && lectura.vigenciaRestanteMs() <= 45_000);
    }

    @Test
    void duplicadoNoRenuevaVigenciaYNuevaObservacionRecuperaEstado() {
        reloj.poner(INICIO.plusSeconds(2));
        SolicitudObservacion primera = observacion(sesion, 1, UUID.randomUUID(), 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "LIBRE"), new ZonaObservacion(zonaB, "OCUPADO"));
        servicio.observar(primera);
        assertEquals("LIBRE", estado(cajonA).estado());
        assertEquals("OCUPADO", estado(cajonB).estado());
        reloj.poner(INICIO.plusSeconds(48));
        assertEquals("NO_VERIFICABLE", estado(cajonA).estado());
        assertEquals("LIBRE", estado(cajonA).ultimoEstadoConfirmado());
        assertTrue(servicio.observar(primera).aceptada());
        assertEquals("NO_VERIFICABLE", estado(cajonA).estado());
        SolicitudObservacion nueva = observacion(sesion, 2, UUID.randomUUID(), 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "OCUPADO"), new ZonaObservacion(zonaB, "LIBRE"));
        servicio.observar(nueva);
        assertEquals("OCUPADO", estado(cajonA).estado());
        assertEquals("LIBRE", estado(cajonB).estado());
    }

    @Test
    void idempotenciaYOrdenDeAperturaImpidenReactivarLaSesionAnterior() {
        assertEquals(sesion, servicio.abrirSesion(apertura).sesionId());
        reloj.poner(INICIO.plusSeconds(3));
        SolicitudSesion nueva = new SolicitudSesion(fuente, UUID.randomUUID(), reloj.instant());
        UUID sesionNueva = servicio.abrirSesion(nueva).sesionId();
        assertNotEquals(sesion, sesionNueva);
        assertThrows(ErrorConfiguracion.class, () -> servicio.abrirSesion(apertura));
        assertThrows(ErrorConfiguracion.class, () -> servicio.abrirSesion(
                new SolicitudSesion(fuente, UUID.randomUUID(), INICIO.plusSeconds(2))));
        assertEquals(sesionNueva, servicio.abrirSesion(nueva).sesionId());
        assertEquals("NO_VERIFICABLE", estado(cajonA).estado());
    }

    @Test
    void consultaCalibracionSoloDevuelveElMapaActivoSinAlterarLaSesion() {
        RespuestaCalibracion lectura = servicio.consultarCalibracion(fuente);
        assertEquals(fuente, lectura.fuenteId());
        assertEquals(java.util.Set.of(new ZonaConfiguracion(zonaA, "C1", cajonA),
                        new ZonaConfiguracion(zonaB, "C2", cajonB)), java.util.Set.copyOf(lectura.zonas()));
        assertEquals(sesion, servicio.abrirSesion(apertura).sesionId());
        assertThrows(ErrorConfiguracion.class, () -> servicio.consultarCalibracion(UUID.randomUUID()));
        reloj.poner(INICIO.plusSeconds(3));
        servicio.activarCalibracion(fuente, calibracion(2L, "b".repeat(64),
                new ZonaConfiguracion(zonaA, "C1", cajonA)));
        RespuestaCalibracion posterior = servicio.consultarCalibracion(fuente);
        assertEquals(List.of(new ZonaConfiguracion(zonaA, "C1", cajonA)), posterior.zonas());
    }

    @Test
    void observacionEnVueloEsRechazadaSiLaActivacionConfirmaPrimero() throws Exception {
        reloj.poner(INICIO.plusSeconds(5));
        SolicitudCalibracion candidata = calibracion(2L, "b".repeat(64),
                new ZonaConfiguracion(zonaA, "C1", cajonA), new ZonaConfiguracion(zonaB, "C2", cajonB));
        SolicitudObservacion antigua = observacion(sesion, 1, UUID.randomUUID(), 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "LIBRE"), new ZonaObservacion(zonaB, "OCUPADO"));
        CountDownLatch bloqueada = new CountDownLatch(1);
        CountDownLatch liberar = new CountDownLatch(1);
        CountDownLatch iniciada = new CountDownLatch(1);
        TransactionTemplate transaccion = new TransactionTemplate(contexto.getBean(PlatformTransactionManager.class));
        try (ExecutorService ejecutor = Executors.newFixedThreadPool(2)) {
            try {
                Future<?> activacion = ejecutor.submit(() -> transaccion.executeWithoutResult(estado -> {
                    servicio.activarCalibracion(fuente, candidata);
                    bloqueada.countDown();
                    try {
                        if (!liberar.await(5, TimeUnit.SECONDS)) {
                            throw new IllegalStateException("No se liberó la activación sintética.");
                        }
                    } catch (InterruptedException excepcion) {
                        Thread.currentThread().interrupt();
                        throw new IllegalStateException(excepcion);
                    }
                }));
                assertTrue(bloqueada.await(5, TimeUnit.SECONDS));
                Future<?> observacion = ejecutor.submit(() -> {
                    iniciada.countDown();
                    servicio.observar(antigua);
                });
                assertTrue(iniciada.await(5, TimeUnit.SECONDS));
                assertThrows(TimeoutException.class, () -> observacion.get(200, TimeUnit.MILLISECONDS));
                liberar.countDown();
                activacion.get(5, TimeUnit.SECONDS);
                ExecutionException error = assertThrows(ExecutionException.class,
                        () -> observacion.get(5, TimeUnit.SECONDS));
                assertTrue(error.getCause() instanceof ErrorConfiguracion);
                assertEquals(0L, jdbc.queryForObject(
                        "SELECT count(*) FROM vision_ocupacion WHERE fuente_id = ?", Long.class, fuente));
            } finally {
                liberar.countDown();
            }
        }
    }

    @Test
    void nombreVisiblePersisteSinCambiarIdentidadAsociacionNiOcupacion() {
        reloj.poner(INICIO.plusSeconds(2));
        servicio.observar(observacion(sesion, 1, UUID.randomUUID(), 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "OCUPADO"), new ZonaObservacion(zonaB, "LIBRE")));
        EstadoCajon antes = estado(cajonA);
        assertNull(antes.displayName());
        var zonaAntes = jdbc.queryForMap(
                "SELECT * FROM vision_zona WHERE fuente_id = ? AND vision_zone_id = ?", fuente, zonaA);
        var ocupacionAntes = jdbc.queryForMap("SELECT * FROM vision_ocupacion WHERE cajon_id = ?", cajonA);
        var fuenteAntes = jdbc.queryForMap("SELECT * FROM vision_fuente WHERE fuente_id = ?", fuente);

        servicio.actualizarNombreCajon(cajonA, "Entrada principal");
        EstadoCajon despues = estado(cajonA);
        assertEquals("Entrada principal", despues.displayName());
        assertEquals(antes.cajonId(), despues.cajonId());
        assertEquals(antes.etiqueta(), despues.etiqueta());
        assertEquals(antes.estado(), despues.estado());
        assertEquals(antes.ultimoEstadoConfirmado(), despues.ultimoEstadoConfirmado());
        assertEquals(antes.observadoEn(), despues.observadoEn());
        assertEquals(zonaAntes, jdbc.queryForMap(
                "SELECT * FROM vision_zona WHERE fuente_id = ? AND vision_zone_id = ?", fuente, zonaA));
        assertEquals(ocupacionAntes, jdbc.queryForMap("SELECT * FROM vision_ocupacion WHERE cajon_id = ?", cajonA));
        assertEquals(fuenteAntes, jdbc.queryForMap("SELECT * FROM vision_fuente WHERE fuente_id = ?", fuente));
        assertEquals("Entrada principal", jdbc.queryForObject(
                "SELECT display_name FROM vision_cajon WHERE cajon_id = ?", String.class, cajonA));

        servicio.actualizarNombreCajon(cajonA, " \t ");
        assertNull(estado(cajonA).displayName());
        servicio.actualizarNombreCajon(cajonA, "Otro nombre");
        servicio.actualizarNombreCajon(cajonA, null);
        assertNull(estado(cajonA).displayName());
        assertEquals(ocupacionAntes, jdbc.queryForMap("SELECT * FROM vision_ocupacion WHERE cajon_id = ?", cajonA));
        assertThrows(ErrorConfiguracion.class, () -> servicio.actualizarNombreCajon(UUID.randomUUID(), "Ajeno"));
    }

    @Test
    void cambioDeNombreSoloNotificaDespuesDelCommitYEsVisibleEnOtraConexion() throws Exception {
        reloj.poner(INICIO.plusSeconds(2));
        servicio.observar(observacion(sesion, 1, UUID.randomUUID(), 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "OCUPADO"), new ZonaObservacion(zonaB, "LIBRE")));
        EstadoCajon anterior = estado(cajonA);
        int antes = invalidaciones.get();
        TransactionTemplate transaccion = new TransactionTemplate(contexto.getBean(PlatformTransactionManager.class));
        String consulta = "SELECT display_name FROM vision_cajon WHERE cajon_id = ?";

        try (Connection conexion = contexto.getBean(DataSource.class).getConnection()) {
            conexion.setTransactionIsolation(Connection.TRANSACTION_READ_COMMITTED);
            assertTrue(conexion.getAutoCommit());
            JdbcTemplate observador = new JdbcTemplate(new SingleConnectionDataSource(conexion, true));
            transaccion.executeWithoutResult(estado -> {
                servicio.actualizarNombreCajon(cajonA, "Entrada principal");
                assertNull(observador.queryForObject(consulta, String.class, cajonA));
                assertEquals(antes, invalidaciones.get());
                estado.setRollbackOnly();
            });
            assertNull(observador.queryForObject(consulta, String.class, cajonA));
            assertEquals(antes, invalidaciones.get());

            transaccion.executeWithoutResult(estado -> {
                servicio.actualizarNombreCajon(cajonA, "Entrada principal");
                assertNull(observador.queryForObject(consulta, String.class, cajonA));
                assertEquals(antes, invalidaciones.get());
            });
            assertEquals("Entrada principal", observador.queryForObject(consulta, String.class, cajonA));
            assertEquals(antes + 1, invalidaciones.get());
            EstadoCajon posterior = estado(cajonA);
            assertEquals(anterior.cajonId(), posterior.cajonId());
            assertEquals(anterior.etiqueta(), posterior.etiqueta());
            assertEquals(anterior.estado(), posterior.estado());
            assertEquals(anterior.ultimoEstadoConfirmado(), posterior.ultimoEstadoConfirmado());
            assertEquals(anterior.observadoEn(), posterior.observadoEn());
            assertThrows(ErrorConfiguracion.class, () -> servicio.actualizarNombreCajon(UUID.randomUUID(), "Ajeno"));
            assertEquals(antes + 1, invalidaciones.get());
        }
    }

    @Test
    void nombreNoSeActualizaSiLaDesactivacionConcurrenteConfirmaPrimero() throws Exception {
        CountDownLatch bloqueada = new CountDownLatch(1);
        CountDownLatch liberar = new CountDownLatch(1);
        CountDownLatch iniciada = new CountDownLatch(1);
        TransactionTemplate transaccion = new TransactionTemplate(contexto.getBean(PlatformTransactionManager.class));
        try (ExecutorService ejecutor = Executors.newFixedThreadPool(2)) {
            try {
                Future<?> activacion = ejecutor.submit(() -> transaccion.executeWithoutResult(estado -> {
                    servicio.activarCalibracion(fuente,
                            calibracion(2L, HASH, new ZonaConfiguracion(zonaB, "C2", cajonB)));
                    bloqueada.countDown();
                    try {
                        if (!liberar.await(5, TimeUnit.SECONDS)) {
                            throw new IllegalStateException("No se liberó la calibración sintética.");
                        }
                    } catch (InterruptedException excepcion) {
                        Thread.currentThread().interrupt();
                        throw new IllegalStateException(excepcion);
                    }
                }));
                assertTrue(bloqueada.await(5, TimeUnit.SECONDS));
                Future<?> guardado = ejecutor.submit(() -> {
                    iniciada.countDown();
                    servicio.actualizarNombreCajon(cajonA, "No debe guardarse");
                });
                assertTrue(iniciada.await(5, TimeUnit.SECONDS));
                assertThrows(TimeoutException.class, () -> guardado.get(200, TimeUnit.MILLISECONDS));
                liberar.countDown();
                activacion.get(5, TimeUnit.SECONDS);
                ExecutionException rechazado = assertThrows(ExecutionException.class,
                        () -> guardado.get(5, TimeUnit.SECONDS));
                assertTrue(rechazado.getCause() instanceof ErrorConfiguracion);
                assertNull(jdbc.queryForObject(
                        "SELECT display_name FROM vision_cajon WHERE cajon_id = ?", String.class, cajonA));
                assertFalse(jdbc.queryForObject(
                        "SELECT activa FROM vision_zona WHERE fuente_id = ? AND vision_zone_id = ?",
                        Boolean.class, fuente, zonaA));
            } finally {
                liberar.countDown();
            }
        }
    }

    @Test
    void snapshotCompletoAgregaActualizaYDesactivaMasDeOchoConservandoIdsYOcupacion() {
        UUID fuenteDoce = UUID.randomUUID();
        reloj.poner(INICIO.plusSeconds(2));
        servicio.registrarFuente(new SolicitudFuente(fuenteDoce));
        List<ZonaConfiguracion> iniciales = new ArrayList<>();
        for (int numero = 1; numero <= 12; numero++) {
            iniciales.add(new ZonaConfiguracion(UUID.randomUUID(), "C" + numero, null));
        }
        RespuestaCalibracion primera = servicio.activarCalibracion(fuenteDoce,
                new SolicitudCalibracion(iniciales));
        assertEquals(12, primera.zonas().size());
        List<UUID> cajonesIniciales = primera.zonas().stream().map(ZonaConfiguracion::cajonId).toList();

        reloj.poner(INICIO.plusSeconds(3));
        UUID sesionPrimera = servicio.abrirSesion(new SolicitudSesion(fuenteDoce, UUID.randomUUID(), reloj.instant()))
                .sesionId();
        List<ZonaObservacion> ocupaciones = primera.zonas().stream()
                .map(zona -> new ZonaObservacion(zona.visionZoneId(), "OCUPADO")).toList();
        reloj.poner(INICIO.plusSeconds(4));
        assertTrue(servicio.observar(new SolicitudObservacion(fuenteDoce, sesionPrimera, 1L,
                UUID.randomUUID(), reloj.instant(), ocupaciones)).aceptada());
        UUID cajonRetirado = cajonesIniciales.get(9);
        servicio.actualizarNombreCajon(cajonRetirado, "Nombre conservado");
        var ocupacionRetirada = jdbc.queryForMap(
                "SELECT * FROM vision_ocupacion WHERE cajon_id = ?", cajonRetirado);

        List<ZonaConfiguracion> siguienteSnapshot = new ArrayList<>();
        for (int indice = 0; indice < 9; indice++) {
            ZonaConfiguracion anterior = primera.zonas().get(indice);
            String etiqueta = indice == 0 ? "C1 editado" : anterior.etiqueta();
            siguienteSnapshot.add(new ZonaConfiguracion(anterior.visionZoneId(), etiqueta, anterior.cajonId()));
        }
        for (int numero = 13; numero <= 15; numero++) {
            siguienteSnapshot.add(new ZonaConfiguracion(UUID.randomUUID(), "C" + numero, null));
        }
        reloj.poner(INICIO.plusSeconds(5));
        RespuestaCalibracion segunda = servicio.activarCalibracion(fuenteDoce,
                new SolicitudCalibracion(siguienteSnapshot));
        assertEquals(12, segunda.zonas().size());
        for (int indice = 0; indice < 9; indice++) {
            assertEquals(cajonesIniciales.get(indice), segunda.zonas().get(indice).cajonId());
        }
        for (int indice = 9; indice < 12; indice++) {
            UUID zonaOmitida = primera.zonas().get(indice).visionZoneId();
            UUID cajonOmitido = cajonesIniciales.get(indice);
            assertFalse(jdbc.queryForObject(
                    "SELECT activa FROM vision_zona WHERE fuente_id = ? AND vision_zone_id = ?",
                    Boolean.class, fuenteDoce, zonaOmitida));
            assertEquals("OCUPADO", jdbc.queryForObject(
                    "SELECT ultimo_estado FROM vision_ocupacion WHERE cajon_id = ?", String.class, cajonOmitido));
            assertEquals(INICIO.plusSeconds(4), jdbc.queryForObject(
                    "SELECT observado_en FROM vision_ocupacion WHERE cajon_id = ?", java.sql.Timestamp.class,
                    cajonOmitido).toInstant());
        }
        assertEquals(12L, jdbc.queryForObject(
                "SELECT count(*) FROM vision_ocupacion WHERE fuente_id = ?", Long.class, fuenteDoce));
        List<EstadoCajon> activos = servicio.consultarCajones();
        Set<UUID> cajonesEsperados = segunda.zonas().stream().map(ZonaConfiguracion::cajonId)
                .collect(java.util.stream.Collectors.toSet());
        Set<UUID> cajonesLeidos = activos.stream().map(EstadoCajon::cajonId)
                .filter(cajonesEsperados::contains).collect(java.util.stream.Collectors.toSet());
        assertEquals(cajonesEsperados, cajonesLeidos);
        assertTrue(activos.stream().noneMatch(cajon -> cajonesIniciales.subList(9, 12).contains(cajon.cajonId())));
        assertThrows(ErrorConfiguracion.class,
                () -> servicio.actualizarNombreCajon(cajonRetirado, "No debe guardarse"));
        assertEquals("Nombre conservado", jdbc.queryForObject(
                "SELECT display_name FROM vision_cajon WHERE cajon_id = ?", String.class, cajonRetirado));
        assertEquals(ocupacionRetirada, jdbc.queryForMap(
                "SELECT * FROM vision_ocupacion WHERE cajon_id = ?", cajonRetirado));
        assertEquals(12L, jdbc.queryForObject(
                "SELECT count(*) FROM vision_zona WHERE fuente_id = ? AND activa", Long.class, fuenteDoce));
    }

    @Test
    void clavesForaneasProtegenIdentidadExistenteDelEstacionamiento() {
        UUID identidad = jdbc.queryForObject("SELECT estacionamiento_id FROM configuracion_estacionamiento WHERE id = 1",
                UUID.class);
        assertThrows(DataIntegrityViolationException.class, () -> jdbc.update(
                "UPDATE configuracion_estacionamiento SET estacionamiento_id = ? WHERE id = 1", UUID.randomUUID()));
        assertEquals(identidad, jdbc.queryForObject(
                "SELECT estacionamiento_id FROM configuracion_estacionamiento WHERE id = 1", UUID.class));
    }

    @Test
    void validaSnapshotOrdenRelojYConflictosDeIdempotencia() {
        reloj.poner(INICIO.plusSeconds(5));
        UUID id = UUID.randomUUID();
        SolicitudObservacion valida = observacion(sesion, 1, id, 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "LIBRE"), new ZonaObservacion(zonaB, "OCUPADO"));
        servicio.observar(valida);
        assertTrue(servicio.observar(observacion(sesion, 1, id, 1, HASH, reloj.instant().plusNanos(1),
                new ZonaObservacion(zonaA, "LIBRE"), new ZonaObservacion(zonaB, "OCUPADO"))).aceptada());
        assertTrue(servicio.observar(observacion(sesion, 2, id, 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "OCUPADO"), new ZonaObservacion(zonaB, "OCUPADO"))).aceptada());
        assertThrows(ErrorConfiguracion.class, () -> servicio.observar(observacion(sesion, 2, UUID.randomUUID(),
                1, HASH, reloj.instant().minusSeconds(16), new ZonaObservacion(zonaA, "LIBRE"),
                new ZonaObservacion(zonaB, "OCUPADO"))));
        assertThrows(ErrorConfiguracion.class, () -> servicio.observar(observacion(sesion, 2, UUID.randomUUID(),
                1, HASH, reloj.instant().plusSeconds(4), new ZonaObservacion(zonaA, "LIBRE"),
                new ZonaObservacion(zonaB, "OCUPADO"))));
        assertThrows(ErrorConfiguracion.class, () -> servicio.observar(observacion(sesion, 2, UUID.randomUUID(),
                2, HASH, reloj.instant().plusSeconds(1), new ZonaObservacion(zonaA, "LIBRE"),
                new ZonaObservacion(zonaB, "OCUPADO"))));
        assertThrows(ErrorConfiguracion.class, () -> servicio.observar(observacion(sesion, 2, UUID.randomUUID(),
                1, HASH, reloj.instant().plusSeconds(1), new ZonaObservacion(zonaA, "LIBRE"))));
        assertThrows(ErrorConfiguracion.class, () -> servicio.observar(observacion(sesion, 2, UUID.randomUUID(),
                1, HASH, reloj.instant().plusSeconds(1), new ZonaObservacion(zonaA, "LIBRE"),
                new ZonaObservacion(zonaA, "OCUPADO"))));
        assertThrows(ErrorConfiguracion.class, () -> servicio.observar(observacion(sesion, 2, UUID.randomUUID(),
                1, HASH, reloj.instant().plusSeconds(1), new ZonaObservacion(zonaA, "LIBRE"),
                new ZonaObservacion(UUID.randomUUID(), "OCUPADO"))));
        assertThrows(ErrorConfiguracion.class, () -> servicio.observar(observacion(sesion, 1, UUID.randomUUID(),
                1, HASH, reloj.instant().plusSeconds(1), new ZonaObservacion(zonaA, "LIBRE"),
                new ZonaObservacion(zonaB, "OCUPADO"))));
        assertEquals("LIBRE", estado(cajonA).estado());
        assertEquals(1L, jdbc.queryForObject("SELECT ultima_secuencia FROM vision_fuente WHERE fuente_id = ?",
                Long.class, fuente));
    }

    @Test
    void edicionConservaIdentidadYZonaRecreadaRecibeIdentidadNueva() {
        reloj.poner(INICIO.plusSeconds(4));
        UUID zonaNueva = UUID.randomUUID();
        RespuestaCalibracion nueva = servicio.activarCalibracion(fuente, calibracion(2L, "b".repeat(64),
                new ZonaConfiguracion(zonaA, "C1 editado", null),
                new ZonaConfiguracion(zonaNueva, "C2", null)));
        assertEquals(cajonA, nueva.zonas().get(0).cajonId());
        assertNotEquals(cajonB, nueva.zonas().get(1).cajonId());
        assertThrows(ErrorConfiguracion.class, () -> servicio.observar(observacion(sesion, 1, UUID.randomUUID(),
                1, HASH, reloj.instant(), new ZonaObservacion(zonaA, "LIBRE"),
                new ZonaObservacion(zonaB, "OCUPADO"))));
        assertThrows(ErrorConfiguracion.class, () -> servicio.activarCalibracion(fuente,
                calibracion(3L, HASH, new ZonaConfiguracion(zonaB, "C2", null))));
        RespuestaCalibracion restaurada = servicio.activarCalibracion(fuente,
                calibracion(3L, HASH, new ZonaConfiguracion(zonaB, "C2", cajonB)));
        assertEquals(cajonB, restaurada.zonas().get(0).cajonId());
    }

    @Test
    void aperturasConcurrentesRetienenLaQueTieneInicioMasReciente() throws Exception {
        reloj.poner(INICIO.plusSeconds(10));
        SolicitudSesion anterior = new SolicitudSesion(fuente, UUID.randomUUID(), INICIO.plusSeconds(8));
        SolicitudSesion posterior = new SolicitudSesion(fuente, UUID.randomUUID(), INICIO.plusSeconds(9));
        CountDownLatch inicio = new CountDownLatch(1);
        try (ExecutorService ejecutor = Executors.newFixedThreadPool(2)) {
            Future<?> a = ejecutor.submit(() -> abrirConcurrente(inicio, anterior));
            Future<?> b = ejecutor.submit(() -> abrirConcurrente(inicio, posterior));
            inicio.countDown();
            a.get();
            b.get();
        }
        UUID activa = servicio.abrirSesion(posterior).sesionId();
        assertEquals(activa, jdbc.queryForObject("SELECT sesion_id FROM vision_fuente WHERE fuente_id = ?",
                UUID.class, fuente));
        assertThrows(ErrorConfiguracion.class, () -> servicio.abrirSesion(anterior));
    }

    @Test
    void retencionProtegeReplaysEnVentanaYEvitaRenovarUnReplayPurgado() {
        reloj.poner(INICIO.plusSeconds(2));
        UUID solicitudId = UUID.randomUUID();
        SolicitudObservacion primera = observacion(sesion, 1, solicitudId, 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "LIBRE"), new ZonaObservacion(zonaB, "OCUPADO"));
        servicio.observar(primera);
        Instant confirmado = estado(cajonA).observadoEn();
        reloj.poner(INICIO.plusSeconds(30));
        assertTrue(servicio.observar(primera).aceptada());
        assertThrows(ErrorConfiguracion.class, () -> servicio.observar(observacion(sesion, 1, solicitudId,
                1, HASH, primera.observadoEn(), new ZonaObservacion(zonaA, "OCUPADO"),
                new ZonaObservacion(zonaB, "OCUPADO"))));
        assertEquals(confirmado, estado(cajonA).observadoEn());

        reloj.poner(INICIO.plusSeconds(48));
        assertEquals(1, servicio.limpiarRecibos(fuente));
        assertEquals(1L, contarRecibos()); // Solo permanece la apertura de la sesión activa.
        assertEquals(sesion, servicio.abrirSesion(apertura).sesionId());
        assertThrows(ErrorConfiguracion.class, () -> servicio.observar(primera));
        assertEquals(confirmado, estado(cajonA).observadoEn());
        assertEquals("NO_VERIFICABLE", estado(cajonA).estado());

        // Tras la ventana no se conserva la historia de un ID, pero sí el cursor de secuencia.
        SolicitudObservacion reutilizada = observacion(sesion, 2, solicitudId, 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "OCUPADO"), new ZonaObservacion(zonaB, "LIBRE"));
        assertTrue(servicio.observar(reutilizada).aceptada());
        assertEquals("OCUPADO", estado(cajonA).estado());
        assertThrows(ErrorConfiguracion.class, () -> servicio.observar(primera));
    }

    @Test
    void aperturaActivaSobreviveLaRetencionYLaSustituidaNoSeReactiva() {
        reloj.poner(INICIO.plusSeconds(32));
        servicio.limpiarRecibos(fuente);
        assertEquals(sesion, servicio.abrirSesion(apertura).sesionId());
        assertEquals(1L, contarRecibos());

        reloj.poner(INICIO.plusSeconds(33));
        SolicitudSesion nueva = new SolicitudSesion(fuente, UUID.randomUUID(), reloj.instant());
        UUID nuevaId = servicio.abrirSesion(nueva).sesionId();
        assertNotEquals(sesion, nuevaId);
        assertThrows(ErrorConfiguracion.class, () -> servicio.abrirSesion(apertura));
        reloj.poner(INICIO.plusSeconds(100));
        servicio.limpiarRecibos(fuente);
        assertEquals(1L, contarRecibos());
        assertEquals(nuevaId, servicio.abrirSesion(nueva).sesionId());

        // Una nueva instancia usa el estado durable y no requiere historial en memoria.
        ServicioVision reiniciado = new ServicioVision(jdbc, reloj, 45, 15, 3, 30);
        TransactionTemplate transaccion = new TransactionTemplate(contexto.getBean(PlatformTransactionManager.class));
        assertEquals(nuevaId, transaccion.execute(estado -> reiniciado.abrirSesion(nueva)).sesionId());
        assertThrows(ErrorConfiguracion.class,
                () -> transaccion.execute(estado -> reiniciado.abrirSesion(apertura)));
    }

    @Test
    void replayEnVentanaLimpiaVencidosSinRenovarFechaDeReciboNiObservacion() {
        reloj.poner(INICIO.plusSeconds(2));
        SolicitudObservacion antigua = observacion(sesion, 1, UUID.randomUUID(), 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "LIBRE"), new ZonaObservacion(zonaB, "OCUPADO"));
        servicio.observar(antigua);
        reloj.poner(INICIO.plusSeconds(3));
        SolicitudObservacion actual = observacion(sesion, 2, UUID.randomUUID(), 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "OCUPADO"), new ZonaObservacion(zonaB, "LIBRE"));
        servicio.observar(actual);
        Instant creado = jdbc.queryForObject(
                "SELECT creado_en FROM vision_solicitud WHERE fuente_id = ? AND solicitud_id = ?",
                Timestamp.class, fuente, actual.solicitudId()).toInstant();
        Instant observado = estado(cajonA).observadoEn();
        reloj.poner(INICIO.plusSeconds(33));
        assertTrue(servicio.observar(actual).aceptada());
        assertEquals(creado, jdbc.queryForObject(
                "SELECT creado_en FROM vision_solicitud WHERE fuente_id = ? AND solicitud_id = ?",
                Timestamp.class, fuente, actual.solicitudId()).toInstant());
        assertEquals(observado, estado(cajonA).observadoEn());
        assertEquals(0L, jdbc.queryForObject(
                "SELECT count(*) FROM vision_solicitud WHERE fuente_id = ? AND solicitud_id = ?",
                Long.class, fuente, antigua.solicitudId()));
        assertEquals(2L, contarRecibos());
    }

    @Test
    void cuotaAbsolutaRechazaSinModificarEstadoYPermiteReplay() {
        ServicioVision limitado = new ServicioVision(jdbc, reloj, 45, 15, 3, 30, 2);
        TransactionTemplate transaccion = new TransactionTemplate(contexto.getBean(PlatformTransactionManager.class));
        reloj.poner(INICIO.plusSeconds(2));
        SolicitudObservacion primera = observacion(sesion, 1, UUID.randomUUID(), 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "LIBRE"), new ZonaObservacion(zonaB, "OCUPADO"));
        assertTrue(transaccion.execute(estado -> limitado.observar(primera)).aceptada());
        assertEquals(2L, contarRecibos()); // Cuenta la apertura activa y una observación.
        assertTrue(transaccion.execute(estado -> limitado.observar(primera)).aceptada());

        reloj.poner(INICIO.plusSeconds(3));
        UUID segundoId = UUID.randomUUID();
        SolicitudObservacion segunda = observacion(sesion, 2, segundoId, 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "OCUPADO"), new ZonaObservacion(zonaB, "LIBRE"));
        ErrorConfiguracion llena = assertThrows(ErrorConfiguracion.class,
                () -> transaccion.execute(estado -> limitado.observar(segunda)));
        assertEquals(429, llena.estadoHttp().value());
        assertEquals(1L, jdbc.queryForObject("SELECT ultima_secuencia FROM vision_fuente WHERE fuente_id = ?",
                Long.class, fuente));
        assertEquals("LIBRE", estado(cajonA).estado());
        assertEquals(2L, contarRecibos());
        assertEquals(0L, jdbc.queryForObject(
                "SELECT count(*) FROM vision_solicitud WHERE fuente_id = ? AND solicitud_id = ?",
                Long.class, fuente, segundoId));

        SolicitudSesion siguiente = new SolicitudSesion(fuente, UUID.randomUUID(), reloj.instant());
        ErrorConfiguracion sesionLlena = assertThrows(ErrorConfiguracion.class,
                () -> transaccion.execute(estado -> limitado.abrirSesion(siguiente)));
        assertEquals(429, sesionLlena.estadoHttp().value());
        assertEquals(sesion, servicio.abrirSesion(apertura).sesionId());

        reloj.poner(INICIO.plusSeconds(33));
        assertEquals(1, servicio.limpiarRecibos(fuente));
        SolicitudObservacion posterior = observacion(sesion, 2, segundoId, 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "OCUPADO"), new ZonaObservacion(zonaB, "LIBRE"));
        assertTrue(transaccion.execute(estado -> limitado.observar(posterior)).aceptada());
        assertEquals("OCUPADO", estado(cajonA).estado());
        assertEquals(2L, contarRecibos());
    }

    @Test
    void ingestionSostenidaMantieneCotaPorTiempoYLimpiaLaFuenteInactiva() {
        for (int numero = 1; numero <= 150; numero++) {
            reloj.poner(INICIO.plusSeconds(numero + 1L));
            servicio.observar(observacion(sesion, numero, UUID.randomUUID(), 1, HASH, reloj.instant(),
                    new ZonaObservacion(zonaA, numero % 2 == 0 ? "LIBRE" : "OCUPADO"),
                    new ZonaObservacion(zonaB, "LIBRE")));
            assertTrue(contarRecibos() <= 32, "La purga oportunista debe acotar los recibos por tiempo.");
        }
        assertEquals(150L, jdbc.queryForObject("SELECT ultima_secuencia FROM vision_fuente WHERE fuente_id = ?",
                Long.class, fuente));
        reloj.poner(INICIO.plusSeconds(182));
        MantenimientoRecibosVision mantenimiento = new MantenimientoRecibosVision(jdbc, servicio, 1000);
        int fuentes = jdbc.queryForObject("SELECT count(*) FROM vision_fuente", Integer.class);
        int maximoCiclos = (fuentes + 15) / 16 + 1;
        for (int ciclo = 0; ciclo < maximoCiclos && contarRecibos() > 1; ciclo++) {
            mantenimiento.limpiarPeriodicamente();
        }
        assertEquals(1L, contarRecibos());
        assertEquals(sesion, servicio.abrirSesion(apertura).sesionId());
    }

    @Test
    void limpiezaConcurrenteRespetaElBloqueoYLaIngestionAvanza() throws Exception {
        reloj.poner(INICIO.plusSeconds(2));
        SolicitudObservacion anterior = observacion(sesion, 1, UUID.randomUUID(), 1, HASH, reloj.instant(),
                new ZonaObservacion(zonaA, "LIBRE"), new ZonaObservacion(zonaB, "OCUPADO"));
        servicio.observar(anterior);
        reloj.poner(INICIO.plusSeconds(33));
        DataSource datos = contexto.getBean(DataSource.class);
        try (Connection bloqueo = datos.getConnection(); ExecutorService ejecutor = Executors.newFixedThreadPool(3)) {
            bloqueo.setAutoCommit(false);
            try (PreparedStatement consulta = bloqueo.prepareStatement(
                    "SELECT fuente_id FROM vision_fuente WHERE fuente_id = ? FOR UPDATE")) {
                consulta.setObject(1, fuente);
                consulta.executeQuery().close();
            }
            Future<Integer> omitida = ejecutor.submit(() -> servicio.limpiarRecibos(fuente));
            assertEquals(0, omitida.get(2, TimeUnit.SECONDS));
            assertEquals(2L, contarRecibos());
            bloqueo.commit();

            SolicitudObservacion nueva = observacion(sesion, 2, UUID.randomUUID(), 1, HASH, reloj.instant(),
                    new ZonaObservacion(zonaA, "OCUPADO"), new ZonaObservacion(zonaB, "LIBRE"));
            CountDownLatch inicio = new CountDownLatch(1);
            Future<RespuestaObservacion> primera = ejecutor.submit(() -> { inicio.await(); return servicio.observar(nueva); });
            Future<RespuestaObservacion> duplicada = ejecutor.submit(() -> { inicio.await(); return servicio.observar(nueva); });
            Future<Integer> limpieza = ejecutor.submit(() -> { inicio.await(); return servicio.limpiarRecibos(fuente); });
            inicio.countDown();
            assertTrue(primera.get(5, TimeUnit.SECONDS).aceptada());
            assertTrue(duplicada.get(5, TimeUnit.SECONDS).aceptada());
            assertTrue(limpieza.get(5, TimeUnit.SECONDS) >= 0);
            assertEquals(2L, jdbc.queryForObject("SELECT ultima_secuencia FROM vision_fuente WHERE fuente_id = ?",
                    Long.class, fuente));
            assertEquals("OCUPADO", estado(cajonA).estado());
            assertEquals(1L, jdbc.queryForObject(
                    "SELECT count(*) FROM vision_solicitud WHERE fuente_id = ? AND solicitud_id = ?",
                    Long.class, fuente, nueva.solicitudId()));
        }
    }

    @Test
    void mantenimientoLimitaElCicloYAvanzaPorMasDeDieciseisFuentes() {
        List<UUID> fuentes = new ArrayList<>();
        for (int numero = 0; numero < 20; numero++) {
            reloj.poner(INICIO);
            UUID otraFuente = UUID.randomUUID();
            UUID otraZona = UUID.randomUUID();
            servicio.registrarFuente(new SolicitudFuente(otraFuente));
            servicio.activarCalibracion(otraFuente, calibracion(1L, HASH,
                    new ZonaConfiguracion(otraZona, "C" + numero, null)));
            reloj.poner(INICIO.plusSeconds(1));
            UUID otraSesion = servicio.abrirSesion(new SolicitudSesion(otraFuente, UUID.randomUUID(),
                    reloj.instant())).sesionId();
            reloj.poner(INICIO.plusSeconds(2));
            servicio.observar(new SolicitudObservacion(otraFuente, otraSesion, 1L, UUID.randomUUID(),
                    reloj.instant(), List.of(new ZonaObservacion(otraZona, "OCUPADO"))));
            fuentes.add(otraFuente);
        }
        reloj.poner(INICIO.plusSeconds(33));
        MantenimientoRecibosVision mantenimiento = new MantenimientoRecibosVision(jdbc, servicio, 1000);
        mantenimiento.limpiarPeriodicamente();
        long restantes = fuentes.stream().mapToLong(id -> jdbc.queryForObject(
                "SELECT count(*) FROM vision_solicitud WHERE fuente_id = ?", Long.class, id)).sum();
        assertTrue(restantes >= 24, "Un ciclo no debe limpiar más de 16 fuentes.");
        int cantidadFuentes = jdbc.queryForObject("SELECT count(*) FROM vision_fuente", Integer.class);
        int maximoCiclos = (cantidadFuentes + 15) / 16 + 1;
        for (int ciclo = 1; ciclo < maximoCiclos; ciclo++) {
            mantenimiento.limpiarPeriodicamente();
        }
        for (UUID id : fuentes) {
            assertEquals(1L, jdbc.queryForObject(
                    "SELECT count(*) FROM vision_solicitud WHERE fuente_id = ?", Long.class, id));
        }
    }

    private long contarRecibos() {
        return jdbc.queryForObject("SELECT count(*) FROM vision_solicitud WHERE fuente_id = ?", Long.class, fuente);
    }

    private static void abrirConcurrente(CountDownLatch inicio, SolicitudSesion solicitud) {
        try {
            inicio.await();
            servicio.abrirSesion(solicitud);
        } catch (ErrorConfiguracion conflictoEsperado) {
            assertEquals(409, conflictoEsperado.estadoHttp().value());
        } catch (InterruptedException interrumpida) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(interrumpida);
        }
    }

    private EstadoCajon estado(UUID cajonId) {
        return servicio.consultarCajones().stream().filter(cajon -> cajon.cajonId().equals(cajonId))
                .findFirst().orElseThrow();
    }

    private static SolicitudCalibracion calibracion(long revisionLegada, String hashLegado,
            ZonaConfiguracion... zonas) {
        return new SolicitudCalibracion(List.of(zonas));
    }

    private SolicitudObservacion observacion(UUID sesionId, long secuencia, UUID solicitudId,
            long revisionLegada, String hashLegado, Instant observado, ZonaObservacion... zonas) {
        return new SolicitudObservacion(fuente, sesionId, secuencia, solicitudId, observado, List.of(zonas));
    }

    @Configuration
    @EnableTransactionManagement
    static class Transacciones { }

    private static final class RelojMutable extends Clock {
        private final AtomicReference<Instant> actual;
        private RelojMutable(Instant instante) { actual = new AtomicReference<>(instante); }
        private void poner(Instant instante) { actual.set(instante); }
        @Override public ZoneId getZone() { return ZoneOffset.UTC; }
        @Override public Clock withZone(ZoneId zona) { return this; }
        @Override public Instant instant() { return actual.get(); }
    }
}
