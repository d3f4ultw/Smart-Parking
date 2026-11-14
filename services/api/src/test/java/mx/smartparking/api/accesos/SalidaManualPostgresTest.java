package mx.smartparking.api.accesos;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;

import java.util.List;
import java.util.UUID;
import java.util.concurrent.Executors;
import javax.sql.DataSource;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.PublicadorAccesoAdministracion;
import mx.smartparking.api.historial.persistencia.RepositorioEventoAccesoJdbc;
import mx.smartparking.api.persistencia.RepositorioCuentasJdbc;
import mx.smartparking.api.rfid3.persistencia.RepositorioRfid3Jdbc;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.mock.web.MockHttpSession;

/** Valida transacciones reales exclusivamente en el PostgreSQL sintético descartable. */
@EnabledIfEnvironmentVariable(named = "SMARTPARKING_MANUAL_POSTGRES_DESCARTABLE", matches = "true")
class SalidaManualPostgresTest {
    private static JdbcTemplate jdbc;
    private static DataSource origen;
    private static UUID dueno;
    private static GestorSesionesPropietario sesiones;
    private static PrincipalPropietario principal;
    private static MockHttpSession sesion;
    private static ServicioSalidaManual manual;
    private static ServicioSalidaManual manualSinClave;
    private static final byte[] CLAVE = new byte[32];
    private static final java.util.concurrent.atomic.AtomicLong RELOJ = new java.util.concurrent.atomic.AtomicLong();
    private static DetectorCapacidadSalidaManual detector;
    private static RepositorioRfid3Jdbc rfid3;
    private static final String BOOT = "AAAAAAAAAAAAAAAAAAAAAA";
    private static final String TICKET = java.util.Base64.getUrlEncoder().withoutPadding()
            .encodeToString(new byte[] {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16});

    @BeforeAll
    static void preparar() {
        assertEquals("sp_manual_salida_test", System.getenv("POSTGRES_DB"));
        assertEquals("127.0.0.1", System.getenv("POSTGRES_HOST"));
        String url = "jdbc:postgresql://127.0.0.1:5432/sp_manual_salida_test";
        String usuario = System.getenv("POSTGRES_USER");
        String contrasena = System.getenv("POSTGRES_PASSWORD");
        String esquema = "manual_" + UUID.randomUUID().toString().replace("-", "");
        DriverManagerDataSource base = new DriverManagerDataSource(url, usuario, contrasena);
        Flyway.configure().dataSource(base).schemas(esquema).defaultSchema(esquema)
                .target("23").cleanDisabled(true).load().migrate();
        origen = new DriverManagerDataSource(url + "?currentSchema=" + esquema, usuario, contrasena);
        jdbc = new JdbcTemplate(origen);
        UUID historico = UUID.randomUUID();
        jdbc.update("""
                INSERT INTO evento_acceso (ocurrido_en, lector, resultado, motivo, lectura_id)
                VALUES (now(), 'RFID2', 'DENEGADA', 'TARJETA_DESCONOCIDA', ?)
                """, historico);
        Flyway.configure().dataSource(base).schemas(esquema).defaultSchema(esquema)
                .cleanDisabled(true).load().migrate();
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM evento_acceso WHERE lectura_id = ?", Integer.class, historico));
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM flyway_schema_history WHERE version = '24' AND success", Integer.class));
        dueno = UUID.randomUUID();
        UUID estacionamiento = UUID.randomUUID();
        String correo = dueno + "@example.invalid";
        jdbc.update("""
                INSERT INTO cuenta (id, nombres, primer_apellido, correo, correo_normalizado, rol,
                    estado, hash_contrasena_acceso, revision_acceso, creada_en, actualizada_en)
                VALUES (?, 'Prueba', 'Sintetica', ?, ?, 'DUENO', 'ACTIVA', 'sintetico', 1, now(), now())
                """, dueno, correo, correo);
        jdbc.update("""
                UPDATE configuracion_estacionamiento
                SET estado = 'CONFIGURADA', revision = 1, revision_propietario = 1,
                    estacionamiento_id = ?, dueno_cuenta_id = ?, hash_contrasena_administrativa = 'sintetico',
                    nombre_estacionamiento = 'Prueba', tipo_estacionamiento = 'MIXTO',
                    modo_horario = 'CONTINUO_24_7', zona_horaria = 'America/Mexico_City'
                WHERE id = 1
                """, estacionamiento, dueno);
        sesiones = new GestorSesionesPropietario();
        principal = new PrincipalPropietario(dueno, RolCuenta.DUENO, 1, 1, correo);
        sesion = new MockHttpSession();
        sesiones.registrar(sesion, principal);
        var administrador = new DataSourceTransactionManager(origen);
        var publicador = mock(PublicadorAccesoAdministracion.class);
        var eventos = new RepositorioEventoAccesoJdbc(jdbc, publicador);
        new java.security.SecureRandom().nextBytes(CLAVE);
        detector = new DetectorCapacidadSalidaManual(
                new AutenticadorSalidaManual(java.util.HexFormat.of().formatHex(CLAVE)), RELOJ::get);
        manual = new ServicioSalidaManual(jdbc, administrador, sesiones, new RepositorioCuentasJdbc(jdbc),
                eventos, publicador, new AutenticadorSalidaManual(java.util.HexFormat.of().formatHex(CLAVE)), detector);
        manualSinClave = new ServicioSalidaManual(jdbc, administrador, sesiones, new RepositorioCuentasJdbc(jdbc),
                eventos, publicador, new AutenticadorSalidaManual(""), detector);
        rfid3 = new RepositorioRfid3Jdbc(jdbc, administrador, eventos);
    }

