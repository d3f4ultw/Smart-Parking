package mx.smartparking.api.rfid1.persistencia;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.sql.Connection;
import java.sql.DriverManager;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

/** Comprueba las búsquedas contra PostgreSQL descartable con tablas temporales sintéticas. */
@EnabledIfSystemProperty(named = "smartparking.integration.rfid1.busqueda.disposable", matches = "true")
class RepositorioTarjetasRfidJdbcBusquedaPostgresqlTest {
    private static final String BASE = "sp_rfid1_busqueda_prueba";
    private static final String USUARIO = "sp_rfid1_busqueda";
    private static final String URL = "jdbc:postgresql://127.0.0.1:5432/" + BASE;
    private static Connection conexion;
    private static RepositorioTarjetasRfidJdbc repositorio;

    @BeforeAll
    static void prepararDatos() throws Exception {
        String contrasena = System.getenv("RFID1_BUSQUEDA_TEST_PASSWORD");
        if (contrasena == null || contrasena.isBlank()) {
            throw new IllegalStateException("Se requiere la contraseña de PostgreSQL sintético.");
        }
        conexion = DriverManager.getConnection(URL, USUARIO, contrasena);
        JdbcTemplate jdbc = new JdbcTemplate(new SingleConnectionDataSource(conexion, true));
        assertEquals(BASE, jdbc.queryForObject("SELECT current_database()", String.class));
        assertEquals(USUARIO, jdbc.queryForObject("SELECT current_user", String.class));
        jdbc.execute("CREATE TEMP TABLE cuenta (id uuid PRIMARY KEY, nombres text, primer_apellido text, segundo_apellido text)");
        jdbc.execute("CREATE TEMP TABLE cliente_codigo_publico (cliente_id uuid PRIMARY KEY, numero bigint)");
        jdbc.execute("CREATE TEMP TABLE empleado (id bigint PRIMARY KEY, nombres text, primer_apellido text, segundo_apellido text)");
        jdbc.execute("CREATE TEMP TABLE asociacion_tarjeta_rfid1 (asociacion_id bigint PRIMARY KEY, uid_canonico text, "
                + "estado text, asociada_en timestamptz, cancelada_en timestamptz, cliente_id uuid, empleado_id bigint)");

        UUID cliente = UUID.fromString("11111111-1111-4111-8111-111111111111");
        jdbc.update("INSERT INTO cuenta VALUES (?, ?, ?, ?)", cliente, "Valeria", "Ríos", "Mendoza");
        jdbc.update("INSERT INTO cliente_codigo_publico VALUES (?, ?)", cliente, 1L);
        insertarTarjeta(jdbc, 1, "AA11BB22", "ACTIVA", cliente, null);
        insertarTarjeta(jdbc, 2, "AA22BB33", "CANCELADA", cliente, null);
        jdbc.update("INSERT INTO empleado VALUES (?, ?, ?, ?)", 7L, "Ana", "Lopez", null);
        insertarTarjeta(jdbc, 3, "DEADBEEF", "CANCELADA", null, 7L);
        jdbc.update("INSERT INTO empleado VALUES (?, ?, ?, ?)", 10001L, "Lucia", "Prueba", null);
        insertarTarjeta(jdbc, 4, "F1F2F3F4", "ACTIVA", null, 10001L);
        jdbc.update("INSERT INTO empleado VALUES (?, ?, ?, ?)", 8L, "Rosa_100%", "Simbolo!\\Demo", null);
        insertarTarjeta(jdbc, 5, "B1B2B3B4", "ACTIVA", null, 8L);
        for (long id = 100; id < 112; id++) {
            jdbc.update("INSERT INTO empleado VALUES (?, ?, ?, ?)", id, "Equipo", "Prueba", null);
            insertarTarjeta(jdbc, id, String.format(Locale.ROOT, "%08X", id), "ACTIVA", null, id);
        }
        repositorio = new RepositorioTarjetasRfidJdbc(jdbc);
    }

    private static void insertarTarjeta(JdbcTemplate jdbc, long id, String uid, String estado, UUID cliente, Long empleado) {
        Instant instante = Instant.parse("2026-11-09T12:00:00Z");
        jdbc.update("INSERT INTO asociacion_tarjeta_rfid1 VALUES (?, ?, ?, ?, ?, ?, ?)",
                id, uid, estado, java.sql.Timestamp.from(instante), null, cliente, empleado);
    }

    @AfterAll
    static void cerrarConexion() throws Exception {
        if (conexion != null) conexion.close();
    }

    @Test
    void buscaNombreCodigoYUidSinDistinguirMayusculas() {
        assertEquals(2, repositorio.contarTarjetas("MIXTO", "TODAS", "vAlErIa RÍOS"));
        assertEquals(2, repositorio.contarTarjetas("CLIENTE", "TODAS", "cli-0001"));
        assertEquals(1, repositorio.contarTarjetas("EMPLEADO", "ACTIVA", "e-10001"));
        assertEquals(1, repositorio.contarTarjetas("MIXTO", "TODAS", "aa11bb"));
        assertEquals("AA11BB22", repositorio.listarTarjetas("MIXTO", "TODAS", "aa11bb", 0, 10).getFirst().uidCanonico());
    }

    @Test
    void combinaTipoEstadoYBusquedaConElMismoConteoYPagina() {
        var pagina = repositorio.listarTarjetas("EMPLEADO", "CANCELADA", "ana", 0, 10);
        assertEquals(1, repositorio.contarTarjetas("EMPLEADO", "CANCELADA", "ana"));
        assertEquals(1, pagina.size());
        assertEquals("E-0007", pagina.getFirst().codigoPersona());
        assertEquals("CANCELADA", pagina.getFirst().estado());
        assertEquals(0, repositorio.contarTarjetas("CLIENTE", "CANCELADA", "ana"));
    }

    @Test
    void paginaEnOrdenDeterministaCuandoLaFechaEsIgual() {
        List<RepositorioTarjetasRfid.TarjetaRfid1Persistida> primera =
                repositorio.listarTarjetas("MIXTO", "TODAS", "equipo prueba", 0, 10);
        List<RepositorioTarjetasRfid.TarjetaRfid1Persistida> segunda =
                repositorio.listarTarjetas("MIXTO", "TODAS", "equipo prueba", 10, 10);
        assertEquals(12, repositorio.contarTarjetas("MIXTO", "TODAS", "equipo prueba"));
        assertEquals(10, primera.size());
        assertEquals(List.of(111L, 110L, 109L, 108L, 107L, 106L, 105L, 104L, 103L, 102L),
                primera.stream().map(RepositorioTarjetasRfid.TarjetaRfid1Persistida::asociacionId).toList());
        assertEquals(List.of(101L, 100L),
                segunda.stream().map(RepositorioTarjetasRfid.TarjetaRfid1Persistida::asociacionId).toList());
    }

    @Test
    void buscaComodinesYBarraComoCaracteresLiterales() {
        for (String termino : List.of("_", "%", "!", "\\")) {
            assertEquals(1, repositorio.contarTarjetas("MIXTO", "TODAS", termino));
            assertEquals(1, repositorio.listarTarjetas("MIXTO", "TODAS", termino, 0, 10).size());
        }
        assertEquals(0, repositorio.contarTarjetas("MIXTO", "TODAS", "x' OR true --"));
        assertEquals(17, repositorio.contarTarjetas("MIXTO", "TODAS", ""));
    }
}
