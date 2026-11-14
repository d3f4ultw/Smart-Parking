package mx.smartparking.api.activacion;

import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.correo.NotificadorInvitacionOperador;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import mx.smartparking.api.empleados.coordinacion.EmpleadoEnlaceOperador;
import mx.smartparking.api.empleados.coordinacion.PuertoEmpleadosOperador;
import mx.smartparking.api.operadores.ProyeccionInvitacionOperador;
import mx.smartparking.api.operadores.PuertoInvitacionesAdministracion;
import mx.smartparking.api.persistencia.AccionOperadorPersistida;
import mx.smartparking.api.persistencia.CuentaActivacionOperador;
import mx.smartparking.api.persistencia.InvitacionOperadorPersistida;
import mx.smartparking.api.persistencia.RepositorioAccionesOperador;
import mx.smartparking.api.persistencia.RepositorioActivacionOperador;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Prepara y envía nuevas invitaciones cuando el dueño las solicita o reactiva una cuenta de operador. */
@Service
public final class ServicioAdministracionInvitacionesOperador implements PuertoInvitacionesAdministracion {

    private static final String REEMITIR = "REEMITIR_INVITACION";
    private static final String REACTIVAR = "REACTIVAR";
    private static final String RECUPERAR = "SOLICITAR_RECUPERACION";
    private static final String CAMBIAR_CORREO = "CAMBIAR_CORREO";
    private static final List<String> OPERACIONES_INVITACION = List.of(REEMITIR, REACTIVAR, CAMBIAR_CORREO);
    private static final int MAXIMO_POR_HORA = 3;
    private static final Duration VALIDEZ_INVITACION = Duration.ofHours(2);
    private static final Duration ENFRIAMIENTO = Duration.ofSeconds(60);

    private final RepositorioActivacionOperador cuentas;
    private final RepositorioAccionesOperador acciones;
    private final ServicioActivacionOperador activacion;
    private final NotificadorInvitacionOperador notificador;
    private final ServicioEventosAdministracion eventos;
    private final TransactionTemplate transaccion;
    private final Clock reloj;
    private final SecureRandom aleatorio;
    private PuertoEmpleadosOperador empleados;

    @Autowired
    void establecerEmpleados(PuertoEmpleadosOperador empleados) { this.empleados = empleados; }

    @Autowired
    public ServicioAdministracionInvitacionesOperador(
            RepositorioActivacionOperador cuentas,
            RepositorioAccionesOperador acciones,
            ServicioActivacionOperador activacion,
            NotificadorInvitacionOperador notificador,
            ServicioEventosAdministracion eventos,
            PlatformTransactionManager administradorTransacciones) {
        this(cuentas, acciones, activacion, notificador, eventos,
                administradorTransacciones, Clock.systemUTC(), new SecureRandom());
    }

    ServicioAdministracionInvitacionesOperador(
            RepositorioActivacionOperador cuentas,
            RepositorioAccionesOperador acciones,
            ServicioActivacionOperador activacion,
            NotificadorInvitacionOperador notificador,
            ServicioEventosAdministracion eventos,
            PlatformTransactionManager administradorTransacciones,
            Clock reloj,
            SecureRandom aleatorio) {
        this.cuentas = cuentas;
        this.acciones = acciones;
        this.activacion = activacion;
        this.notificador = notificador;
        this.eventos = eventos;
        this.transaccion = new TransactionTemplate(administradorTransacciones);
        this.reloj = reloj;
        this.aleatorio = aleatorio;
    }