    @BeforeEach
    void prepararCapacidad() {
        RELOJ.set(0);
        detector.invalidar();
        renovarCapacidad();
    }

    @Test
    void soloAcuseValidoCierraUnaVezYRegistraManual() {
        Visita visita = visita(true);
        UUID id = UUID.randomUUID();
        var primera = manual.solicitar(Long.toString(visita.movimiento()), id.toString(), principal, sesion);
        assertEquals("PENDIENTE", primera.estado());
        assertEquals(primera, manual.solicitar(Long.toString(visita.movimiento()), id.toString(), principal, sesion));
        assertThrows(ErrorConfiguracion.class, () -> manual.solicitar(Long.toString(visita.movimiento()),
                UUID.randomUUID().toString(), principal, sesion));
        assertNotNull(manual.emitir(id.toString(), BOOT, TICKET));
        assertNull(manual.emitir(id.toString(), BOOT, TICKET));
        assertEquals(1, abiertas(visita));
        assertThrows(ErrorConfiguracion.class, () -> manual.resultado(id.toString(), TICKET, TICKET, "EJECUTADA", firmaResultado(id, "EJECUTADA")));
        assertEquals(1, abiertas(visita));
        assertEquals("CONFIRMADA", notificar(id, "EJECUTADA").estado());
        assertEquals("CONFIRMADA", notificar(id, "EJECUTADA").estado());
        assertEquals(0, abiertas(visita));
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM evento_acceso WHERE lector = 'MANUAL' AND lectura_id = ?", Integer.class, id));
        assertEquals("CONFIRMADA", manual.solicitar(Long.toString(visita.movimiento()), id.toString(), principal, sesion).estado());
    }

    @Test
    void activaOCerradaNoPermitePrepararUnaSalida() {
        Visita activa = visita(false);
        assertThrows(ErrorConfiguracion.class, () -> manual.solicitar(Long.toString(activa.movimiento()),
                UUID.randomUUID().toString(), principal, sesion));
        Visita cerrada = visita(true);
        assertEquals("AUTORIZADA", rfid3.registrarSalida(cerrada.uid(), UUID.randomUUID()).resultado());
        assertThrows(ErrorConfiguracion.class, () -> manual.solicitar(Long.toString(cerrada.movimiento()),
                UUID.randomUUID().toString(), principal, sesion));
    }

