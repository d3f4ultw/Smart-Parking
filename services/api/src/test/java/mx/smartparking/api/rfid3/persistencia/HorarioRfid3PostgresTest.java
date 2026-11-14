package mx.smartparking.api.rfid3.persistencia;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

import java.time.Clock;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.Locale;
import java.util.UUID;
import javax.sql.DataSource;
import mx.smartparking.api.historial.persistencia.RepositorioEventoAccesoJdbc;
import mx.smartparking.api.rfid2.servicio.HorarioRfid2PostgresTest;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;

/** Comprueba que RFID3 cierra movimientos aun después del horario de entrada. */
class HorarioRfid3PostgresTest {
    private static final ZoneId ZONA = ZoneId.of("America/Mexico_City");
    private static final LocalDate FECHA = LocalDate.of(2026, 11, 7);
    private static DataSource origen;
    private static JdbcTemplate jdbc;

    @BeforeAll
    static void prepararBase() {
        origen = HorarioRfid2PostgresTest.baseDescartable("rfid3_horario_pruebas");
        jdbc = new JdbcTemplate(origen);
        String estado = jdbc.queryForObject("SELECT estado FROM configuracion_estacionamiento WHERE id = 1", String.class);
        if ("SIN_CONFIGURAR".equals(estado)) {
            UUID dueno = UUID.randomUUID();
            String correo = dueno + "@example.invalid";
            jdbc.update("""
                    INSERT INTO cuenta (id, nombres, primer_apellido, correo, correo_normalizado, rol,
                        estado, hash_contrasena_acceso, revision_acceso, creada_en, actualizada_en)
                    VALUES (?, 'Sintetico', 'Prueba', ?, ?, 'DUENO', 'ACTIVA', 'hash-sintetico', 1, now(), now())
                    """, dueno, correo, correo);
            jdbc.update("""
                    UPDATE configuracion_estacionamiento
                    SET estado = 'CONFIGURADA', revision = 1, revision_propietario = 1,
                        estacionamiento_id = ?, dueno_cuenta_id = ?, hash_contrasena_administrativa = 'hash-sintetico',
                        nombre_estacionamiento = 'Prueba', tipo_estacionamiento = 'MIXTO',
                        modo_horario = 'INTERVALO_DIARIO', zona_horaria = 'America/Mexico_City',
                        hora_apertura = '08:00', hora_cierre = '18:00'
                    WHERE id = 1
                    """, UUID.randomUUID(), dueno);
        }
        assertEquals("CONFIGURADA", jdbc.queryForObject(
                "SELECT estado FROM configuracion_estacionamiento WHERE id = 1", String.class));
        jdbc.update("""
                UPDATE configuracion_estacionamiento SET modo_horario = 'INTERVALO_DIARIO',
                    zona_horaria = 'America/Mexico_City', hora_apertura = '08:00', hora_cierre = '18:00'
                WHERE id = 1
                """);
    }

    @Test
    void empleadoYClienteSalenDespuesDelCierre() {
        Clock reloj = Clock.fixed(FECHA.atTime(19, 0).atZone(ZONA).toInstant(), ZoneOffset.UTC);
        RepositorioRfid3Jdbc repositorio = new RepositorioRfid3Jdbc(jdbc,
                new DataSourceTransactionManager(origen), reloj, new RepositorioEventoAccesoJdbc(jdbc, null));
        for (String tipo : new String[] {"EMPLEADO", "CLIENTE"}) {
            Persona persona = persona(tipo);
            UUID lecturaEntrada = UUID.randomUUID();
            UUID lecturaSalida = UUID.randomUUID();
            OffsetDateTime instanteEntrada = FECHA.atTime(17, 0).atZone(ZONA).toOffsetDateTime();
            Long movimientoId = jdbc.queryForObject("""
                    INSERT INTO movimiento_estacionamiento (asociacion_id, tipo_persona, cliente_id, empleado_id,
                        uid_historico, lectura_id, fecha_entrada, hora_entrada, instante_entrada)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING movimiento_id
                    """, Long.class, persona.asociacionId(), tipo, persona.clienteId(), persona.empleadoId(),
                    persona.uid(), lecturaEntrada, FECHA, LocalTime.of(17, 0), instanteEntrada);

            assertEquals("AUTORIZADA", repositorio.registrarSalida(persona.uid(), lecturaSalida).resultado());
            assertEquals(LocalTime.of(19, 0), jdbc.queryForObject(
                    "SELECT hora_salida FROM movimiento_estacionamiento WHERE movimiento_id = ?", LocalTime.class,
                    movimientoId));
            assertNotNull(jdbc.queryForObject("SELECT instante_salida FROM movimiento_estacionamiento "
                    + "WHERE movimiento_id = ?", OffsetDateTime.class, movimientoId));
            assertEquals(lecturaSalida, jdbc.queryForObject("SELECT lectura_salida_id FROM movimiento_estacionamiento "
                    + "WHERE movimiento_id = ?", UUID.class, movimientoId));
            assertEquals(1, jdbc.queryForObject("""
                    SELECT COUNT(*) FROM evento_acceso WHERE lector = 'RFID3' AND lectura_id = ?
                        AND resultado = 'AUTORIZADA' AND asociacion_id = ? AND movimiento_id = ?
                    """, Integer.class, lecturaSalida, persona.asociacionId(), movimientoId));
        }
    }

