package mx.smartparking.fixture;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.HttpSession;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.HexFormat;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import mx.smartparking.api.activacion.SeguridadTokensOperador;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.HuellaSesionPropietario;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.context.SecurityContextRepository;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Fixtures sintéticos para la prueba de integración; solo se compilan desde src/test. */
@RestController
@RequestMapping("/api/v1/__sandbox/unificacion")
public final class SandboxFixtureControlador {

    private static final String CORREO_SESION = "operador-fixture@example.test";

    private final JdbcTemplate jdbc;
    private final RepositorioCuentas cuentas;
    private final GestorSesionesPropietario sesiones;
    private final SecurityContextRepository repositorioContexto;
    private final TransactionTemplate transaccion;
    private final String nonceConfigurado;
    private final Map<UUID, DatosFixture> fixtures = new ConcurrentHashMap<>();

    public SandboxFixtureControlador(
            JdbcTemplate jdbc,
            RepositorioCuentas cuentas,
            GestorSesionesPropietario sesiones,
            SecurityContextRepository repositorioContexto,
            PlatformTransactionManager administradorTransacciones,
            String nonceConfigurado) {
        this.jdbc = jdbc;
        this.cuentas = cuentas;
        this.sesiones = sesiones;
        this.repositorioContexto = repositorioContexto;
        this.transaccion = new TransactionTemplate(administradorTransacciones);
        this.nonceConfigurado = nonceConfigurado == null ? "" : nonceConfigurado;
    }