    /**
     * Reúne el estado de la invitación y los intentos que quedan para que el propietario pueda
     * consultarlos.
     */
    @Override
    public ProyeccionInvitacionOperador consultar(UUID operadorId) {
        Instant ahora = ahora();
        Optional<InvitacionOperadorPersistida> invitacion = acciones.consultarInvitacion(operadorId);
        int usadasInvitacion = contarAccionesInvitacion(operadorId, ahora.minus(Duration.ofHours(1)));
        int usadasRecuperacion = acciones.contarAcciones(operadorId, RECUPERAR, ahora.minus(Duration.ofHours(1)));
        Instant reenvioDisponible = invitacion.map(valor -> valor.generadoEn().plus(ENFRIAMIENTO)).orElse(null);
        Instant recuperacionDisponible = acciones.ultimaAccion(operadorId, RECUPERAR)
                .map(fecha -> fecha.plus(Duration.ofMinutes(15))).orElse(null);
        int reenviosRestantes = Math.max(0, MAXIMO_POR_HORA - usadasInvitacion);
        int recuperacionesRestantes = Math.max(0, MAXIMO_POR_HORA - usadasRecuperacion);
        if (invitacion.isPresent() && reenviosRestantes == 0) {
            Instant cuotaDisponible = acciones.primeraAccion(operadorId, OPERACIONES_INVITACION,
                    ahora.minus(Duration.ofHours(1)))
                    .map(fecha -> fecha.plus(Duration.ofHours(1))).orElse(ahora.plus(Duration.ofHours(1)));
            reenvioDisponible = posterior(reenvioDisponible, cuotaDisponible);
        }
        if (recuperacionesRestantes == 0) {
            Instant cuotaDisponible = acciones.primeraAccion(operadorId, List.of(RECUPERAR),
                    ahora.minus(Duration.ofHours(1)))
                    .map(fecha -> fecha.plus(Duration.ofHours(1))).orElse(ahora.plus(Duration.ofHours(1)));
            recuperacionDisponible = posterior(recuperacionDisponible, cuotaDisponible);
        }
        boolean puedeReemitir = invitacion.filter(valor -> valor.consumidoEn() == null).isPresent()
                && reenviosRestantes > 0 && (reenvioDisponible == null || !ahora.isBefore(reenvioDisponible));
        boolean puedeRecuperar = recuperacionesRestantes > 0
                && (recuperacionDisponible == null || !ahora.isBefore(recuperacionDisponible));
        String estado = invitacion.map(valor -> estadoVisible(valor, ahora)).orElse(null);
        return new ProyeccionInvitacionOperador(
                estado,
                invitacion.map(InvitacionOperadorPersistida::generadoEn).orElse(null),
                invitacion.map(InvitacionOperadorPersistida::venceEn).orElse(null),
                invitacion.map(InvitacionOperadorPersistida::consumidoEn).orElse(null),
                reenvioDisponible,
                reenviosRestantes,
                puedeReemitir,
                recuperacionDisponible,
                recuperacionesRestantes,
                puedeRecuperar);
    }

    /**
     * Genera otra invitación si los datos del operador siguen vigentes y se respeta el límite; repetir
     * la solicitud no crea otra.
     */
    public ResultadoReemisionInvitacionOperador reemitir(
            UUID operadorId, String ifMatch, String rawIdempotencyKey) {
        String claveHash = SeguridadTokensOperador.hashClaveIdempotencia(rawIdempotencyKey);
        long revisionSolicitada = validarIfMatch(ifMatch);
        TransicionReemision transicion = transaccion.execute(estado -> prepararReemision(
                operadorId, claveHash, revisionSolicitada));
        if (transicion == null) {
            throw servicioNoDisponible();
        }
        if (transicion.preparacion() != null) {
            publicarCambioDirectorio();
            EstadoEnvioInvitacion resultado = enviar(transicion.preparacion());
            persistirResultado(transicion.preparacion(), resultado);
            transicion = new TransicionReemision(
                    null, transicion.revisionAcceso(), resultado);
        }
        ProyeccionInvitacionOperador proyeccion = consultar(operadorId);
        RespuestaReemisionInvitacionOperador respuesta = new RespuestaReemisionInvitacionOperador(
                transicion.estado(), proyeccion.puedeReemitirInvitacion(), proyeccion.reenvioDisponibleEn());
        return new ResultadoReemisionInvitacionOperador(respuesta, transicion.revisionAcceso());
    }

