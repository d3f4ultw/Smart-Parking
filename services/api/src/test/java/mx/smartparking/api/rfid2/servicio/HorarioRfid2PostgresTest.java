package mx.smartparking.api.rfid2.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.time.Clock;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import javax.sql.DataSource;
import mx.smartparking.api.accesos.RepositorioAccesosJdbc;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.EstadoConfiguracion;
import mx.smartparking.api.configuracion.ModoHorario;
import mx.smartparking.api.persistencia.ConfiguracionPersistida;
import mx.smartparking.api.persistencia.RepositorioConfiguracion;
import mx.smartparking.api.rfid2.persistencia.RepositorioRfid2Jdbc;
import mx.smartparking.api.rfid2.persistencia.ResultadoEntradaRfid2;
import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.configuration.FluentConfiguration;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/** Verifica el horario y sus registros en una base explícitamente descartable. */
public class HorarioRfid2PostgresTest {
    private static final ZoneId ZONA = ZoneId.of("America/Mexico_City");
    private static final LocalDate FECHA = LocalDate.of(2026, 11, 7);
    private static DataSource origen;
    private static JdbcTemplate jdbc;

    @BeforeAll
    static void prepararBase() {
        origen = baseDescartable("rfid2_horario_pruebas");
        jdbc = new JdbcTemplate(origen);
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
        for (int numero = 0; numero < 150; numero++) {
            UUID cajon = UUID.randomUUID();
            jdbc.update("INSERT INTO vision_cajon (cajon_id, estacionamiento_id, etiqueta) VALUES (?, ?, ?)",
                    cajon, estacionamiento, "C" + numero);
            jdbc.update("INSERT INTO vision_zona (fuente_id, vision_zone_id, cajon_id) VALUES (?, ?, ?)",
                    fuente, UUID.randomUUID(), cajon);
        }
    }

    /** Prepara solo esquemas dedicados en la base de pruebas elegida explícitamente. */
    public static DataSource baseDescartable(String esquema) {
        assumeTrue("true".equals(System.getenv("SMARTPARKING_POSTGRES_DESCARTABLE")),
                "La prueba PostgreSQL es opt-in.");
        assertTrue(Set.of("rfid2_horario_pruebas", "rfid3_horario_pruebas").contains(esquema)
                || esquema.matches("rfid2_historico_[0-9a-f]{32}")
                || esquema.matches("rfid2_membresia_[0-9a-f]{32}")
                || esquema.matches("rfid2_seguridad_[0-9a-f]{32}"));
        assertEquals("sp_rfid2_horario_test", System.getenv("POSTGRES_DB"),
                "Se requiere la base descartable específica.");
        String host = System.getenv("POSTGRES_HOST");
        assertTrue("127.0.0.1".equals(host) || "localhost".equals(host),
                "La base de pruebas debe ser accesible solo por loopback.");
        String puerto = System.getenv("POSTGRES_PORT");
        assertNotNull(puerto);
        assertTrue(puerto.matches("[0-9]{1,5}"));
        int numeroPuerto = Integer.parseInt(puerto);
        assertTrue(numeroPuerto > 0 && numeroPuerto <= 65535);
        String usuario = System.getenv("POSTGRES_USER");
        String contrasena = System.getenv("POSTGRES_PASSWORD");
        assertNotNull(usuario);
        assertFalse(usuario.isBlank());
        assertNotNull(contrasena);
        assertFalse(contrasena.isBlank());
        String url = "jdbc:postgresql://" + host + ":" + puerto + "/sp_rfid2_horario_test";
        DriverManagerDataSource conexionBase = new DriverManagerDataSource(url, usuario, contrasena);
        assertEquals("sp_rfid2_horario_test",
                new JdbcTemplate(conexionBase).queryForObject("SELECT current_database()", String.class));
        FluentConfiguration flyway = Flyway.configure().dataSource(conexionBase).schemas(esquema)
                .defaultSchema(esquema).cleanDisabled(true);
        if (esquema.startsWith("rfid2_historico_")) {
            flyway.target("20");
        }
        flyway.load().migrate();
        return new DriverManagerDataSource(url + "?currentSchema=" + esquema, usuario, contrasena);
    }