    @Test
    void rechazoAntesDePwmConservaLaVisitaYPermiteNuevoIntentoExplicito() {
        Visita visita = visita(true);
        UUID id = UUID.randomUUID();
        manual.solicitar(Long.toString(visita.movimiento()), id.toString(), principal, sesion);
        assertNotNull(manual.emitir(id.toString(), BOOT, TICKET));
        assertEquals("NO_EJECUTADA", notificar(id, "NO_EJECUTADA").estado());
        assertEquals("NO_EJECUTADA", notificar(id, "NO_EJECUTADA").estado());
        assertEquals(1, abiertas(visita));
        assertEquals("PENDIENTE", manual.solicitar(Long.toString(visita.movimiento()),
                UUID.randomUUID().toString(), principal, sesion).estado());
    }

    @Test
    void rfid3AnulaPendienteYBloqueaEmisionSinDuplicarSalida() {
        Visita visita = visita(true);
        UUID id = UUID.randomUUID();
        manual.solicitar(Long.toString(visita.movimiento()), id.toString(), principal, sesion);
        assertEquals("AUTORIZADA", rfid3.registrarSalida(visita.uid(), UUID.randomUUID()).resultado());
        assertEquals("ANULADA", manual.consultar(id.toString()).estado());
        assertNull(manual.emitir(id.toString(), BOOT, TICKET));
        assertEquals(0, abiertas(visita));
    }

    @Test
    void rfid3NoCierraVisitaInciertaNiDespuesDeVencerTicket() {
        Visita visita = visita(true);
        UUID id = UUID.randomUUID();
        manual.solicitar(Long.toString(visita.movimiento()), id.toString(), principal, sesion);
        assertNotNull(manual.emitir(id.toString(), BOOT, TICKET));
        jdbc.update("UPDATE solicitud_salida_manual SET emitida_en = now() - interval '30 seconds' WHERE operacion_id = ?", id);
        assertEquals("INCIERTA", manual.consultar(id.toString()).estado());
        var resultado = rfid3.registrarSalida(visita.uid(), UUID.randomUUID());
        assertEquals("DENEGADA", resultado.resultado());
        assertEquals("SALIDA_MANUAL_EN_CURSO", resultado.motivo());
        assertEquals(1, abiertas(visita));
        assertThrows(ErrorConfiguracion.class, () -> manual.solicitar(Long.toString(visita.movimiento()),
                UUID.randomUUID().toString(), principal, sesion));
        assertEquals("CONFIRMADA", notificar(id, "EJECUTADA").estado());
    }

    @Test
    void dosEmisionesSimultaneasEntreganUnSoloPermiso() throws Exception {
        Visita visita = visita(true);
        UUID id = UUID.randomUUID();
        manual.solicitar(Long.toString(visita.movimiento()), id.toString(), principal, sesion);
        try (var pool = Executors.newFixedThreadPool(2)) {
            var resultados = pool.invokeAll(List.<java.util.concurrent.Callable<Boolean>>of(
                    () -> manual.emitir(id.toString(), BOOT, TICKET) != null,
                    () -> manual.emitir(id.toString(), BOOT, TICKET) != null));
            long permisos = 0;
            for (var resultado : resultados) if (resultado.get()) permisos++;
            assertEquals(1, permisos);
        }
        assertEquals(1, abiertas(visita));
    }

    @Test
    void cierreDeSesionAntesDeEmisionImpideAutorizar() {
        Visita visita = visita(true);
        UUID id = UUID.randomUUID();
        MockHttpSession temporal = new MockHttpSession();
        sesiones.registrar(temporal, principal);
        manual.solicitar(Long.toString(visita.movimiento()), id.toString(), principal, temporal);
        sesiones.olvidar(temporal);
        assertNull(manual.emitir(id.toString(), BOOT, TICKET));
        assertEquals("ANULADA", manual.consultar(id.toString()).estado());
        assertEquals(1, abiertas(visita));
    }

