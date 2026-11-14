package mx.smartparking.api.recuperacion;

import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.activacion.ErrorLimitacionAccionOperador;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;
import mx.smartparking.api.activacion.ProteccionIntentosActivacion;
import mx.smartparking.api.activacion.SeguridadTokensOperador;
import mx.smartparking.api.activacion.ServicioActivacionOperador;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.empleados.coordinacion.EmpleadoEnlaceOperador;
import mx.smartparking.api.empleados.coordinacion.PuertoEmpleadosOperador;
import mx.smartparking.api.correo.NotificadorRecuperacionOperador;
import mx.smartparking.api.persistencia.AccionOperadorPersistida;
import mx.smartparking.api.persistencia.CuentaActivacionOperador;
import mx.smartparking.api.persistencia.RecuperacionContrasenaOperadorPersistida;
import mx.smartparking.api.persistencia.RepositorioAccionesOperador;
import mx.smartparking.api.persistencia.RepositorioActivacionOperador;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Permite pedir y utilizar enlaces para que los operadores recuperen su contraseña. */
@Service
public final class ServicioRecuperacionContrasenaOperador {

    private static final String OPERACION = "SOLICITAR_RECUPERACION";
    private static final Duration VALIDEZ = Duration.ofMinutes(30);
    private static final Duration ENFRIAMIENTO = Duration.ofMinutes(15);
    private static final Duration VENTANA_CUOTA = Duration.ofHours(1);
    private static final int MAXIMO_POR_HORA = 3;
    private static final String CODIGO_TOKEN_INVALIDO = "TOKEN_RECUPERACION_INVALIDO";
    private static final String MENSAJE_TOKEN_INVALIDO = "Este enlace venció o ya se usó. Pide uno nuevo.";

    private final RepositorioActivacionOperador cuentas;
    private final RepositorioAccionesOperador acciones;
    private final NotificadorRecuperacionOperador notificador;
    private final ServicioActivacionOperador activacion;
    private final PasswordEncoder codificador;
    private final ProteccionIntentosActivacion proteccionIntentos;
    private final GestorSesionesPropietario sesiones;
    private final TransactionTemplate transaccion;
    private final Clock reloj;
    private final SecureRandom aleatorio;
    private PuertoEmpleadosOperador empleados;

    @Autowired
    void establecerEmpleados(PuertoEmpleadosOperador empleados) { this.empleados = empleados; }

    @Autowired
    public ServicioRecuperacionContrasenaOperador(
            RepositorioActivacionOperador cuentas,
            RepositorioAccionesOperador acciones,
            NotificadorRecuperacionOperador notificador,
            ServicioActivacionOperador activacion,
            PasswordEncoder codificador,
            ProteccionIntentosActivacion proteccionIntentos,
            GestorSesionesPropietario sesiones,
            PlatformTransactionManager administradorTransacciones) {
        this(cuentas, acciones, notificador, activacion, codificador, proteccionIntentos, sesiones,
                administradorTransacciones, Clock.systemUTC(), new SecureRandom());
    }

    ServicioRecuperacionContrasenaOperador(
            RepositorioActivacionOperador cuentas,
            RepositorioAccionesOperador acciones,
            NotificadorRecuperacionOperador notificador,
            ServicioActivacionOperador activacion,
            PasswordEncoder codificador,
            ProteccionIntentosActivacion proteccionIntentos,
            GestorSesionesPropietario sesiones,
            PlatformTransactionManager administradorTransacciones,
            Clock reloj,
            SecureRandom aleatorio) {
        this.cuentas = cuentas;
        this.acciones = acciones;
        this.notificador = notificador;
        this.activacion = activacion;
        this.codificador = codificador;
        this.proteccionIntentos = proteccionIntentos;
        this.sesiones = sesiones;
        this.transaccion = new TransactionTemplate(administradorTransacciones);
        this.reloj = reloj;
        this.aleatorio = aleatorio;
    }

    /** Prepara un enlace de recuperación para una cuenta activa y guarda solo una huella de su código. */
    public ResultadoSolicitudRecuperacionOperador solicitar(
            UUID operadorId, String ifMatch, String rawIdempotencyKey) {
        long revisionSolicitada = validarIfMatch(ifMatch);
        String claveHash = SeguridadTokensOperador.hashClaveIdempotencia(rawIdempotencyKey);
        TransicionSolicitud transicion = transaccion.execute(estado -> prepararSolicitud(
                operadorId, revisionSolicitada, claveHash));
        if (transicion == null) {
            throw servicioNoDisponible();
        }
        EstadoEnvioInvitacion estadoEnvio = transicion.estadoEnvio();
        Instant venceEn = transicion.venceEn();
        if (transicion.preparacion() != null) {
            estadoEnvio = enviar(transicion.preparacion());
            persistirResultado(transicion.preparacion(), estadoEnvio);
        }
        return new ResultadoSolicitudRecuperacionOperador(
                new RespuestaSolicitudRecuperacionOperador(
                        estadoEnvio, venceEn, transicion.creadaEn().plus(ENFRIAMIENTO)),
                transicion.revisionAcceso());
    }