    @Test
    void empleadoYClienteCompartenHorarioYContinuo() {
        for (String tipo : new String[] {"EMPLEADO", "CLIENTE"}) {
            Persona dentro = persona(tipo);
            UUID lecturaDentro = UUID.randomUUID();
            assertEquals("AUTORIZADA", entrada(dentro, lecturaDentro, LocalTime.of(9, 0),
                    ModoHorario.INTERVALO_DIARIO, LocalTime.of(8, 0), LocalTime.of(18, 0)).resultado());
            Map<String, Object> movimiento = jdbc.queryForMap("""
                    SELECT tipo_persona, empleado_id, cliente_id FROM movimiento_estacionamiento WHERE lectura_id = ?
                    """, lecturaDentro);
            assertEquals(tipo, movimiento.get("tipo_persona"));
            assertEquals(dentro.empleadoId(), movimiento.get("empleado_id"));
            assertEquals(dentro.clienteId(), movimiento.get("cliente_id"));

            Persona fuera = persona(tipo);
            UUID lecturaFuera = UUID.randomUUID();
            ResultadoEntradaRfid2 denegada = entrada(fuera, lecturaFuera, LocalTime.of(18, 0),
                    ModoHorario.INTERVALO_DIARIO, LocalTime.of(8, 0), LocalTime.of(18, 0));
            assertEquals("DENEGADA", denegada.resultado());
            assertEquals("FUERA_DE_HORARIO", denegada.motivo());
            assertEquals(0, movimientos(fuera));
            Map<String, Object> evento = evento(lecturaFuera);
            assertEquals("DENEGADA", evento.get("resultado"));
            assertEquals("FUERA_DE_HORARIO", evento.get("motivo"));
            assertEquals(fuera.asociacionId(), evento.get("asociacion_id"));
            assertNull(evento.get("movimiento_id"));

            Persona continuo = persona(tipo);
            assertEquals("AUTORIZADA", entrada(continuo, UUID.randomUUID(), LocalTime.of(3, 0),
                    ModoHorario.CONTINUO_24_7, null, null).resultado());
            assertEquals(1, movimientos(continuo));
        }
    }

    @Test
    void limitesDiurnosYNocturnosUsanLaZonaConfigurada() {
        comprobarLimite(LocalTime.of(8, 0), LocalTime.of(18, 0), LocalTime.of(7, 59, 59), false);
        comprobarLimite(LocalTime.of(8, 0), LocalTime.of(18, 0), LocalTime.of(8, 0), true);
        comprobarLimite(LocalTime.of(8, 0), LocalTime.of(18, 0), LocalTime.of(17, 59, 59), true);
        comprobarLimite(LocalTime.of(8, 0), LocalTime.of(18, 0), LocalTime.of(18, 0), false);
        comprobarLimite(LocalTime.of(22, 0), LocalTime.of(6, 0), LocalTime.of(21, 59, 59), false);
        comprobarLimite(LocalTime.of(22, 0), LocalTime.of(6, 0), LocalTime.of(22, 0), true);
        comprobarLimite(LocalTime.of(22, 0), LocalTime.of(6, 0), LocalTime.MIDNIGHT, true);
        comprobarLimite(LocalTime.of(22, 0), LocalTime.of(6, 0), LocalTime.of(5, 59, 59), true);
        comprobarLimite(LocalTime.of(22, 0), LocalTime.of(6, 0), LocalTime.of(6, 0), false);
    }