    @Test
    void tarjetaCanceladaConEntradaAbiertaSaleUnaVezDespuesDelCierre() {
        Clock reloj = Clock.fixed(FECHA.atTime(19, 0).atZone(ZONA).toInstant(), ZoneOffset.UTC);
        RepositorioRfid3Jdbc repositorio = new RepositorioRfid3Jdbc(jdbc,
                new DataSourceTransactionManager(origen), reloj, new RepositorioEventoAccesoJdbc(jdbc, null));
        for (String tipo : new String[] {"EMPLEADO", "CLIENTE"}) {
            Persona persona = persona(tipo);
            UUID lecturaSalida = UUID.randomUUID();
            OffsetDateTime instanteEntrada = FECHA.atTime(17, 0).atZone(ZONA).toOffsetDateTime();
            Long movimientoId = jdbc.queryForObject("""
                    INSERT INTO movimiento_estacionamiento (asociacion_id, tipo_persona, cliente_id, empleado_id,
                        uid_historico, lectura_id, fecha_entrada, hora_entrada, instante_entrada)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING movimiento_id
                    """, Long.class, persona.asociacionId(), tipo, persona.clienteId(), persona.empleadoId(),
                    persona.uid(), UUID.randomUUID(), FECHA, LocalTime.of(17, 0), instanteEntrada);
            jdbc.update("UPDATE asociacion_tarjeta_rfid1 SET estado = 'CANCELADA', cancelada_en = now() "
                    + "WHERE asociacion_id = ?", persona.asociacionId());

            assertEquals("AUTORIZADA", repositorio.registrarSalida(persona.uid(), lecturaSalida).resultado());
            assertEquals("AUTORIZADA", repositorio.registrarSalida(persona.uid(), lecturaSalida).resultado());
            assertEquals("TARJETA_CANCELADA",
                    repositorio.registrarSalida(persona.uid(), UUID.randomUUID()).motivo());
            assertEquals(lecturaSalida, jdbc.queryForObject(
                    "SELECT lectura_salida_id FROM movimiento_estacionamiento WHERE movimiento_id = ?",
                    UUID.class, movimientoId));
            assertEquals(1, jdbc.queryForObject("""
                    SELECT COUNT(*) FROM evento_acceso WHERE lector = 'RFID3'
                        AND lectura_id = ? AND resultado = 'AUTORIZADA' AND movimiento_id = ?
                    """, Integer.class, lecturaSalida, movimientoId));
        }
    }

    @Test
    void tarjetaCanceladaSinEntradaAbiertaNoPuedeSalir() {
        RepositorioRfid3Jdbc repositorio = new RepositorioRfid3Jdbc(jdbc,
                new DataSourceTransactionManager(origen), Clock.systemUTC(), new RepositorioEventoAccesoJdbc(jdbc, null));
        Persona persona = persona("EMPLEADO");
        jdbc.update("UPDATE asociacion_tarjeta_rfid1 SET estado = 'CANCELADA', cancelada_en = now() "
                + "WHERE asociacion_id = ?", persona.asociacionId());

        assertEquals("TARJETA_CANCELADA",
                repositorio.registrarSalida(persona.uid(), UUID.randomUUID()).motivo());
        assertEquals(0, jdbc.queryForObject(
                "SELECT COUNT(*) FROM movimiento_estacionamiento WHERE asociacion_id = ?",
                Integer.class, persona.asociacionId()));
    }

    private static Persona persona(String tipo) {
        String uid = UUID.randomUUID().toString().replace("-", "").substring(0, 20).toUpperCase(Locale.ROOT);
        Long empleadoId = null;
        UUID clienteId = null;
        if ("EMPLEADO".equals(tipo)) {
            empleadoId = jdbc.queryForObject("INSERT INTO empleado (nombres, primer_apellido, estado) "
                    + "VALUES ('Sintetico', 'Prueba', 'INACTIVO') RETURNING id", Long.class);
        } else {
            clienteId = UUID.randomUUID();
            String correo = clienteId + "@example.invalid";
            jdbc.update("""
                    INSERT INTO cuenta (id, nombres, primer_apellido, correo, correo_normalizado,
                        rol, estado, revision_acceso, creada_en, actualizada_en)
                    VALUES (?, 'Sintetico', 'Prueba', ?, ?, 'CLIENTE', 'INACTIVA', 1, now(), now())
                    """, clienteId, correo, correo);
        }
        Long asociacionId = jdbc.queryForObject("""
                INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico, empleado_id, cliente_id)
                VALUES (?, ?, ?) RETURNING asociacion_id
                """, Long.class, uid, empleadoId, clienteId);
        return new Persona(uid, asociacionId, empleadoId, clienteId);
    }

    private record Persona(String uid, long asociacionId, Long empleadoId, UUID clienteId) { }
}