    private TransicionSolicitud prepararSolicitud(UUID operadorId, long revisionSolicitada, String claveHash) {
        Long empleadoId = cuentas.empleadoId(operadorId).orElse(null);
        EmpleadoEnlaceOperador empleado = bloquearEmpleadoVinculado(empleadoId);
        CuentaActivacionOperador cuenta = cuentas.bloquearCuenta(operadorId)
                .orElseThrow(() -> operadorNoElegible());
        validarVinculoYEmpleadoActivo(cuenta, empleadoId, empleado);
        acciones.bloquearInvitacion(operadorId);
        acciones.bloquearRecuperacion(operadorId);
        Optional<AccionOperadorPersistida> repetida = acciones.bloquearAccion(operadorId, OPERACION, claveHash);
        if (repetida.isPresent()) {
            AccionOperadorPersistida accion = repetida.get();
            return new TransicionSolicitud(null, cuenta.revisionAcceso(), accion.estadoEnvio(),
                    accion.creadaEn(), accion.venceEn());
        }
        exigirRevision(cuenta.revisionAcceso(), revisionSolicitada);
        exigirCuentaActiva(cuenta);
        exigirCuota(operadorId);
        validarCorreoAntesDeCommit();

        Instant generadoEn = ahora();
        Instant venceEn = generadoEn.plus(VALIDEZ);
        String token = SeguridadTokensOperador.crearToken(aleatorio);
        String tokenHash = SeguridadTokensOperador.hash(token);
        if (!acciones.crearRecuperacion(operadorId, tokenHash, generadoEn, venceEn, generadoEn)
                || !acciones.insertarAccion(operadorId, OPERACION, claveHash, generadoEn,
                        EstadoEnvioInvitacion.ENVIANDO, cuenta.revisionAcceso(), venceEn)) {
            throw error(HttpStatus.CONFLICT, "OPERACION_EN_CONFLICTO", "La información cambió. Inténtalo de nuevo.");
        }
        PreparacionRecuperacionOperador preparacion = new PreparacionRecuperacionOperador(
                operadorId, cuenta.correo(), token, tokenHash, claveHash, venceEn, activacion.origenValidado());
        return new TransicionSolicitud(preparacion, cuenta.revisionAcceso(),
                EstadoEnvioInvitacion.ENVIANDO, generadoEn, venceEn);
    }

    /** Comprueba si el enlace de recuperación puede usarse sin impedir que se utilice después. */
    public RespuestaValidacionRecuperacionOperador validar(String token) {
        String claveIntentos = claveIntentos(token);
        exigirPermitido(claveIntentos);
        Optional<RecuperacionContrasenaOperadorPersistida> recuperacion = obtenerVigente(token);
        if (recuperacion.isEmpty()) {
            registrarFallo(claveIntentos);
            throw tokenInvalido();
        }
        return new RespuestaValidacionRecuperacionOperador(true);
    }

    /** Guarda la contraseña nueva y deja de aceptar el enlace en una sola operación. */
    public void completar(SolicitudCompletarRecuperacionOperador solicitud) {
        if (solicitud == null) {
            throw error(HttpStatus.BAD_REQUEST, "SOLICITUD_NO_VALIDA", "Escribe una contraseña y repítela en el segundo campo.");
        }
        String token = solicitud.token();
        String tokenHash = SeguridadTokensOperador.hash(token == null ? "" : token);
        String claveIntentos = claveIntentos(token);
        exigirPermitido(claveIntentos);
        Optional<RecuperacionContrasenaOperadorPersistida> candidata = obtenerVigente(token);
        if (candidata.isEmpty()) {
            registrarFallo(claveIntentos);
            throw tokenInvalido();
        }
        validarContrasenas(solicitud, claveIntentos);
        String hashContrasena = codificador.encode(solicitud.contrasena());
        Boolean completada = transaccion.execute(estado -> completarBajoBloqueo(
                candidata.get().operadorId(), tokenHash, hashContrasena, claveIntentos));
        if (!Boolean.TRUE.equals(completada)) {
            throw servicioNoDisponible();
        }
        proteccionIntentos.registrarExito(claveIntentos);
        sesiones.revocarCuenta(candidata.get().operadorId());
    }