    @Test
    void replayConservaMovimientoEventoYConflicto() {
        for (String tipo : new String[] {"EMPLEADO", "CLIENTE"}) {
            Persona persona = persona(tipo);
            UUID lectura = UUID.randomUUID();
            assertEquals("AUTORIZADA", entrada(persona, lectura, LocalTime.of(17, 0),
                    ModoHorario.INTERVALO_DIARIO, LocalTime.of(8, 0), LocalTime.of(18, 0)).resultado());
            Map<String, Object> eventoOriginal = evento(lectura);
            Map<String, Object> movimientoOriginal = jdbc.queryForMap(
                    "SELECT * FROM movimiento_estacionamiento WHERE lectura_id = ?", lectura);
            assertEquals("AUTORIZADA", entrada(persona, lectura, LocalTime.of(17, 30),
                    ModoHorario.INTERVALO_DIARIO, LocalTime.of(8, 0), LocalTime.of(18, 0)).resultado());
            ResultadoEntradaRfid2 fuera = entrada(persona, lectura, LocalTime.of(18, 0),
                    ModoHorario.INTERVALO_DIARIO, LocalTime.of(8, 0), LocalTime.of(18, 0));
            assertEquals("DENEGADA", fuera.resultado());
            assertEquals("FUERA_DE_HORARIO", fuera.motivo());
            assertEquals(1, movimientos(persona));
            assertEquals(eventoOriginal, evento(lectura));
            assertEquals(movimientoOriginal, jdbc.queryForMap(
                    "SELECT * FROM movimiento_estacionamiento WHERE lectura_id = ?", lectura));
            assertEquals(1, jdbc.queryForObject("SELECT COUNT(*) FROM evento_acceso WHERE lectura_id = ?",
                    Integer.class, lectura));
            Persona otra = persona(tipo);
            ErrorConfiguracion conflicto = assertThrows(ErrorConfiguracion.class, () -> entrada(
                    otra, lectura, LocalTime.of(18, 0), ModoHorario.INTERVALO_DIARIO,
                    LocalTime.of(8, 0), LocalTime.of(18, 0)));
            assertEquals(HttpStatus.CONFLICT, conflicto.estadoHttp());
            assertEquals("LECTURA_EN_CONFLICTO", conflicto.codigo());
            assertEquals(eventoOriginal, evento(lectura));
            assertEquals(0, movimientos(otra));
        }
    }

    @Test
    void denegacionesExistentesConservanPrioridadFueraDeHorario() {
        Persona desconocida = new Persona(uid(), 0, null, null);
        assertEquals("TARJETA_DESCONOCIDA", entrada(desconocida, UUID.randomUUID(), LocalTime.of(20, 0),
                ModoHorario.INTERVALO_DIARIO, LocalTime.of(8, 0), LocalTime.of(18, 0)).motivo());
        Persona cancelada = persona("EMPLEADO");
        jdbc.update("UPDATE asociacion_tarjeta_rfid1 SET estado = 'CANCELADA', cancelada_en = now() "
                + "WHERE asociacion_id = ?", cancelada.asociacionId());
        assertEquals("TARJETA_CANCELADA", entrada(cancelada, UUID.randomUUID(), LocalTime.of(20, 0),
                ModoHorario.INTERVALO_DIARIO, LocalTime.of(8, 0), LocalTime.of(18, 0)).motivo());
        Persona pendiente = persona("CLIENTE");
        assertEquals("AUTORIZADA", entrada(pendiente, UUID.randomUUID(), LocalTime.of(10, 0),
                ModoHorario.INTERVALO_DIARIO, LocalTime.of(8, 0), LocalTime.of(18, 0)).resultado());
        assertEquals("ENTRADA_PENDIENTE", entrada(pendiente, UUID.randomUUID(), LocalTime.of(20, 0),
                ModoHorario.INTERVALO_DIARIO, LocalTime.of(8, 0), LocalTime.of(18, 0)).motivo());
    }

    @Test
    void v21MantieneRestriccionesDeAsociacionMovimientoYLector() {
        Persona persona = persona("EMPLEADO");
        UUID lectura = UUID.randomUUID();
        assertEquals("AUTORIZADA", entrada(persona, lectura, LocalTime.of(10, 0),
                ModoHorario.CONTINUO_24_7, null, null).resultado());
        Long movimientoId = jdbc.queryForObject("SELECT movimiento_id FROM movimiento_estacionamiento WHERE lectura_id = ?",
                Long.class, lectura);
        String insertar = "INSERT INTO evento_acceso (ocurrido_en, lector, resultado, motivo, lectura_id, "
                + "asociacion_id, movimiento_id) VALUES (now(), ?, 'DENEGADA', ?, ?, ?, ?)";
        assertThrows(DataIntegrityViolationException.class,
                () -> jdbc.update(insertar, "RFID2", "FUERA_DE_HORARIO", UUID.randomUUID(), null, null));
        assertThrows(DataIntegrityViolationException.class,
                () -> jdbc.update(insertar, "RFID3", "FUERA_DE_HORARIO", UUID.randomUUID(), persona.asociacionId(), null));
        assertThrows(DataIntegrityViolationException.class,
                () -> jdbc.update(insertar, "RFID2", "FUERA_DE_HORARIO", UUID.randomUUID(), persona.asociacionId(), movimientoId));
        assertEquals(1, jdbc.update(insertar, "RFID2", "FUERA_DE_HORARIO", UUID.randomUUID(), persona.asociacionId(), null));
        assertEquals(1, jdbc.update(insertar, "RFID2", "ENTRADA_PENDIENTE", UUID.randomUUID(), persona.asociacionId(), null));
        assertEquals(1, jdbc.update(insertar, "RFID3", "SIN_ENTRADA_ABIERTA", UUID.randomUUID(), persona.asociacionId(), null));
        assertEquals(1, jdbc.update(insertar, "RFID2", "TARJETA_DESCONOCIDA", UUID.randomUUID(), null, null));
    }