    private TransicionReemision prepararReemision(UUID operadorId, String claveHash, long revisionSolicitada) {
        Long empleadoId = cuentas.empleadoId(operadorId).orElse(null);
        EmpleadoEnlaceOperador empleado = bloquearEmpleadoVinculado(empleadoId);
        CuentaActivacionOperador cuenta = cuentas.bloquearCuenta(operadorId)
                .orElseThrow(() -> error(HttpStatus.NOT_FOUND, "OPERADOR_NO_ENCONTRADO", "No encontramos esta cuenta."));
        if (!java.util.Objects.equals(empleadoId, cuenta.empleadoId())
                || (empleadoId != null && (empleado == null || !"ACTIVO".equals(empleado.estado())))) {
            throw error(HttpStatus.CONFLICT, "EMPLEADO_INACTIVO",
                    "No se puede enviar una invitación mientras el empleado no esté activo.");
        }
        InvitacionOperadorPersistida invitacion = acciones.bloquearInvitacion(operadorId)
                .orElseThrow(() -> error(HttpStatus.CONFLICT, "INVITACION_NO_DISPONIBLE", "No hay una invitación activa para esta cuenta."));
        acciones.bloquearRecuperacion(operadorId);
        Optional<AccionOperadorPersistida> repetida = acciones.bloquearAccion(operadorId, REEMITIR, claveHash);
        if (repetida.isPresent()) {
            return new TransicionReemision(null, cuenta.revisionAcceso(), repetida.get().estadoEnvio());
        }
        exigirRevision(cuenta.revisionAcceso(), revisionSolicitada);
        exigirCuentaPendiente(cuenta);
        if (invitacion.consumidoEn() != null) {
            throw error(HttpStatus.CONFLICT, "INVITACION_NO_DISPONIBLE", "No hay una invitación activa para esta cuenta.");
        }
        exigirCuotaInvitacion(operadorId, invitacion.generadoEn());
        validarCorreoAntesDeCommit();

        Instant generadoEn = ahora();
        Instant venceEn = generadoEn.plus(VALIDEZ_INVITACION);
        String token = SeguridadTokensOperador.crearToken(aleatorio);
        String tokenHash = SeguridadTokensOperador.hash(token);
        if (!acciones.reemplazarInvitacion(operadorId, invitacion.tokenHash(), tokenHash,
                generadoEn, venceEn, generadoEn)
                || !acciones.insertarAccion(operadorId, REEMITIR, claveHash, generadoEn,
                        EstadoEnvioInvitacion.ENVIANDO, cuenta.revisionAcceso(), venceEn)) {
            throw error(HttpStatus.CONFLICT, "OPERACION_EN_CONFLICTO", "La invitación cambió. Actualiza la información antes de continuar.");
        }
        PreparacionInvitacionOperador preparacion = new PreparacionInvitacionOperador(
                operadorId, cuenta.correo(), token, tokenHash, venceEn, activacion.origenValidado(), REEMITIR, claveHash);
        return new TransicionReemision(preparacion, cuenta.revisionAcceso(),
                EstadoEnvioInvitacion.ENVIANDO);
    }

    @Override
    public boolean reactivacionRepetida(UUID operadorId, String rawIdempotencyKey) {
        String claveHash = SeguridadTokensOperador.hashClaveIdempotencia(rawIdempotencyKey);
        acciones.bloquearInvitacion(operadorId);
        acciones.bloquearRecuperacion(operadorId);
        return acciones.bloquearAccion(operadorId, REACTIVAR, claveHash).isPresent();
    }