    private boolean completarBajoBloqueo(
            UUID operadorId, String tokenHash, String hashContrasena, String claveIntentos) {
        Long empleadoId = cuentas.empleadoId(operadorId).orElse(null);
        EmpleadoEnlaceOperador empleado = bloquearEmpleadoVinculado(empleadoId);
        CuentaActivacionOperador cuenta = cuentas.bloquearCuenta(operadorId).orElse(null);
        if (cuenta != null) {
            validarVinculoYEmpleadoActivo(cuenta, empleadoId, empleado);
        }
        acciones.bloquearInvitacion(operadorId);
        RecuperacionContrasenaOperadorPersistida recuperacion = acciones.bloquearRecuperacion(operadorId).orElse(null);
        acciones.bloquearAcciones(operadorId);
        Instant ahora = ahora();
        if (!cuentaActiva(cuenta) || recuperacion == null || !esVigente(recuperacion, tokenHash, ahora)) {
            registrarFallo(claveIntentos);
            throw tokenInvalido();
        }
        if (cuenta.revisionAcceso() == Long.MAX_VALUE) {
            throw servicioNoDisponible();
        }
        if (!acciones.actualizarContrasena(operadorId, cuenta.revisionAcceso(), hashContrasena, ahora)
                || !acciones.consumirRecuperacion(operadorId, tokenHash, ahora)) {
            registrarFallo(claveIntentos);
            throw tokenInvalido();
        }
        return true;
    }


    private EmpleadoEnlaceOperador bloquearEmpleadoVinculado(Long empleadoId) {
        if (empleadoId == null) {
            return null;
        }
        if (empleados == null) {
            throw servicioNoDisponible();
        }
        EmpleadoEnlaceOperador empleado = empleados.bloquearPorId(empleadoId).orElse(null);
        if (empleado == null || !"ACTIVO".equals(empleado.estado())) {
            throw operadorNoElegible();
        }
        return empleado;
    }

    private static void validarVinculoYEmpleadoActivo(
            CuentaActivacionOperador cuenta, Long empleadoId, EmpleadoEnlaceOperador empleado) {
        if (!java.util.Objects.equals(cuenta.empleadoId(), empleadoId)
                || (empleadoId != null && (empleado == null || !"ACTIVO".equals(empleado.estado())))) {
            throw operadorNoElegible();
        }
    }

    private void persistirResultado(PreparacionRecuperacionOperador preparacion, EstadoEnvioInvitacion estado) {
        transaccion.execute(transaccionEstado -> {
            acciones.actualizarEstadoRecuperacion(preparacion.operadorId(), preparacion.tokenHash(), estado);
            acciones.actualizarEstadoAccion(preparacion.operadorId(), OPERACION, preparacion.claveHash(), estado);
            return null;
        });
    }

    private EstadoEnvioInvitacion enviar(PreparacionRecuperacionOperador preparacion) {
        try {
            EstadoEnvioInvitacion estado = notificador.enviarRecuperacion(
                    preparacion.correo(), enlace(preparacion.origen(), preparacion.token()));
            return estado == null || estado == EstadoEnvioInvitacion.ENVIANDO
                    ? EstadoEnvioInvitacion.DESCONOCIDO : estado;
        } catch (RuntimeException excepcion) {
            return EstadoEnvioInvitacion.DESCONOCIDO;
        }
    }

    private void validarCorreoAntesDeCommit() {
        activacion.origenValidado();
    }

    private void exigirCuota(UUID operadorId) {
        Instant ahora = ahora();
        Optional<Instant> ultima = acciones.ultimaAccion(operadorId, OPERACION);
        if (ultima.isPresent()) {
            Instant disponible = ultima.get().plus(ENFRIAMIENTO);
            if (ahora.isBefore(disponible)) {
                throw new ErrorLimitacionAccionOperador("RECUPERACION_EN_ENFRIAMIENTO",
                        "Espera un momento antes de pedir otro enlace.", segundosHasta(ahora, disponible));
            }
        }
        Instant desde = ahora.minus(VENTANA_CUOTA);
        if (acciones.contarAcciones(operadorId, OPERACION, desde) >= MAXIMO_POR_HORA) {
            Instant disponible = acciones.primeraAccion(operadorId, java.util.List.of(OPERACION), desde)
                    .map(fecha -> fecha.plus(VENTANA_CUOTA)).orElse(ahora.plus(VENTANA_CUOTA));
            throw new ErrorLimitacionAccionOperador("RECUPERACION_LIMITE_ALCANZADO",
                    "Ya pediste varios enlaces. Inténtalo más tarde.", segundosHasta(ahora, disponible));
        }
    }

    private Optional<RecuperacionContrasenaOperadorPersistida> obtenerVigente(String token) {
        if (!SeguridadTokensOperador.tokenTieneFormato(token)) {
            return Optional.empty();
        }
        String tokenHash = SeguridadTokensOperador.hash(token);
        return acciones.buscarRecuperacionPorHash(tokenHash)
                .filter(recuperacion -> esVigente(recuperacion, tokenHash, ahora()));
    }

