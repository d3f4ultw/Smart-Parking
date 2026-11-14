package mx.smartparking.api.rfid2.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.sql.Connection;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import javax.sql.DataSource;
import com.zaxxer.hikari.HikariDataSource;
import mx.smartparking.api.persistencia.RepositorioConfiguracionJdbc;
import mx.smartparking.api.rfid1.persistencia.RepositorioTarjetasRfidJdbc;
import mx.smartparking.api.rfid2.controlador.ManejadorErroresDispositivoRfid2;
import mx.smartparking.api.rfid2.PlazoEntradaRfid2;
import mx.smartparking.api.rfid2.persistencia.RepositorioRfid2Jdbc;
import mx.smartparking.api.rfid2.persistencia.ResultadoEntradaRfid2;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;

/** Verifica cancelación y plazos de entrada contra PostgreSQL desechable. */
class ConcurrenciaRfid2PostgresTest {
    private static DataSource origen;
    private static JdbcTemplate jdbc;
    private static DataSourceTransactionManager administrador;

    @BeforeAll
    static void preparar() {
        origen = HorarioRfid2PostgresTest.baseDescartable(
                "rfid2_seguridad_" + UUID.randomUUID().toString().replace("-", ""));
        jdbc = new JdbcTemplate(origen);
        administrador = new DataSourceTransactionManager(origen);
        UUID dueno = UUID.randomUUID();
        UUID estacionamiento = UUID.randomUUID();
        UUID fuente = UUID.randomUUID();
        jdbc.update("""
                INSERT INTO cuenta (id, nombres, primer_apellido, correo, correo_normalizado, rol,
                    estado, hash_contrasena_acceso, revision_acceso, creada_en, actualizada_en)
                VALUES (?, 'Sintetico', 'Prueba', ?, ?, 'DUENO', 'ACTIVA', 'hash-sintetico', 1, now(), now())
                """, dueno, dueno + "@example.invalid", dueno + "@example.invalid");
        jdbc.update("""
                UPDATE configuracion_estacionamiento
                SET estado = 'CONFIGURADA', revision = 1, revision_propietario = 1,
                    estacionamiento_id = ?, dueno_cuenta_id = ?, hash_contrasena_administrativa = 'hash-sintetico',
                    nombre_estacionamiento = 'Prueba', tipo_estacionamiento = 'MIXTO',
                    modo_horario = 'CONTINUO_24_7', zona_horaria = 'America/Mexico_City'
                WHERE id = 1
                """, estacionamiento, dueno);
        jdbc.update("INSERT INTO vision_fuente (fuente_id, estacionamiento_id) VALUES (?, ?)", fuente, estacionamiento);
        for (int numero = 0; numero < 20; numero++) {
            UUID cajon = UUID.randomUUID();
            jdbc.update("INSERT INTO vision_cajon (cajon_id, estacionamiento_id, etiqueta) VALUES (?, ?, ?)",
                    cajon, estacionamiento, "C" + numero);
            jdbc.update("INSERT INTO vision_zona (fuente_id, vision_zone_id, cajon_id) VALUES (?, ?, ?)",
                    fuente, UUID.randomUUID(), cajon);
        }
    }

    @Test
    void entradaYCancelacionCompartenOrdenDeBloqueosParaAmbosTipos() throws Exception {
        for (String tipo : List.of("EMPLEADO", "CLIENTE")) {
            comprobarCarrera(persona(tipo), true);
            comprobarCarrera(persona(tipo), false);
        }
    }

    @Test
    void losBloqueosProlongadosAgotanElPlazoSinRegistrarEntrada() throws Exception {
        for (String bloqueo : List.of("ADVISORY", "CONFIGURACION", "ASOCIACION")) {
            comprobarTimeout(persona("EMPLEADO"), bloqueo);
        }
    }