    @Test
    void firmaInvalidaOCambiadaNuncaConfirmaLaSalida() {
        Visita visita = visita(true);
        UUID id = UUID.randomUUID();
        manual.solicitar(Long.toString(visita.movimiento()), id.toString(), principal, sesion);
        String permiso = manual.emitir(id.toString(), BOOT, TICKET);
        assertNotNull(permiso);
        assertTrue(java.security.MessageDigest.isEqual(permiso.getBytes(java.nio.charset.StandardCharsets.US_ASCII),
                firmaEjecucion(id).getBytes(java.nio.charset.StandardCharsets.US_ASCII)));
        String valida = firmaResultado(id, "EJECUTADA");
        String alterada = (valida.charAt(0) == 'A' ? "B" : "A") + valida.substring(1);
        assertThrows(ErrorConfiguracion.class,
                () -> manual.resultado(id.toString(), BOOT, TICKET, "EJECUTADA", null));
        assertThrows(ErrorConfiguracion.class,
                () -> manual.resultado(id.toString(), BOOT, TICKET, "EJECUTADA", alterada));
        assertThrows(ErrorConfiguracion.class,
                () -> manual.resultado(UUID.randomUUID().toString(), BOOT, TICKET, "EJECUTADA", valida));
        assertThrows(ErrorConfiguracion.class,
                () -> manual.resultado(id.toString(), TICKET, TICKET, "EJECUTADA", valida));
        assertThrows(ErrorConfiguracion.class,
                () -> manual.resultado(id.toString(), BOOT, BOOT, "EJECUTADA", valida));
        assertThrows(ErrorConfiguracion.class,
                () -> manual.resultado(id.toString(), BOOT, TICKET, "NO_EJECUTADA", valida));
        assertEquals(1, abiertas(visita));
        assertEquals("EMITIDA", manual.consultar(id.toString()).estado());
        assertEquals("CONFIRMADA", notificar(id, "EJECUTADA").estado());
    }