    private void validarContrasenas(SolicitudCompletarRecuperacionOperador solicitud, String claveIntentos) {
        String contrasena = solicitud.contrasena();
        if (contrasena == null || contrasena.codePointCount(0, contrasena.length()) < 10
                || !contrasena.equals(solicitud.confirmarContrasena())) {
            registrarFallo(claveIntentos);
            throw error(HttpStatus.BAD_REQUEST, "CONTRASENA_NO_VALIDA",
                    "Elige una contraseña más larga y repítela igual en ambos campos.");
        }
    }

    private String claveIntentos(String token) {
        return SeguridadTokensOperador.hash("RECUPERACION:" + (token == null ? "" : token));
    }

    private void exigirPermitido(String claveIntentos) {
        if (!proteccionIntentos.permitido(claveIntentos)) {
            throw error(HttpStatus.TOO_MANY_REQUESTS, "INTENTOS_RECUPERACION_LIMITADOS",
                    "Por seguridad, espera 15 minutos antes de intentarlo otra vez.");
        }
    }

    private void registrarFallo(String claveIntentos) {
        proteccionIntentos.registrarFallo(claveIntentos);
    }

    private static boolean cuentaActiva(CuentaActivacionOperador cuenta) {
        return cuenta != null && cuenta.rol() == RolCuenta.OPERADOR && "ACTIVA".equals(cuenta.estado())
                && cuenta.hashContrasena() != null;
    }

    private static void exigirCuentaActiva(CuentaActivacionOperador cuenta) {
        if (!cuentaActiva(cuenta)) {
            throw operadorNoElegible();
        }
    }

    private static boolean esVigente(
            RecuperacionContrasenaOperadorPersistida recuperacion, String tokenHash, Instant ahora) {
        return SeguridadTokensOperador.hashesIguales(recuperacion.tokenHash(), tokenHash)
                && recuperacion.consumidoEn() == null && ahora.isBefore(recuperacion.venceEn());
    }

    private static long validarIfMatch(String ifMatch) {
        if (ifMatch == null) {
            throw error(HttpStatus.PRECONDITION_REQUIRED, "REVISION_REQUERIDA",
                    "Actualiza la información de la cuenta antes de continuar.");
        }
        if (ifMatch.length() < 3 || ifMatch.charAt(0) != '"' || ifMatch.charAt(ifMatch.length() - 1) != '"'
                || !ifMatch.substring(1, ifMatch.length() - 1).matches("[0-9]+")) {
            throw error(HttpStatus.BAD_REQUEST, "REVISION_NO_VALIDA", "La información cambió. Actualiza la cuenta e inténtalo de nuevo.");
        }
        try {
            return Long.parseLong(ifMatch.substring(1, ifMatch.length() - 1));
        } catch (NumberFormatException excepcion) {
            throw error(HttpStatus.BAD_REQUEST, "REVISION_NO_VALIDA", "La información cambió. Actualiza la cuenta e inténtalo de nuevo.");
        }
    }

    private static void exigirRevision(long actual, long esperada) {
        if (actual != esperada) {
            throw error(HttpStatus.PRECONDITION_FAILED, "REVISION_OBSOLETA",
                    "La información de la cuenta cambió. Actualízala antes de continuar.");
        }
    }

    private static String enlace(String origen, String token) {
        return origen + "/restablecer-contrasena#" + token;
    }

    private Instant ahora() {
        return reloj.instant().truncatedTo(ChronoUnit.MICROS);
    }

    private static long segundosHasta(Instant ahora, Instant limite) {
        Duration espera = Duration.between(ahora, limite);
        return espera.getNano() > 0 ? espera.getSeconds() + 1 : Math.max(1, espera.getSeconds());
    }

    private static ErrorConfiguracion tokenInvalido() {
        return error(HttpStatus.GONE, CODIGO_TOKEN_INVALIDO, MENSAJE_TOKEN_INVALIDO);
    }

    private static ErrorConfiguracion operadorNoElegible() {
        return error(HttpStatus.NOT_FOUND, "OPERADOR_NO_ENCONTRADO", "No encontramos esta cuenta.");
    }

    private static ErrorConfiguracion servicioNoDisponible() {
        return error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                "No pudimos preparar el cambio de contraseña. Inténtalo más tarde.");
    }

    private static ErrorConfiguracion error(HttpStatus estado, String codigo, String mensaje) {
        return new ErrorConfiguracion(estado, mensaje, codigo);
    }

    private record TransicionSolicitud(
            PreparacionRecuperacionOperador preparacion,
            long revisionAcceso,
            EstadoEnvioInvitacion estadoEnvio,
            Instant creadaEn,
            Instant venceEn) {
    }
}