    @Test
    void conexionNoDisponibleDuranteMasDeTresSegundosNoConfirmaEntradaTardia() throws Exception {
        Persona persona = persona("EMPLEADO");
        UUID lectura = UUID.randomUUID();
        DriverManagerDataSource fuente = (DriverManagerDataSource) origen;
        ExecutorService hilos = Executors.newSingleThreadExecutor();
        try (HikariDataSource pool = new HikariDataSource()) {
            pool.setJdbcUrl(fuente.getUrl());
            pool.setUsername(fuente.getUsername());
            pool.setPassword(fuente.getPassword());
            pool.setMaximumPoolSize(1);
            pool.setConnectionTimeout(5000);
            RepositorioRfid2Jdbc repo = new RepositorioRfid2Jdbc(
                    new JdbcTemplate(pool), new DataSourceTransactionManager(pool));
            CountDownLatch iniciada = new CountDownLatch(1);
            Future<?> resultado;
            try (Connection retenida = pool.getConnection()) {
                resultado = hilos.submit(() -> {
                    iniciada.countDown();
                    return entrada(repo, persona, lectura);
                });
                assertTrue(iniciada.await(2, TimeUnit.SECONDS));
                Thread.sleep(3200);
                assertFalse(resultado.isDone());
            }
            ExecutionException error = assertThrows(ExecutionException.class,
                    () -> resultado.get(3, TimeUnit.SECONDS));
            assertInstanceOf(DataAccessResourceFailureException.class, error.getCause());
            assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM movimiento_estacionamiento WHERE lectura_id = ?",
                    Integer.class, lectura));
            assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM evento_acceso WHERE lectura_id = ?",
                    Integer.class, lectura));
        } finally {
            hilos.shutdownNow();
            assertTrue(hilos.awaitTermination(5, TimeUnit.SECONDS));
        }
    }

    @Test
    void lecturaBloqueadaDeConfiguracionNoConfirmaEntradaTardia() throws Exception {
        Persona persona = persona("EMPLEADO");
        UUID lectura = UUID.randomUUID();
        CountDownLatch tablaBloqueada = new CountDownLatch(1);
        CountDownLatch liberar = new CountDownLatch(1);
        ExecutorService hilos = Executors.newFixedThreadPool(2);
        try {
            Future<?> bloqueo = hilos.submit(() -> new TransactionTemplate(administrador).execute(estado -> {
                jdbc.execute("LOCK TABLE configuracion_estacionamiento IN ACCESS EXCLUSIVE MODE");
                tablaBloqueada.countDown();
                esperar(liberar, 8);
                return null;
            }));
            assertTrue(tablaBloqueada.await(3, TimeUnit.SECONDS));
            ServicioRfid2 servicio = new ServicioRfid2(new RepositorioRfid2Jdbc(jdbc, administrador),
                    new RepositorioConfiguracionJdbc(jdbc));
            Future<?> resultado = hilos.submit(() -> servicio.registrarEntrada(persona.uid(), lectura.toString()));
            esperarBloqueo();
            Thread.sleep(3200);
            assertFalse(resultado.isDone());
            liberar.countDown();
            bloqueo.get(3, TimeUnit.SECONDS);
            ExecutionException error = assertThrows(ExecutionException.class,
                    () -> resultado.get(3, TimeUnit.SECONDS));
            assertInstanceOf(DataAccessResourceFailureException.class, error.getCause());
            assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM movimiento_estacionamiento WHERE lectura_id = ?",
                    Integer.class, lectura));
            assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM evento_acceso WHERE lectura_id = ?",
                    Integer.class, lectura));
        } finally {
            liberar.countDown();
            hilos.shutdownNow();
            assertTrue(hilos.awaitTermination(5, TimeUnit.SECONDS));
        }
    }

    private static void comprobarCarrera(Persona persona, boolean entradaPrimero) throws Exception {
        CountDownLatch padreBloqueado = new CountDownLatch(1);
        CountDownLatch continuar = new CountDownLatch(1);
        JdbcTemplate pausado = new JdbcTemplateConPausa(origen, padreBloqueado, continuar);
        RepositorioRfid2Jdbc entradaPausada = new RepositorioRfid2Jdbc(pausado, administrador);
        RepositorioRfid2Jdbc entradaNormal = new RepositorioRfid2Jdbc(jdbc, administrador);
        RepositorioTarjetasRfidJdbc cancelacionPausada = new RepositorioTarjetasRfidJdbc(pausado);
        RepositorioTarjetasRfidJdbc cancelacionNormal = new RepositorioTarjetasRfidJdbc(jdbc);
        ExecutorService hilos = Executors.newFixedThreadPool(2);
        try {
            UUID lectura = UUID.randomUUID();
            Future<?> primero = hilos.submit(() -> {
                if (entradaPrimero) {
                    return entrada(entradaPausada, persona, lectura);
                }
                return new TransactionTemplate(administrador).execute(estado ->
                        cancelacionPausada.cancelarTarjeta(persona.asociacionId(), Instant.now()));
            });
            assertTrue(padreBloqueado.await(3, TimeUnit.SECONDS));
            Future<?> segundo = hilos.submit(() -> {
                if (entradaPrimero) {
                    return new TransactionTemplate(administrador).execute(estado ->
                            cancelacionNormal.cancelarTarjeta(persona.asociacionId(), Instant.now()));
                }
                return entrada(entradaNormal, persona, lectura);
            });
            esperarBloqueo();
            assertFalse(segundo.isDone());
            continuar.countDown();
            Object resultadoPrimero = primero.get(3, TimeUnit.SECONDS);
            Object resultadoSegundo = segundo.get(3, TimeUnit.SECONDS);
            ResultadoEntradaRfid2 resultado = (ResultadoEntradaRfid2)
                    (entradaPrimero ? resultadoPrimero : resultadoSegundo);
            assertEquals(entradaPrimero ? "AUTORIZADA" : "DENEGADA", resultado.resultado());
            if (!entradaPrimero) {
                assertEquals("TARJETA_CANCELADA", resultado.motivo());
            }
            assertEquals(entradaPrimero ? 1 : 0, jdbc.queryForObject(
                    "SELECT count(*) FROM movimiento_estacionamiento WHERE lectura_id = ?", Integer.class, lectura));
            assertEquals("CANCELADA", jdbc.queryForObject(
                    "SELECT estado FROM asociacion_tarjeta_rfid1 WHERE asociacion_id = ?",
                    String.class, persona.asociacionId()));
        } finally {
            continuar.countDown();
            hilos.shutdownNow();
            assertTrue(hilos.awaitTermination(5, TimeUnit.SECONDS));
        }
    }

    private static void comprobarTimeout(Persona persona, String tipo) throws Exception {
        UUID lectura = UUID.randomUUID();
        CountDownLatch bloqueado = new CountDownLatch(1);
        CountDownLatch continuar = new CountDownLatch(1);
        ExecutorService hilos = Executors.newSingleThreadExecutor();
        try {
            Future<?> poseedor = hilos.submit(() -> new TransactionTemplate(administrador).execute(estado -> {
                switch (tipo) {
                    case "ADVISORY" -> jdbc.query("SELECT pg_advisory_xact_lock(?, ?)", rs -> null,
                            0x52464932, claveBloqueo(lectura));
                    case "CONFIGURACION" -> jdbc.query("SELECT id FROM configuracion_estacionamiento "
                            + "WHERE id = 1 FOR UPDATE", rs -> null);
                    case "ASOCIACION" -> jdbc.query("SELECT asociacion_id FROM asociacion_tarjeta_rfid1 "
                            + "WHERE asociacion_id = ? FOR UPDATE", rs -> null, persona.asociacionId());
                    default -> throw new IllegalArgumentException();
                }
                bloqueado.countDown();
                esperar(continuar, 5);
                return null;
            }));
            assertTrue(bloqueado.await(3, TimeUnit.SECONDS));
            long inicio = System.nanoTime();
            DataAccessException error = assertThrows(DataAccessException.class, () ->
                    entrada(new RepositorioRfid2Jdbc(jdbc, administrador), persona, lectura));
            long milisegundos = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - inicio);
            assertTrue(milisegundos >= 1000 && milisegundos < 2800, "Plazo medido: " + milisegundos);
            assertEquals(HttpStatus.SERVICE_UNAVAILABLE,
                    new ManejadorErroresDispositivoRfid2().errorPersistencia(error).getStatusCode());
            continuar.countDown();
            poseedor.get(3, TimeUnit.SECONDS);
            assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM movimiento_estacionamiento WHERE lectura_id = ?",
                    Integer.class, lectura));
            assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM evento_acceso WHERE lectura_id = ?",
                    Integer.class, lectura));
        } finally {
            continuar.countDown();
            hilos.shutdownNow();
            assertTrue(hilos.awaitTermination(5, TimeUnit.SECONDS));
        }
    }

    private static void esperarBloqueo() throws InterruptedException {
        for (int intento = 0; intento < 40; intento++) {
            Integer bloqueadas = jdbc.queryForObject("""
                    SELECT count(*) FROM pg_stat_activity
                    WHERE datname = current_database() AND wait_event_type = 'Lock'
                    """, Integer.class);
            if (bloqueadas != null && bloqueadas > 0) {
                return;
            }
            Thread.sleep(20);
        }
        throw new AssertionError("No se observó la espera de bloqueo PostgreSQL.");
    }

    private static ResultadoEntradaRfid2 entrada(RepositorioRfid2Jdbc repo, Persona persona, UUID lectura) {
        return repo.registrarEntrada(persona.uid(), lectura, Clock.systemUTC(), ZoneOffset.UTC,
                hora -> true, 1L, new PlazoEntradaRfid2());
    }

    private static Persona persona(String tipo) {
        Long empleado = null;
        UUID cliente = null;
        if ("EMPLEADO".equals(tipo)) {
            empleado = jdbc.queryForObject("INSERT INTO empleado (nombres, primer_apellido) "
                    + "VALUES ('Sintetico', 'Prueba') RETURNING id", Long.class);
        } else {
            cliente = UUID.randomUUID();
            String correo = cliente + "@example.invalid";
            jdbc.update("""
                    INSERT INTO cuenta (id, nombres, primer_apellido, correo, correo_normalizado,
                        rol, estado, hash_contrasena_acceso, revision_acceso, creada_en, actualizada_en)
                    VALUES (?, 'Sintetico', 'Prueba', ?, ?, 'CLIENTE', 'ACTIVA', 'hash-sintetico', 1, now(), now())
                    """, cliente, correo, correo);
            HorarioRfid2PostgresTest.crearMembresiaSintetica(jdbc, cliente);
        }
        String uid = UUID.randomUUID().toString().replace("-", "").substring(0, 20).toUpperCase(Locale.ROOT);
        Long asociacion = jdbc.queryForObject("""
                INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico, empleado_id, cliente_id)
                VALUES (?, ?, ?) RETURNING asociacion_id
                """, Long.class, uid, empleado, cliente);
        return new Persona(uid, asociacion);
    }

    private static int claveBloqueo(UUID lectura) {
        long superior = lectura.getMostSignificantBits();
        long inferior = lectura.getLeastSignificantBits();
        return (int) (superior >>> 32) ^ (int) superior ^ (int) (inferior >>> 32) ^ (int) inferior;
    }

    private static void esperar(CountDownLatch senal, int segundos) {
        try {
            if (!senal.await(segundos, TimeUnit.SECONDS)) {
                throw new AssertionError("La prueba no recibió la señal esperada.");
            }
        } catch (InterruptedException excepcion) {
            Thread.currentThread().interrupt();
            throw new AssertionError("La prueba fue interrumpida.", excepcion);
        }
    }

    private static final class JdbcTemplateConPausa extends JdbcTemplate {
        private final CountDownLatch bloqueado;
        private final CountDownLatch continuar;

        private JdbcTemplateConPausa(DataSource origen, CountDownLatch bloqueado, CountDownLatch continuar) {
            super(origen);
            this.bloqueado = bloqueado;
            this.continuar = continuar;
        }

        @Override
        public <T> List<T> query(String sql, RowMapper<T> mapper, Object... argumentos) {
            List<T> resultado = super.query(sql, mapper, argumentos);
            if (sql.contains("FOR UPDATE OF codigo, cuenta")
                    || sql.contains("SELECT id FROM empleado WHERE id = ? FOR UPDATE")) {
                bloqueado.countDown();
                esperar(continuar, 2);
            }
            return resultado;
        }
    }

    private record Persona(String uid, long asociacionId) { }
}