    @Test
    void consultasDentroBuscanNombreYCodigoSinBuscarUidYPaginanElTotalFiltrado() {
        String nombre = "Filtro" + UUID.randomUUID().toString().replace("-", "").substring(0, 8);
        Persona primera = null;
        for (int numero = 0; numero < 12; numero++) {
            Persona empleado = persona("EMPLEADO");
            if (primera == null) {
                primera = empleado;
            }
            jdbc.update("UPDATE empleado SET nombres = ? WHERE id = ?", nombre, empleado.empleadoId());
            assertEquals("AUTORIZADA", entrada(empleado, UUID.randomUUID(), LocalTime.of(10, 0),
                    ModoHorario.CONTINUO_24_7, null, null).resultado());
        }
        Persona cliente = persona("CLIENTE");
        jdbc.update("UPDATE cuenta SET nombres = ? WHERE id = ?", nombre, cliente.clienteId());
        assertEquals("AUTORIZADA", entrada(cliente, UUID.randomUUID(), LocalTime.of(10, 0),
                ModoHorario.CONTINUO_24_7, null, null).resultado());

        RepositorioAccesosJdbc accesos = new RepositorioAccesosJdbc(jdbc);
        var pagina1 = accesos.consultarDentro(1, nombre.toLowerCase(Locale.ROOT));
        var pagina2 = accesos.consultarDentro(2, nombre);
        assertEquals(13, pagina1.total());
        assertEquals(10, pagina1.items().size());
        assertTrue(pagina1.haySiguiente());
        assertEquals(3, pagina2.items().size());
        assertFalse(pagina2.haySiguiente());
        String codigoEmpleado = String.format(Locale.ROOT, "E-%04d", primera.empleadoId());
        long numeroCliente = jdbc.queryForObject("SELECT numero FROM cliente_codigo_publico WHERE cliente_id = ?",
                Long.class, cliente.clienteId());
        String codigoCliente = String.format(Locale.ROOT, "CLI-%04d", numeroCliente);
        assertEquals(codigoEmpleado, accesos.consultarDentro(1, codigoEmpleado.toLowerCase(Locale.ROOT))
                .items().getFirst().codigoPersona());
        assertEquals(codigoCliente, accesos.consultarDentro(1, codigoCliente).items().getFirst().codigoPersona());
        assertEquals(0, accesos.consultarDentro(1, primera.uid()).total());
        assertEquals(0, accesos.consultarDentro(1, "%_").total());
    }