    @Test
    void claveAusenteDeshabilitaManualSinAfectarRfid() {
        Visita visita = visita(true);
        UUID id = UUID.randomUUID();
        ErrorConfiguracion sinClave = assertThrows(ErrorConfiguracion.class, () -> manualSinClave.solicitar(
                Long.toString(visita.movimiento()), id.toString(), principal, sesion));
        assertEquals(org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE, sinClave.estadoHttp());
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM solicitud_salida_manual WHERE operacion_id = ?",
                Integer.class, id));
        manual.solicitar(Long.toString(visita.movimiento()), id.toString(), principal, sesion);
        assertThrows(ErrorConfiguracion.class, () -> manualSinClave.emitir(id.toString(), BOOT, TICKET));
        assertEquals("PENDIENTE", manual.consultar(id.toString()).estado());
        assertEquals("AUTORIZADA", rfid3.registrarSalida(visita.uid(), UUID.randomUUID()).resultado());

        Visita emitida = visita(true);
        UUID otra = UUID.randomUUID();
        manual.solicitar(Long.toString(emitida.movimiento()), otra.toString(), principal, sesion);
        assertNotNull(manual.emitir(otra.toString(), BOOT, TICKET));
        assertThrows(ErrorConfiguracion.class, () -> manualSinClave.resultado(
                otra.toString(), BOOT, TICKET, "EJECUTADA", firmaResultado(otra, "EJECUTADA")));
        assertEquals(1, abiertas(emitida));
    }

    @Test
    void vencimientoNoCreaOrdenNiImpideReplayYBloqueaEmision() {
        Visita visita = visita(true);
        UUID clave = UUID.randomUUID();
        detector.invalidar();
        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> manual.solicitar(Long.toString(visita.movimiento()), clave.toString(), principal, sesion));
        assertEquals(org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE, error.estadoHttp());
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM solicitud_salida_manual WHERE operacion_id = ?",
                Integer.class, clave));
        renovarCapacidad();
        assertEquals("PENDIENTE", manual.solicitar(Long.toString(visita.movimiento()), clave.toString(), principal, sesion).estado());
        RELOJ.addAndGet(java.util.concurrent.TimeUnit.SECONDS.toNanos(8));
        assertEquals("PENDIENTE", manual.solicitar(Long.toString(visita.movimiento()), clave.toString(), principal, sesion).estado());
        assertNull(manual.emitir(clave.toString(), BOOT, TICKET));
        assertEquals("ANULADA", manual.consultar(clave.toString()).estado());
        assertEquals(1, abiertas(visita));

        renovarCapacidad();
        UUID otra = UUID.randomUUID();
        manual.solicitar(Long.toString(visita.movimiento()), otra.toString(), principal, sesion);
        assertNotNull(manual.emitir(otra.toString(), BOOT, TICKET));
        detector.invalidar();
        assertEquals("CONFIRMADA", notificar(otra, "EJECUTADA").estado());
    }

    @Test
    void unBootDiferenteNoUsaLaCapacidadDelArranqueAnterior() {
        Visita visita = visita(true);
        UUID primera = UUID.randomUUID();
        manual.solicitar(Long.toString(visita.movimiento()), primera.toString(), principal, sesion);
        assertNull(manual.emitir(primera.toString(), TICKET, TICKET));
        assertEquals("ANULADA", manual.consultar(primera.toString()).estado());
        assertFalse(detector.disponibilidad().disponible());
        assertEquals(1, abiertas(visita));

        String desafio = detector.crearDesafio();
        assertTrue(detector.confirmar(desafio, TICKET, DetectorCapacidadSalidaManualTest.firmar(TICKET, desafio, CLAVE)));
        UUID segunda = UUID.randomUUID();
        manual.solicitar(Long.toString(visita.movimiento()), segunda.toString(), principal, sesion);
        assertNotNull(manual.emitir(segunda.toString(), TICKET, TICKET));
        assertEquals("EMITIDA", manual.consultar(segunda.toString()).estado());
        assertEquals(1, abiertas(visita));
    }

    @Test
    void recorridoContinuaAunqueUnaEmisionNoTengaResultado() {
        Visita primera = visita(true);
        Visita segunda = visita(true);
        UUID idPrimero = UUID.randomUUID();
        UUID idSegundo = UUID.randomUUID();
        manual.solicitar(Long.toString(primera.movimiento()), idPrimero.toString(), principal, sesion);
        manual.solicitar(Long.toString(segunda.movimiento()), idSegundo.toString(), principal, sesion);
        assertNotNull(manual.emitir(idPrimero.toString(), BOOT, TICKET));
        assertNotNull(manual.emitir(idSegundo.toString(), BOOT, TICKET));
        int cantidad = jdbc.queryForObject("""
                SELECT count(*) FROM solicitud_salida_manual
                WHERE (estado = 'PENDIENTE' AND vence_en > clock_timestamp())
                    OR estado IN ('EMITIDA', 'INCIERTA')
                """, Integer.class);
        java.util.Set<String> vistas = new java.util.HashSet<>();
        String cursor = null;
        for (int i = 0; i < cantidad + 1; i++) {
            var trabajo = manual.pendiente(cursor);
            assertNotNull(trabajo);
            cursor = trabajo.operacionId();
            vistas.add(cursor);
        }
        assertTrue(vistas.contains(idPrimero.toString()));
        assertTrue(vistas.contains(idSegundo.toString()));
    }

    @Test
    void solicitudesConcurrentesDeLaMismaVisitaNoCreanDosOrdenes() throws Exception {
        Visita visita = visita(true);
        try (var pool = Executors.newFixedThreadPool(2)) {
            var tareas = List.<java.util.concurrent.Callable<Boolean>>of(
                    () -> intentarSolicitar(visita), () -> intentarSolicitar(visita));
            var resultados = pool.invokeAll(tareas);
            long creadas = 0;
            for (var resultado : resultados) if (resultado.get()) creadas++;
            assertEquals(1, creadas);
        }
        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM solicitud_salida_manual
                WHERE movimiento_id = ? AND estado IN ('PENDIENTE', 'EMITIDA', 'INCIERTA')
                """, Integer.class, visita.movimiento()));
    }

    @Test
    void falloDelEventoRevierteCierreYConfirmacion() {
        Visita visita = visita(true);
        UUID id = UUID.randomUUID();
        manual.solicitar(Long.toString(visita.movimiento()), id.toString(), principal, sesion);
        assertNotNull(manual.emitir(id.toString(), BOOT, TICKET));
        jdbc.execute("""
                CREATE FUNCTION rechazar_evento_manual_test() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF NEW.lector = 'MANUAL' THEN RAISE EXCEPTION 'fallo sintetico'; END IF; RETURN NEW; END $$
                """);
        jdbc.execute("""
                CREATE TRIGGER rechazar_evento_manual_test BEFORE INSERT ON evento_acceso
                FOR EACH ROW EXECUTE FUNCTION rechazar_evento_manual_test()
                """);
        try {
            assertThrows(RuntimeException.class, () -> notificar(id, "EJECUTADA"));
            assertEquals(1, abiertas(visita));
            assertEquals("EMITIDA", manual.consultar(id.toString()).estado());
        } finally {
            jdbc.execute("DROP TRIGGER rechazar_evento_manual_test ON evento_acceso");
            jdbc.execute("DROP FUNCTION rechazar_evento_manual_test()");
        }
        assertEquals("CONFIRMADA", notificar(id, "EJECUTADA").estado());
    }

    private static boolean intentarSolicitar(Visita visita) {
        try {
            manual.solicitar(Long.toString(visita.movimiento()), UUID.randomUUID().toString(), principal, sesion);
            return true;
        } catch (ErrorConfiguracion excepcion) {
            assertEquals(org.springframework.http.HttpStatus.CONFLICT, excepcion.estadoHttp());
            return false;
        }
    }

    private static ServicioSalidaManual.Respuesta notificar(UUID id, String resultado) {
        return manual.resultado(id.toString(), BOOT, TICKET, resultado, firmaResultado(id, resultado));
    }

    private static void renovarCapacidad() {
        String desafio = detector.crearDesafio();
        assertNotNull(desafio);
        assertTrue(detector.confirmar(desafio, BOOT, DetectorCapacidadSalidaManualTest.firmar(BOOT, desafio, CLAVE)));
    }

    private static String firmaResultado(UUID id, String resultado) {
        String codigo = "EJECUTADA".equals(resultado) ? "E" : "N";
        return firmaPrueba(id, "RESULT", "|" + codigo);
    }

    private static String firmaEjecucion(UUID id) {
        return firmaPrueba(id, "EXEC", "");
    }

    private static String firmaPrueba(UUID id, String proposito, String sufijo) {
        try {
            byte[] uuid = java.nio.ByteBuffer.allocate(16).putLong(id.getMostSignificantBits())
                    .putLong(id.getLeastSignificantBits()).array();
            String compacto = java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(uuid);
            String datos = "smartparking.manual.v1|" + proposito + "|" + compacto + "|" + BOOT + "|" + TICKET + sufijo;
            javax.crypto.Mac mac = javax.crypto.Mac.getInstance("HmacSHA256");
            mac.init(new javax.crypto.spec.SecretKeySpec(CLAVE, "HmacSHA256"));
            return java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(
                    java.util.Arrays.copyOf(mac.doFinal(datos.getBytes(java.nio.charset.StandardCharsets.US_ASCII)), 12));
        } catch (java.security.GeneralSecurityException excepcion) {
            throw new IllegalStateException(excepcion);
        }
    }

    private static Visita visita(boolean cancelar) {
        Long empleado = jdbc.queryForObject("INSERT INTO empleado (nombres, primer_apellido) VALUES ('A', 'Sintetico') RETURNING id", Long.class);
        String uid = UUID.randomUUID().toString().replace("-", "").substring(0, 20).toUpperCase();
        Long asociacion = jdbc.queryForObject("""
                INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico, empleado_id) VALUES (?, ?) RETURNING asociacion_id
                """, Long.class, uid, empleado);
        Long movimiento = jdbc.queryForObject("""
                INSERT INTO movimiento_estacionamiento (asociacion_id, tipo_persona, empleado_id, uid_historico,
                    lectura_id, fecha_entrada, hora_entrada, instante_entrada)
                VALUES (?, 'EMPLEADO', ?, ?, ?, current_date, localtime, now() - interval '1 minute') RETURNING movimiento_id
                """, Long.class, asociacion, empleado, uid, UUID.randomUUID());
        if (cancelar) jdbc.update("UPDATE asociacion_tarjeta_rfid1 SET estado = 'CANCELADA', cancelada_en = now() WHERE asociacion_id = ?", asociacion);
        return new Visita(uid, movimiento);
    }
    private static int abiertas(Visita visita) {
        return jdbc.queryForObject("SELECT count(*) FROM movimiento_estacionamiento WHERE movimiento_id = ? AND instante_salida IS NULL", Integer.class, visita.movimiento());
    }
    private record Visita(String uid, long movimiento) { }
}