    /**
     * Prepara una invitación mientras se guarda el cambio de la cuenta para mantener ambos datos de
     * acuerdo.
     */
    @Override
    public PreparacionInvitacionOperador prepararReactivacion(
            UUID operadorId, String correo, String rawIdempotencyKey) {
        String claveHash = SeguridadTokensOperador.hashClaveIdempotencia(rawIdempotencyKey);
        CuentaActivacionOperador cuenta = cuentas.bloquearCuenta(operadorId)
                .orElseThrow(() -> error(HttpStatus.NOT_FOUND, "OPERADOR_NO_ENCONTRADO", "No encontramos esta cuenta."));
        InvitacionOperadorPersistida invitacion = acciones.bloquearInvitacion(operadorId)
                .orElseThrow(() -> error(HttpStatus.CONFLICT, "INVITACION_NO_DISPONIBLE", "No hay una invitación activa para esta cuenta."));
        acciones.bloquearRecuperacion(operadorId);
        if (acciones.bloquearAccion(operadorId, REACTIVAR, claveHash).isPresent()) {
            throw error(HttpStatus.CONFLICT, "OPERACION_REPETIDA", "La cuenta ya está activa.");
        }
        if (cuenta.rol() != RolCuenta.OPERADOR || !"INACTIVA".equals(cuenta.estado())
                || cuenta.revisionAcceso() == Long.MAX_VALUE) {
            throw error(HttpStatus.CONFLICT, "OPERADOR_NO_INACTIVO", "No se puede activar esta cuenta ahora.");
        }
        exigirCuotaInvitacion(operadorId, invitacion.generadoEn());
        validarCorreoAntesDeCommit();
        Instant generadoEn = ahora();
        Instant venceEn = generadoEn.plus(VALIDEZ_INVITACION);
        String token = SeguridadTokensOperador.crearToken(aleatorio);
        String tokenHash = SeguridadTokensOperador.hash(token);
        acciones.invalidarRecuperacion(operadorId, generadoEn);
        if (!acciones.prepararInvitacion(operadorId, tokenHash, generadoEn, venceEn, generadoEn)
                || !acciones.insertarAccion(operadorId, REACTIVAR, claveHash, generadoEn,
                        EstadoEnvioInvitacion.ENVIANDO, cuenta.revisionAcceso() + 1, venceEn)) {
            throw error(HttpStatus.CONFLICT, "OPERACION_EN_CONFLICTO", "La invitación cambió. Actualiza la información antes de continuar.");
        }
        return new PreparacionInvitacionOperador(
                operadorId, correo, token, tokenHash, venceEn, activacion.origenValidado(), REACTIVAR, claveHash);
    }

    /** Prepara una nueva invitación para el correo cambiado; se envía después de guardar el cambio. */
    @Override
    public PreparacionInvitacionOperador prepararCambioCorreo(
            UUID operadorId, String correo, String rawIdempotencyKey) {
        String claveHash = SeguridadTokensOperador.hashClaveIdempotencia(rawIdempotencyKey);
        CuentaActivacionOperador cuenta = cuentas.bloquearCuenta(operadorId)
                .orElseThrow(() -> error(HttpStatus.NOT_FOUND, "OPERADOR_NO_ENCONTRADO", "No encontramos esta cuenta."));
        InvitacionOperadorPersistida invitacion = acciones.bloquearInvitacion(operadorId)
                .orElseThrow(() -> error(HttpStatus.CONFLICT, "INVITACION_NO_DISPONIBLE", "No hay una invitación activa para esta cuenta."));
        acciones.bloquearRecuperacion(operadorId);
        acciones.bloquearAcciones(operadorId);
        if (cuenta.rol() != RolCuenta.OPERADOR || !"PENDIENTE".equals(cuenta.estado())
                || cuenta.hashContrasena() != null || cuenta.revisionAcceso() == Long.MAX_VALUE
                || invitacion.consumidoEn() != null) {
            throw error(HttpStatus.CONFLICT, "OPERADOR_NO_PENDIENTE", "No se puede actualizar esta invitación ahora.");
        }
        if (acciones.bloquearAccion(operadorId, CAMBIAR_CORREO, claveHash).isPresent()) {
            throw error(HttpStatus.CONFLICT, "OPERACION_REPETIDA", "La solicitud ya se procesó.");
        }
        exigirCuotaInvitacion(operadorId, invitacion.generadoEn());
        activacion.origenValidado();
        Instant generadoEn = ahora();
        Instant venceEn = generadoEn.plus(VALIDEZ_INVITACION);
        String token = SeguridadTokensOperador.crearToken(aleatorio);
        String tokenHash = SeguridadTokensOperador.hash(token);
        acciones.invalidarRecuperacion(operadorId, generadoEn);
        if (!acciones.reemplazarInvitacion(operadorId, invitacion.tokenHash(), tokenHash,
                generadoEn, venceEn, generadoEn)
                || !acciones.insertarAccion(operadorId, CAMBIAR_CORREO, claveHash, generadoEn,
                        EstadoEnvioInvitacion.ENVIANDO, cuenta.revisionAcceso() + 1, venceEn)) {
            throw error(HttpStatus.CONFLICT, "OPERACION_EN_CONFLICTO", "La invitación cambió. Actualiza la información antes de continuar.");
        }
        return new PreparacionInvitacionOperador(
                operadorId, correo, token, tokenHash, venceEn, activacion.origenValidado(), CAMBIAR_CORREO, claveHash);
    }