    @PostMapping("/preparar")
    ResponseEntity<RespuestaPreparacion> preparar(
            @RequestBody SolicitudFixture solicitud,
            @AuthenticationPrincipal PrincipalPropietario dueno,
            HttpServletRequest peticion) {
        if (!esDueno(dueno) || !nonceValido(solicitud.nonce())) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
        }
        HttpSession sesionDueno = peticion.getSession(false);
        if (sesionDueno == null) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        }

        UUID fixtureId = UUID.randomUUID();
        String huellaSesion = HuellaSesionPropietario.calcular(sesionDueno.getId());
        DatosFixture datos = transaccion.execute(estado -> crearDatos(fixtureId, dueno, huellaSesion));
        if (datos == null) {
            throw new IllegalStateException("No se pudieron crear los datos sintéticos de integración.");
        }
        fixtures.put(fixtureId, datos);
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(new RespuestaPreparacion(fixtureId, datos.empleadoNombre(), datos.operadorNombre()));
    }

    @GetMapping("/preservacion-rfid/{fixtureId}")
    ResponseEntity<RespuestaPreservacion> comprobarPreservacionRfid(
            @PathVariable UUID fixtureId,
            @AuthenticationPrincipal PrincipalPropietario principal) {
        if (!esDueno(principal)) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
        }
        DatosFixture datos = fixtures.get(fixtureId);
        if (datos == null) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok(new RespuestaPreservacion(
                existe("SELECT EXISTS (SELECT 1 FROM asociacion_tarjeta_rfid1 WHERE empleado_id = ? AND uid_canonico = ?)",
                        datos.empleadoId(), datos.uidEmpleado()),
                existe("SELECT EXISTS (SELECT 1 FROM asociacion_tarjeta_rfid1 WHERE cliente_id = ? AND uid_canonico = ?)",
                        datos.clienteId(), datos.uidCliente()),
                existe("SELECT EXISTS (SELECT 1 FROM captura_rfid1 WHERE captura_id = ? AND empleado_id = ?)",
                        datos.capturaEmpleadoId(), datos.empleadoId()),
                existe("SELECT EXISTS (SELECT 1 FROM captura_rfid1 WHERE captura_id = ? AND cliente_id = ?)",
                        datos.capturaClienteId(), datos.clienteId()),
                existe("SELECT EXISTS (SELECT 1 FROM idempotencia_registro_empleado "
                                + "WHERE cuenta_id = ? AND clave_hash = ? AND empleado_id = ? AND estado = 'COMPLETADA')",
                        datos.duenoId(), datos.claveRegistroHash(), datos.empleadoId()),
                existe("SELECT EXISTS (SELECT 1 FROM cuenta WHERE id = ? AND rol = 'OPERADOR')",
                        datos.operadorId())));
    }

    @PostMapping("/sesion-operador/{operadorId}")
    ResponseEntity<RespuestaFixture> instalarSesionOperador(
            @PathVariable("operadorId") UUID operadorId,
            @RequestBody SolicitudFixture solicitud,
            @AuthenticationPrincipal PrincipalPropietario dueno,
            HttpServletRequest peticion,
            HttpServletResponse respuesta) {
        if (!esDueno(dueno) || !nonceValido(solicitud.nonce())) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
        }

        CuentaActiva cuenta = buscarCuentaActivaVinculada(operadorId);
        if (cuenta == null || !cuentas.sesionVigente(
                cuenta.id(), cuenta.revisionAcceso(), RolCuenta.OPERADOR.name(), dueno.revisionPropietario())) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND).build();
        }

        HttpSession sesion = peticion.getSession(true);
        sesiones.olvidar(sesion);
        peticion.changeSessionId();

        PrincipalPropietario operador = new PrincipalPropietario(
                cuenta.id(), RolCuenta.OPERADOR, cuenta.revisionAcceso(),
                dueno.revisionPropietario(), CORREO_SESION);
        SecurityContext contexto = SecurityContextHolder.createEmptyContext();
        contexto.setAuthentication(UsernamePasswordAuthenticationToken.authenticated(
                operador, null, List.of(new SimpleGrantedAuthority("ROLE_OPERADOR"))));
        SecurityContextHolder.setContext(contexto);
        repositorioContexto.saveContext(contexto, peticion, respuesta);
        sesiones.registrar(peticion.getSession(false), operador);

        return ResponseEntity.ok(new RespuestaFixture(true, RolCuenta.OPERADOR.name()));
    }

    private DatosFixture crearDatos(UUID fixtureId, PrincipalPropietario dueno, String huellaSesion) {
        String sufijo = fixtureId.toString().substring(0, 8);
        String empleadoNombre = "Prueba-" + sufijo;
        String empleadoApellido = "RFID";
        String operadorNombre = "Operador";
        String operadorApellido = "Legado-" + sufijo;
        UUID clienteId = UUID.randomUUID();
        UUID operadorId = UUID.randomUUID();
        Instant ahora = Instant.now().truncatedTo(ChronoUnit.MICROS);
        Timestamp marca = Timestamp.from(ahora);
        String correoCliente = "fixture-cliente-" + fixtureId + "@example.test";
        String correoOperador = "fixture-operador-" + fixtureId + "@example.test";

        Long empleadoIdLeido = jdbc.queryForObject("""
                INSERT INTO empleado (nombres, primer_apellido, segundo_apellido, estado)
                VALUES (?, ?, NULL, 'ACTIVO')
                RETURNING id
                """, Long.class, empleadoNombre, empleadoApellido);
        if (empleadoIdLeido == null) {
            throw new IllegalStateException("No se creó el empleado sintético.");
        }
        long empleadoId = empleadoIdLeido;

        jdbc.update("""
                INSERT INTO cuenta (
                    id, nombres, primer_apellido, segundo_apellido, correo, correo_normalizado,
                    rol, estado, hash_contrasena_acceso, revision_acceso, creada_en, actualizada_en)
                VALUES (?, 'Cliente', ?, NULL, ?, ?, 'CLIENTE', 'ACTIVA', ?, 1, ?, ?)
                """, clienteId, "RFID-" + sufijo, correoCliente, correoCliente,
                hash("fixture-cliente:" + fixtureId), marca, marca);
        Long numeroCliente = jdbc.queryForObject(
                "SELECT numero FROM cliente_codigo_publico WHERE cliente_id = ?", Long.class, clienteId);
        if (numeroCliente == null) {
            throw new IllegalStateException("No se creó el código público del cliente sintético.");
        }

        jdbc.update("""
                INSERT INTO cuenta (
                    id, nombres, primer_apellido, segundo_apellido, correo, correo_normalizado,
                    rol, estado, hash_contrasena_acceso, revision_acceso, creada_en, actualizada_en)
                VALUES (?, ?, ?, 'Pendiente', ?, ?, 'OPERADOR', 'PENDIENTE', NULL, 1, ?, ?)
                """, operadorId, operadorNombre, operadorApellido, correoOperador, correoOperador, marca, marca);
        jdbc.update("""
                INSERT INTO invitacion_operador (
                    operador_id, token_hash, generado_en, vence_en, consumido_en,
                    estado_envio, intento_iniciado_en)
                VALUES (?, ?, ?, ?, NULL, 'DESHABILITADO', ?)
                """, operadorId, SeguridadTokensOperador.hash(UUID.randomUUID().toString()),
                marca, Timestamp.from(ahora.plus(2, ChronoUnit.HOURS)), marca);

        String uidEmpleado = uidCanonico();
        String uidCliente = uidCanonico();
        jdbc.update("INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico, empleado_id) VALUES (?, ?)",
                uidEmpleado, empleadoId);
        jdbc.update("INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico, cliente_id) VALUES (?, ?)",
                uidCliente, clienteId);

        String capturaEmpleadoId = UUID.randomUUID().toString().replace("-", "");
        String capturaClienteId = UUID.randomUUID().toString().replace("-", "");
        insertarCaptura(capturaEmpleadoId, "EMPLEADO", codigoEmpleado(empleadoId), null, empleadoId,
                dueno, huellaSesion, uidEmpleado, ahora);
        insertarCaptura(capturaClienteId, "CLIENTE", codigoCliente(numeroCliente), clienteId, null,
                dueno, huellaSesion, uidCliente, ahora);

        String claveRegistroHash = hash("fixture-registro-clave:" + fixtureId);
        jdbc.update("""
                INSERT INTO idempotencia_registro_empleado (
                    cuenta_id, clave_hash, huella_solicitud, estado, empleado_id)
                VALUES (?, ?, ?, 'COMPLETADA', ?)
                """, dueno.cuentaId(), claveRegistroHash,
                hash("fixture-registro-huella:" + fixtureId), empleadoId);

        return new DatosFixture(fixtureId, dueno.cuentaId(), empleadoId, clienteId, operadorId,
                uidEmpleado, uidCliente, capturaEmpleadoId, capturaClienteId, claveRegistroHash,
                empleadoNombre + " " + empleadoApellido,
                operadorNombre + " " + operadorApellido + " Pendiente");
    }

    private void insertarCaptura(
            String capturaId,
            String tipoEntidad,
            String codigoPersona,
            UUID clienteId,
            Long empleadoId,
            PrincipalPropietario dueno,
            String huellaSesion,
            String uid,
            Instant ahora) {
        jdbc.update("""
                INSERT INTO captura_rfid1 (
                    captura_id, lector, tipo_entidad, codigo_persona, cliente_id, empleado_id,
                    propietario_cuenta_id, revision_acceso, revision_propietario, huella_sesion,
                    clave_inicio_hash, huella_solicitud, request_id, huella_uid,
                    estado, resultado, codigo_error, creada_en, actualizada_en, vence_en, terminada_en)
                VALUES (?, 'RFID1', ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?,
                        'COMPLETADA', 'ASOCIADA', NULL, ?, ?, ?, ?)
                """, capturaId, tipoEntidad, codigoPersona, clienteId, empleadoId, dueno.cuentaId(),
                dueno.revisionPropietario(), huellaSesion, hash("fixture-captura-clave:" + capturaId),
                hash("fixture-captura-huella:" + capturaId), uid.substring(0, 4), hash(uid),
                Timestamp.from(ahora), Timestamp.from(ahora), Timestamp.from(ahora.plusSeconds(120)),
                Timestamp.from(ahora));
    }

    private CuentaActiva buscarCuentaActivaVinculada(UUID operadorId) {
        List<CuentaActiva> resultado = jdbc.query("""
                SELECT id, revision_acceso FROM cuenta
                WHERE id = ? AND rol = 'OPERADOR' AND estado = 'ACTIVA' AND empleado_id IS NOT NULL
                """, (fila, numero) -> new CuentaActiva(
                fila.getObject("id", UUID.class), fila.getLong("revision_acceso")), operadorId);
        return resultado.stream().findFirst().orElse(null);
    }

    private boolean existe(String sql, Object... parametros) {
        Boolean resultado = jdbc.queryForObject(sql, Boolean.class, parametros);
        return Boolean.TRUE.equals(resultado);
    }

    private boolean nonceValido(String presentado) {
        if (nonceConfigurado.isBlank() || presentado == null) {
            return false;
        }
        return MessageDigest.isEqual(
                nonceConfigurado.getBytes(StandardCharsets.UTF_8), presentado.getBytes(StandardCharsets.UTF_8));
    }

    private static boolean esDueno(PrincipalPropietario principal) {
        return principal != null && principal.rol() == RolCuenta.DUENO;
    }

    private static String codigoEmpleado(long id) {
        return String.format(Locale.ROOT, "E-%04d", id);
    }

    private static String codigoCliente(long numero) {
        return String.format(Locale.ROOT, "CLI-%04d", numero);
    }

    private static String uidCanonico() {
        return UUID.randomUUID().toString().replace("-", "").substring(0, 20).toUpperCase(Locale.ROOT);
    }

    private static String hash(String valor) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(valor.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException("No se pudo preparar la huella sintética.", excepcion);
        }
    }

    private record DatosFixture(
            UUID fixtureId,
            UUID duenoId,
            long empleadoId,
            UUID clienteId,
            UUID operadorId,
            String uidEmpleado,
            String uidCliente,
            String capturaEmpleadoId,
            String capturaClienteId,
            String claveRegistroHash,
            String empleadoNombre,
            String operadorNombre) {
    }

    private record CuentaActiva(UUID id, long revisionAcceso) {
    }

    public record SolicitudFixture(String nonce) {
    }

    public record RespuestaPreparacion(UUID fixtureId, String empleadoNombre, String operadorNombre) {
    }

    public record RespuestaFixture(boolean autenticada, String rol) {
    }

    public record RespuestaPreservacion(
            boolean asociacionEmpleadoPreservada,
            boolean asociacionClientePreservada,
            boolean capturaEmpleadoPreservada,
            boolean capturaClientePreservada,
            boolean reciboHistoricoPreservado,
            boolean operadorLegadoPreservado) {
    }
}