    @Test
    void v21ConservaMovimientosYEventosAnteriores() {
        String esquema = "rfid2_historico_" + UUID.randomUUID().toString().replace("-", "");
        DataSource origenHistorico = baseDescartable(esquema);
        JdbcTemplate historico = new JdbcTemplate(origenHistorico);
        assertEquals(1, historico.queryForObject("SELECT COUNT(*) FROM flyway_schema_history "
                + "WHERE version = '20' AND success", Integer.class));
        assertEquals(0, historico.queryForObject("SELECT COUNT(*) FROM flyway_schema_history "
                + "WHERE version = '21' AND success", Integer.class));

        Persona empleado = persona(historico, "EMPLEADO");
        Persona cliente = persona(historico, "CLIENTE");
        for (Persona persona : new Persona[] {empleado, cliente}) {
            UUID lecturaEntrada = UUID.randomUUID();
            UUID lecturaSalida = UUID.randomUUID();
            String tipo = persona.clienteId() == null ? "EMPLEADO" : "CLIENTE";
            Long movimientoId = historico.queryForObject("""
                    INSERT INTO movimiento_estacionamiento (
                        asociacion_id, tipo_persona, cliente_id, empleado_id, uid_historico, lectura_id,
                        fecha_entrada, hora_entrada, instante_entrada, fecha_salida, hora_salida,
                        instante_salida, lectura_salida_id)
                    VALUES (?, ?, ?, ?, ?, ?, DATE '2026-01-01', TIME '04:00', TIMESTAMPTZ '2026-01-01 10:00+00',
                        DATE '2026-01-01', TIME '05:00', TIMESTAMPTZ '2026-01-01 11:00+00', ?) RETURNING movimiento_id
                    """, Long.class, persona.asociacionId(), tipo, persona.clienteId(), persona.empleadoId(),
                    persona.uid(), lecturaEntrada, lecturaSalida);
            String insertar = "INSERT INTO evento_acceso (ocurrido_en, lector, resultado, motivo, lectura_id, "
                    + "asociacion_id, movimiento_id) VALUES (?, ?, ?, ?, ?, ?, ?)";
            historico.update(insertar, OffsetDateTime.parse("2026-01-01T10:00:00Z"), "RFID2", "AUTORIZADA",
                    null, lecturaEntrada, persona.asociacionId(), movimientoId);
            historico.update(insertar, OffsetDateTime.parse("2026-01-01T10:30:00Z"), "RFID2", "DENEGADA",
                    "ENTRADA_PENDIENTE", UUID.randomUUID(), persona.asociacionId(), null);
            historico.update(insertar, OffsetDateTime.parse("2026-01-01T11:00:00Z"), "RFID3", "AUTORIZADA",
                    null, lecturaSalida, persona.asociacionId(), movimientoId);
            historico.update(insertar, OffsetDateTime.parse("2026-01-01T11:05:00Z"), "RFID3", "DENEGADA",
                    "SIN_ENTRADA_ABIERTA", UUID.randomUUID(), persona.asociacionId(), null);
        }
        String denegacion = "INSERT INTO evento_acceso (ocurrido_en, lector, resultado, motivo, lectura_id, "
                + "asociacion_id, movimiento_id) VALUES (now(), 'RFID2', 'DENEGADA', ?, ?, ?, NULL)";
        historico.update(denegacion, "TARJETA_DESCONOCIDA", UUID.randomUUID(), null);
        assertThrows(DataIntegrityViolationException.class, () -> historico.update(denegacion,
                "FUERA_DE_HORARIO", UUID.randomUUID(), empleado.asociacionId()));

        List<Map<String, Object>> asociaciones = historico.queryForList(
                "SELECT * FROM asociacion_tarjeta_rfid1 ORDER BY asociacion_id");
        List<Map<String, Object>> movimientos = historico.queryForList(
                "SELECT * FROM movimiento_estacionamiento ORDER BY movimiento_id");
        List<Map<String, Object>> eventos = historico.queryForList("SELECT * FROM evento_acceso ORDER BY evento_id");
        assertEquals(2, asociaciones.size());
        assertEquals(2, movimientos.size());
        assertEquals(9, eventos.size());
        assertEquals("sp_rfid2_horario_test", historico.queryForObject("SELECT current_database()", String.class));

        Flyway.configure().dataSource(origenHistorico).schemas(esquema).defaultSchema(esquema)
                .cleanDisabled(true).load().migrate();

        assertEquals(1, historico.queryForObject("SELECT COUNT(*) FROM flyway_schema_history "
                + "WHERE version = '21' AND success", Integer.class));
        assertEquals(asociaciones, historico.queryForList("SELECT * FROM asociacion_tarjeta_rfid1 ORDER BY asociacion_id"));
        assertEquals(movimientos, historico.queryForList("SELECT * FROM movimiento_estacionamiento ORDER BY movimiento_id"));
        assertEquals(eventos, historico.queryForList("SELECT * FROM evento_acceso ORDER BY evento_id"));
        assertEquals(1, historico.update(denegacion, "FUERA_DE_HORARIO", UUID.randomUUID(), empleado.asociacionId()));
    }

    private static void comprobarLimite(LocalTime apertura, LocalTime cierre, LocalTime hora, boolean autorizada) {
        Persona persona = persona("EMPLEADO");
        ResultadoEntradaRfid2 resultado = entrada(persona, UUID.randomUUID(), hora,
                ModoHorario.INTERVALO_DIARIO, apertura, cierre);
        assertEquals(autorizada ? "AUTORIZADA" : "DENEGADA", resultado.resultado());
        assertEquals(autorizada ? 1 : 0, movimientos(persona));
    }