    /** Intenta enviar una invitación al correo nuevo y registra el resultado de ese único intento. */
    @Override
    public EstadoEnvioInvitacion enviarCambioCorreo(PreparacionInvitacionOperador preparacion) {
        EstadoEnvioInvitacion resultado = enviar(preparacion);
        persistirResultado(preparacion, resultado);
        return resultado;
    }

    /** Deja sin efecto los enlaces pendientes cuando se guarda el cambio de la cuenta. */
    @Override
    public void invalidarPendientes(UUID operadorId) {
        acciones.bloquearInvitacion(operadorId);
        acciones.bloquearRecuperacion(operadorId);
        acciones.bloquearAcciones(operadorId);
        Instant ahora = ahora();
        acciones.invalidarInvitacion(operadorId, ahora);
        acciones.invalidarRecuperacion(operadorId, ahora);
    }

    /** Intenta enviar una invitación después de que se guardó la reactivación de la cuenta. */
    @Override
    public EstadoEnvioInvitacion enviarReactivacion(PreparacionInvitacionOperador preparacion) {
        EstadoEnvioInvitacion resultado = enviar(preparacion);
        persistirResultado(preparacion, resultado);
        return resultado;
    }

    private void persistirResultado(PreparacionInvitacionOperador preparacion, EstadoEnvioInvitacion estado) {
        Boolean visible = transaccion.execute(transaccionEstado -> {
            boolean cambioVisible = acciones.actualizarEstadoInvitacion(
                    preparacion.operadorId(), preparacion.tokenHash(), estado);
            acciones.actualizarEstadoAccion(preparacion.operadorId(), preparacion.operacion(),
                    preparacion.claveHash(), estado);
            return cambioVisible;
        });
        if (Boolean.TRUE.equals(visible)) {
            publicarCambioDirectorio();
        }
    }

    private EstadoEnvioInvitacion enviar(PreparacionInvitacionOperador preparacion) {
        try {
            EstadoEnvioInvitacion estado = notificador.enviar(
                    preparacion.correo(), enlaceActivacion(preparacion.origen(), preparacion.token()));
            return estado == null || estado == EstadoEnvioInvitacion.ENVIANDO
                    ? EstadoEnvioInvitacion.DESCONOCIDO : estado;
        } catch (RuntimeException excepcion) {
            return EstadoEnvioInvitacion.DESCONOCIDO;
        }
    }

    private void validarCorreoAntesDeCommit() {
        activacion.origenValidado();
    }

    private EmpleadoEnlaceOperador bloquearEmpleadoVinculado(Long empleadoId) {
        if (empleadoId == null) {
            return null;
        }
        if (empleados == null) {
            throw servicioNoDisponible();
        }
        return empleados.bloquearPorId(empleadoId).orElse(null);
    }

