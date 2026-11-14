package mx.smartparking.api.accesos;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/** Comprueba V21 a V22 en una base sintética habilitada explícitamente. */
class CapacidadMigracionPostgresTest {

    @Test
    void conservaLasDecisionesYRechazaDenegacionConMotivoNulo() {
        assumeTrue("true".equals(System.getenv("SMARTPARKING_POSTGRES_DESCARTABLE")),
                "La prueba PostgreSQL es opt-in.");
        assertEquals("sp_rfid2_horario_test", System.getenv("POSTGRES_DB"));
        String host = System.getenv("POSTGRES_HOST");
        assertTrue("127.0.0.1".equals(host) || "localhost".equals(host));
        String puerto = System.getenv("POSTGRES_PORT");
        assertNotNull(puerto);
        assertTrue(puerto.matches("[0-9]{1,5}"));
        assertTrue(Integer.parseInt(puerto) > 0 && Integer.parseInt(puerto) <= 65535);
        String usuario = System.getenv("POSTGRES_USER");
        String contrasena = System.getenv("POSTGRES_PASSWORD");
        assertNotNull(usuario);
        assertFalse(usuario.isBlank());
        assertNotNull(contrasena);
        assertFalse(contrasena.isBlank());

        String url = "jdbc:postgresql://" + host + ":" + puerto + "/sp_rfid2_horario_test";
        String esquema = "rfid2_v22_" + UUID.randomUUID().toString().replace("-", "");
        DriverManagerDataSource base = new DriverManagerDataSource(url, usuario, contrasena);
        assertEquals("sp_rfid2_horario_test", new JdbcTemplate(base).queryForObject(
                "SELECT current_database()", String.class));
        Flyway.configure().dataSource(base).schemas(esquema).defaultSchema(esquema)
                .target("21").cleanDisabled(true).load().migrate();
        DriverManagerDataSource origen = new DriverManagerDataSource(
                url + "?currentSchema=" + esquema, usuario, contrasena);
        JdbcTemplate jdbc = new JdbcTemplate(origen);
        Long empleado = jdbc.queryForObject("""
                INSERT INTO empleado (nombres, primer_apellido, estado)
                VALUES ('Sintetico', 'Prueba', 'ACTIVO') RETURNING id
                """, Long.class);
        String uid = UUID.randomUUID().toString().replace("-", "").substring(0, 20).toUpperCase();
        Long asociacion = jdbc.queryForObject("""
                INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico, empleado_id)
                VALUES (?, ?) RETURNING asociacion_id
                """, Long.class, uid, empleado);
        String sql = "INSERT INTO evento_acceso (ocurrido_en, lector, resultado, motivo, lectura_id, "
                + "asociacion_id, movimiento_id) VALUES (now(), ?, 'DENEGADA', ?, ?, ?, NULL)";
        UUID lecturaAnterior = UUID.randomUUID();
        assertEquals(1, jdbc.update(sql, "RFID2", "FUERA_DE_HORARIO", lecturaAnterior, asociacion));

        Flyway.configure().dataSource(base).schemas(esquema).defaultSchema(esquema)
                .cleanDisabled(true).load().migrate();
        assertEquals(1, jdbc.queryForObject("SELECT COUNT(*) FROM flyway_schema_history "
                + "WHERE version = '22' AND success", Integer.class));
        assertEquals(1, jdbc.queryForObject("SELECT COUNT(*) FROM evento_acceso "
                + "WHERE lectura_id = ? AND motivo = 'FUERA_DE_HORARIO'", Integer.class, lecturaAnterior));
        assertEquals(1, jdbc.update(sql, "RFID2", "CAPACIDAD_COMPLETA", UUID.randomUUID(), asociacion));
        assertEquals(1, jdbc.update(sql, "RFID2", "ENTRADA_PENDIENTE", UUID.randomUUID(), asociacion));
        assertEquals(1, jdbc.update(sql, "RFID3", "SIN_ENTRADA_ABIERTA", UUID.randomUUID(), asociacion));
        assertThrows(DataIntegrityViolationException.class,
                () -> jdbc.update(sql, "RFID2", null, UUID.randomUUID(), asociacion));
        assertThrows(DataIntegrityViolationException.class,
                () -> jdbc.update(sql, "RFID2", "CAPACIDAD_COMPLETA", UUID.randomUUID(), null));
        assertThrows(DataIntegrityViolationException.class,
                () -> jdbc.update(sql, "RFID3", "CAPACIDAD_COMPLETA", UUID.randomUUID(), asociacion));
        assertThrows(DataIntegrityViolationException.class,
                () -> jdbc.update(sql, "RFID2", "MOTIVO_INEXISTENTE", UUID.randomUUID(), asociacion));
    }
}