    private static ResultadoEntradaRfid2 entrada(Persona persona, UUID lectura, LocalTime hora,
            ModoHorario modo, LocalTime apertura, LocalTime cierre) {
        RepositorioConfiguracion configuracion = mock(RepositorioConfiguracion.class);
        ConfiguracionPersistida actual = new ConfiguracionPersistida(
                EstadoConfiguracion.CONFIGURADA, 1, 1, null, null, null, null, null, null, null,
                null, null, modo, ZONA.getId(), apertura, cierre, null, null, null, null, null, null, null, null);
        when(configuracion.buscar()).thenReturn(Optional.of(actual));
        Clock reloj = Clock.fixed(FECHA.atTime(hora).atZone(ZONA).toInstant(), ZoneOffset.UTC);
        RepositorioRfid2Jdbc repositorio = new RepositorioRfid2Jdbc(jdbc, new DataSourceTransactionManager(origen));
        return new ServicioRfid2(repositorio, configuracion, reloj).registrarEntrada(persona.uid(), lectura.toString());
    }

    private static Persona persona(String tipo) {
        return persona(jdbc, tipo);
    }

    private static Persona persona(JdbcTemplate destino, String tipo) {
        String uid = uid();
        Long empleadoId = null;
        UUID clienteId = null;
        if ("EMPLEADO".equals(tipo)) {
            empleadoId = destino.queryForObject("INSERT INTO empleado (nombres, primer_apellido, estado) "
                    + "VALUES ('Sintetico', 'Prueba', 'INACTIVO') RETURNING id", Long.class);
        } else {
            clienteId = UUID.randomUUID();
            String correo = clienteId + "@example.invalid";
            destino.update("""
                    INSERT INTO cuenta (id, nombres, primer_apellido, correo, correo_normalizado,
                        rol, estado, hash_contrasena_acceso, revision_acceso, creada_en, actualizada_en)
                    VALUES (?, 'Sintetico', 'Prueba', ?, ?, 'CLIENTE', 'ACTIVA', 'hash-sintetico', 1, now(), now())
                    """, clienteId, correo, correo);
            crearMembresiaSintetica(destino, clienteId);
        }
        Long asociacionId = destino.queryForObject("""
                INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico, empleado_id, cliente_id)
                VALUES (?, ?, ?) RETURNING asociacion_id
                """, Long.class, uid, empleadoId, clienteId);
        return new Persona(uid, asociacionId, empleadoId, clienteId);
    }

    private static String uid() {
        return UUID.randomUUID().toString().replace("-", "").substring(0, 20).toUpperCase(Locale.ROOT);
    }

    static void crearMembresiaSintetica(JdbcTemplate destino, UUID clienteId) {
        String sufijo = clienteId.toString().replace("-", "");
        destino.update("""
                INSERT INTO cliente_stripe (cliente_id, estado, stripe_customer_id, creada_en, actualizada_en)
                VALUES (?, 'ASOCIADO', ?, now(), now())
                """, clienteId, "cus_" + sufijo);
        destino.update("""
                INSERT INTO suscripcion_cliente (stripe_subscription_id, cliente_id, stripe_customer_id,
                    price_id, estado_stripe, estado, estado_factura_stripe, periodo_inicio, periodo_fin,
                    cancel_at_period_end, evento_creado_en, actualizada_en)
                VALUES (?, ?, ?, 'price_1USQ5HAqtHmR2qmyAWwUp5vy', 'active', 'ACTIVA', 'paid',
                    TIMESTAMPTZ '2026-01-01 00:00+00', TIMESTAMPTZ '2027-12-31 00:00+00', FALSE, now(), now())
                """, "sub_" + sufijo, clienteId, "cus_" + sufijo);
    }

    private static int movimientos(Persona persona) {
        return jdbc.queryForObject("SELECT COUNT(*) FROM movimiento_estacionamiento WHERE asociacion_id = ?",
                Integer.class, persona.asociacionId());
    }

    private static Map<String, Object> evento(UUID lectura) {
        return jdbc.queryForMap("SELECT * FROM evento_acceso WHERE lector = 'RFID2' AND lectura_id = ?", lectura);
    }

    private record Persona(String uid, long asociacionId, Long empleadoId, UUID clienteId) { }
}