    private void exigirCuotaInvitacion(UUID operadorId, Instant ultimaGeneracion) {
        Instant ahora = ahora();
        Instant enfriamientoHasta = ultimaGeneracion.plus(ENFRIAMIENTO);
        if (ahora.isBefore(enfriamientoHasta)) {
            throw new ErrorLimitacionAccionOperador("REENVIO_EN_ENFRIAMIENTO",
                        "Espera un momento antes de enviar otra invitación.", segundosHasta(ahora, enfriamientoHasta));
        }
        int usadas = contarAccionesInvitacion(operadorId, ahora.minus(Duration.ofHours(1)));
        if (usadas >= MAXIMO_POR_HORA) {
            Instant desde = ahora.minus(Duration.ofHours(1));
            Instant disponible = acciones.primeraAccion(operadorId, OPERACIONES_INVITACION, desde)
                    .map(fecha -> fecha.plus(Duration.ofHours(1))).orElse(ahora.plus(Duration.ofHours(1)));
            throw new ErrorLimitacionAccionOperador("REENVIO_LIMITE_ALCANZADO",
                    "Ya se enviaron varias invitaciones. Inténtalo más tarde.", segundosHasta(ahora, disponible));
        }
    }

    private int contarAccionesInvitacion(UUID operadorId, Instant desde) {
        return acciones.contarAcciones(operadorId, REEMITIR, desde)
                + acciones.contarAcciones(operadorId, REACTIVAR, desde)
                + acciones.contarAcciones(operadorId, CAMBIAR_CORREO, desde);
    }

    private void exigirCuentaPendiente(CuentaActivacionOperador cuenta) {
        if (cuenta.rol() != RolCuenta.OPERADOR || !"PENDIENTE".equals(cuenta.estado())
                || cuenta.hashContrasena() != null) {
            throw error(HttpStatus.CONFLICT, "OPERADOR_NO_PENDIENTE", "No se puede activar esta cuenta ahora.");
        }
    }

    private static void exigirRevision(long revisionActual, long revisionSolicitada) {
        if (revisionActual != revisionSolicitada) {
            throw error(HttpStatus.PRECONDITION_FAILED, "REVISION_OBSOLETA",
                    "La información de la cuenta cambió. Actualízala antes de continuar.");
        }
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

    private static String estadoVisible(InvitacionOperadorPersistida invitacion, Instant ahora) {
        if (invitacion.consumidoEn() != null) {
            return "CONSUMIDA";
        }
        return !ahora.isBefore(invitacion.venceEn()) ? "EXPIRADA" : invitacion.estadoEnvio().name();
    }

    private static long segundosHasta(Instant ahora, Instant limite) {
        long segundos = Duration.between(ahora, limite).getSeconds();
        return Duration.between(ahora, limite).getNano() > 0 ? segundos + 1 : Math.max(1, segundos);
    }

    private static Instant posterior(Instant primera, Instant segunda) {
        if (primera == null || segunda.isAfter(primera)) {
            return segunda;
        }
        return primera;
    }

    private static String enlaceActivacion(String origen, String token) {
        return origen + "/activar-operador#" + token;
    }

    private Instant ahora() {
        return reloj.instant().truncatedTo(ChronoUnit.MICROS);
    }

    private void publicarCambioDirectorio() {
        try {
            eventos.publicarDirectorioOperadorActualizado();
        } catch (RuntimeException excepcion) {
            System.getLogger(ServicioAdministracionInvitacionesOperador.class.getName()).log(
                    System.Logger.Level.WARNING, "No se pudo publicar la actualización del directorio de operadores.");
        }
    }

    private static ErrorConfiguracion servicioNoDisponible() {
        return error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                "No pudimos cargar la invitación. Inténtalo más tarde.");
    }

    private static ErrorConfiguracion error(HttpStatus estado, String codigo, String mensaje) {
        return new ErrorConfiguracion(estado, mensaje, codigo);
    }

    private record TransicionReemision(
            PreparacionInvitacionOperador preparacion,
            long revisionAcceso,
            EstadoEnvioInvitacion estado) {
    }
}
