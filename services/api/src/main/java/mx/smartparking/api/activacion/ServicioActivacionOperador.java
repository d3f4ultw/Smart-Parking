package mx.smartparking.api.activacion;

import java.net.URI;
import java.net.URISyntaxException;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Locale;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.correo.NotificadorInvitacionOperador;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import mx.smartparking.api.empleados.coordinacion.EmpleadoEnlaceOperador;
import mx.smartparking.api.empleados.coordinacion.PuertoEmpleadosOperador;
import mx.smartparking.api.persistencia.CuentaActivacionOperador;
import mx.smartparking.api.persistencia.InvitacionOperadorPersistida;
import mx.smartparking.api.persistencia.RepositorioActivacionOperador;
import mx.smartparking.api.persistencia.RepositorioActivacionOperador.ResultadoActualizacionEnvio;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Prepara las invitaciones de operadores y permite comprobarlas o activar la cuenta con una contraseña. */
@Service
public final class ServicioActivacionOperador {

    private static final java.time.Duration DURACION_INVITACION = java.time.Duration.ofHours(2);
    private static final String CODIGO_INVITACION_INVALIDA = "INVITACION_NO_VALIDA";
    private static final String MENSAJE_INVITACION_INVALIDA = "Este enlace venció o ya se usó. Pide otra invitación al propietario.";
    private static final Set<String> PERFILES_HTTP_PERMITIDOS = Set.of("local", "dev", "test");

    private final RepositorioActivacionOperador repositorio;
    private final NotificadorInvitacionOperador notificador;
    private final PasswordEncoder codificador;
    private final ProteccionIntentosActivacion proteccionIntentos;
    private final TransactionTemplate transaccion;
    private final Clock reloj;
    private final SecureRandom aleatorio;
    private final String origenConfigurado;
    private final boolean permitirHttpLocal;
    private final Set<String> perfilesActivos;
    private ServicioEventosAdministracion eventos;
    private PuertoEmpleadosOperador empleados;

    @Autowired
    void establecerEventos(ServicioEventosAdministracion eventos) { this.eventos = eventos; }

    @Autowired
    void establecerEmpleados(PuertoEmpleadosOperador empleados) { this.empleados = empleados; }

    @Autowired
    public ServicioActivacionOperador(
            RepositorioActivacionOperador repositorio,
            NotificadorInvitacionOperador notificador,
            PasswordEncoder codificador,
            ProteccionIntentosActivacion proteccionIntentos,
            PlatformTransactionManager administradorTransacciones,
            @Value("${smartparking.operadores.origen-activacion:}") String origenConfigurado,
            @Value("${smartparking.operadores.permitir-http-local:false}") boolean permitirHttpLocal,
            Environment entorno) {
        this(repositorio, notificador, codificador, proteccionIntentos, administradorTransacciones,
                origenConfigurado, permitirHttpLocal, Set.of(entorno.getActiveProfiles()),
                Clock.systemUTC(), new SecureRandom());
    }

    /**
     * Permite crear este servicio con sus opciones anteriores sin habilitar por defecto direcciones
     * inseguras.
     */
    public ServicioActivacionOperador(
            RepositorioActivacionOperador repositorio,
            NotificadorInvitacionOperador notificador,
            PasswordEncoder codificador,
            ProteccionIntentosActivacion proteccionIntentos,
            PlatformTransactionManager administradorTransacciones,
            String origenConfigurado) {
        this(repositorio, notificador, codificador, proteccionIntentos, administradorTransacciones,
                origenConfigurado, false, Set.of(), Clock.systemUTC(), new SecureRandom());
    }

    ServicioActivacionOperador(
            RepositorioActivacionOperador repositorio,
            NotificadorInvitacionOperador notificador,
            PasswordEncoder codificador,
            ProteccionIntentosActivacion proteccionIntentos,
            PlatformTransactionManager administradorTransacciones,
            String origenConfigurado,
            Clock reloj,
            SecureRandom aleatorio) {
        this(repositorio, notificador, codificador, proteccionIntentos, administradorTransacciones,
                origenConfigurado, false, Set.of(), reloj, aleatorio);
    }

    ServicioActivacionOperador(
            RepositorioActivacionOperador repositorio,
            NotificadorInvitacionOperador notificador,
            PasswordEncoder codificador,
            ProteccionIntentosActivacion proteccionIntentos,
            PlatformTransactionManager administradorTransacciones,
            String origenConfigurado,
            Set<String> perfilesActivos,
            Clock reloj,
            SecureRandom aleatorio) {
        this(repositorio, notificador, codificador, proteccionIntentos, administradorTransacciones,
                origenConfigurado, false, perfilesActivos, reloj, aleatorio);
    }

    ServicioActivacionOperador(
            RepositorioActivacionOperador repositorio,
            NotificadorInvitacionOperador notificador,
            PasswordEncoder codificador,
            ProteccionIntentosActivacion proteccionIntentos,
            PlatformTransactionManager administradorTransacciones,
            String origenConfigurado,
            boolean permitirHttpLocal,
            Set<String> perfilesActivos,
            Clock reloj,
            SecureRandom aleatorio) {
        this.repositorio = repositorio;
        this.notificador = notificador;
        this.codificador = codificador;
        this.proteccionIntentos = proteccionIntentos;
        this.transaccion = new TransactionTemplate(administradorTransacciones);
        this.origenConfigurado = origenConfigurado;
        this.permitirHttpLocal = permitirHttpLocal;
        this.reloj = reloj;
        this.aleatorio = aleatorio;
        this.perfilesActivos = perfilesActivos.stream()
                .map(perfil -> perfil.toLowerCase(Locale.ROOT))
                .collect(Collectors.toUnmodifiableSet());
    }

    /** Comprueba que la dirección de los enlaces sea segura antes de guardar una nueva cuenta. */
    public void validarOrigenConfigurado() {
        obtenerOrigenValidado();
    }

    /** Entrega la dirección segura que se usará para formar los enlaces de activación y recuperación. */
    public String origenValidado() {
        return obtenerOrigenValidado();
    }
    /**
     * Prepara la invitación al registrar la cuenta y guarda solo una huella del código, no el código
     * original.
     */
    public PreparacionInvitacionOperador prepararInicial(UUID operadorId, String correo) {
        String origen = obtenerOrigenValidado();
        String token = SeguridadTokensOperador.crearToken(aleatorio);
        Instant generadoEn = ahora();
        String tokenHash = SeguridadTokensOperador.hash(token);
        Instant venceEn = generadoEn.plus(DURACION_INVITACION);
        repositorio.crearInicial(operadorId, tokenHash, generadoEn, venceEn);
        return new PreparacionInvitacionOperador(operadorId, correo, token, tokenHash, venceEn, origen);
    }
    /** Intenta enviar la invitación una sola vez después de guardar la cuenta y registra si pudo enviarse. */
    public EstadoEnvioInvitacion enviarInicial(PreparacionInvitacionOperador preparacion) {
        if (preparacion == null) {
            throw new IllegalArgumentException("Se requiere la preparación de la invitación.");
        }
        EstadoEnvioInvitacion resultado = intentarEnviar(preparacion.correo(),
                enlace(preparacion.origen(), preparacion.token()));
        return persistirResultado(preparacion.operadorId(), preparacion.tokenHash(), resultado);
    }
    /** Indica si la invitación todavía puede usarse sin gastarla ni mostrar datos de la cuenta. */
    public RespuestaValidacionActivacionOperador validar(String token) {
        String tokenHash = SeguridadTokensOperador.hash(token == null ? "" : token);
        exigirPermitido(tokenHash);
        if (!SeguridadTokensOperador.tokenTieneFormato(token)) {
            registrarFallo(tokenHash);
            throw invitacionInvalida();
        }
        Optional<InvitacionOperadorPersistida> invitacion = repositorio.buscarPorTokenHash(tokenHash);
        Instant ahora = ahora();
        if (invitacion.isEmpty() || !esVigente(invitacion.get(), tokenHash, ahora)) {
            registrarFallo(tokenHash);
            throw invitacionInvalida();
        }
        return new RespuestaValidacionActivacionOperador(true);
    }
    /** Guarda la contraseña, activa la cuenta y deja de aceptar el enlace como una sola operación. */
    public void completar(SolicitudCompletarActivacionOperador solicitud) {
        if (solicitud == null) {
            throw error(HttpStatus.BAD_REQUEST, "SOLICITUD_NO_VALIDA", "Escribe una contraseña y repítela en el segundo campo.");
        }
        String token = solicitud.token();
        String tokenHash = SeguridadTokensOperador.hash(token == null ? "" : token);
        exigirPermitido(tokenHash);
        if (!SeguridadTokensOperador.tokenTieneFormato(token)) {
            registrarFallo(tokenHash);
            throw invitacionInvalida();
        }
        Optional<InvitacionOperadorPersistida> candidata = repositorio.buscarPorTokenHash(tokenHash);
        if (candidata.isEmpty() || !esVigente(candidata.get(), tokenHash, ahora())) {
            registrarFallo(tokenHash);
            throw invitacionInvalida();
        }
        validarContrasenas(solicitud, tokenHash);

        String hashContrasena = codificador.encode(solicitud.contrasena());
        Boolean empleadoVinculado = transaccion.execute(estado -> activarBajoBloqueo(candidata.get().operadorId(),
                tokenHash, hashContrasena));
        if (empleadoVinculado == null) {
            throw servicioNoDisponible();
        }
        proteccionIntentos.registrarExito(tokenHash);
        publicarCambioDirectorio(empleadoVinculado);
    }
    private Boolean activarBajoBloqueo(UUID operadorId, String tokenHash, String hashContrasena) {
        Long empleadoId = repositorio.empleadoId(operadorId).orElse(null);
        EmpleadoEnlaceOperador empleado = null;
        if (empleadoId != null) {
            if (empleados == null) {
                throw servicioNoDisponible();
            }
            empleado = empleados.bloquearPorId(empleadoId).orElse(null);
            if (empleado == null || !"ACTIVO".equals(empleado.estado())) {
                registrarFallo(tokenHash);
                throw invitacionInvalida();
            }
        }
        CuentaActivacionOperador cuenta = repositorio.bloquearCuenta(operadorId).orElse(null);
        InvitacionOperadorPersistida invitacion = repositorio.bloquearInvitacion(operadorId).orElse(null);
        Instant ahora = ahora();
        if (!cuentaPendiente(cuenta) || !java.util.Objects.equals(cuenta.empleadoId(), empleadoId)
                || invitacion == null || !esVigente(invitacion, tokenHash, ahora)) {
            registrarFallo(tokenHash);
            throw invitacionInvalida();
        }
        if (cuenta.revisionAcceso() == Long.MAX_VALUE
                || (empleado != null && empleado.revision() == Long.MAX_VALUE)) {
            throw servicioNoDisponible();
        }
        if (!repositorio.activar(operadorId, cuenta.revisionAcceso(), hashContrasena, ahora)
                || !repositorio.consumir(operadorId, tokenHash, ahora)) {
            registrarFallo(tokenHash);
            throw invitacionInvalida();
        }
        if (empleado != null && !empleados.incrementarRevision(empleado.id(), empleado.revision())) {
            throw servicioNoDisponible();
        }
        return empleado != null;
    }

    private EstadoEnvioInvitacion persistirResultado(
            UUID operadorId, String tokenHash, EstadoEnvioInvitacion resultado) {
        Optional<ResultadoActualizacionEnvio> actualizacion = repositorio.actualizarResultadoEnvio(
                operadorId, tokenHash, resultado);
        if (actualizacion.filter(actual -> actual.cambioAplicado() && actual.cambioVisible()).isPresent()) {
            publicarCambioDirectorio();
        }
        return actualizacion.map(ResultadoActualizacionEnvio::estado)
                .orElse(EstadoEnvioInvitacion.DESCONOCIDO);
    }

    private void publicarCambioDirectorio() {
        publicarCambioDirectorio(false);
    }

    private void publicarCambioDirectorio(boolean empleadoVinculado) {
        try {
            eventos.publicarDirectorioOperadorActualizado();
        } catch (RuntimeException excepcion) {
            System.getLogger(ServicioActivacionOperador.class.getName()).log(
                    System.Logger.Level.WARNING, "No se pudo publicar la actualización del directorio de operadores.");
        }
        if (empleadoVinculado) {
            try {
                eventos.publicarDirectorioActualizado();
            } catch (RuntimeException excepcion) {
                System.getLogger(ServicioActivacionOperador.class.getName()).log(
                        System.Logger.Level.WARNING, "No se pudo publicar la actualización del directorio de empleados.");
            }
        }
    }

    private EstadoEnvioInvitacion intentarEnviar(String correo, String enlace) {
        try {
            EstadoEnvioInvitacion resultado = notificador.enviar(correo, enlace);
            return resultado == null || resultado == EstadoEnvioInvitacion.ENVIANDO
                    ? EstadoEnvioInvitacion.DESCONOCIDO
                    : resultado;
        } catch (RuntimeException excepcion) {
            return EstadoEnvioInvitacion.DESCONOCIDO;
        }
    }

    private void validarContrasenas(SolicitudCompletarActivacionOperador solicitud, String tokenHash) {
        String contrasena = solicitud.contrasena();
        String confirmacion = solicitud.confirmarContrasena();
        if (contrasena == null || contrasena.codePointCount(0, contrasena.length()) < 10
                || !contrasena.equals(confirmacion)) {
            registrarFallo(tokenHash);
            throw error(HttpStatus.BAD_REQUEST, "CONTRASENA_NO_VALIDA",
                    "Elige una contraseña más larga y repítela igual en ambos campos.");
        }
    }

    private void exigirPermitido(String tokenHash) {
        if (!proteccionIntentos.permitido(tokenHash)) {
            throw error(HttpStatus.TOO_MANY_REQUESTS, "INTENTOS_ACTIVACION_LIMITADOS",
                    "Por seguridad, espera 15 minutos antes de intentarlo otra vez.");
        }
    }

    private void registrarFallo(String tokenHash) {
        proteccionIntentos.registrarFallo(tokenHash);
    }

    private Instant ahora() {
        return reloj.instant().truncatedTo(ChronoUnit.MICROS);
    }

    private static boolean esVigente(InvitacionOperadorPersistida invitacion, String tokenHash, Instant ahora) {
        return SeguridadTokensOperador.hashesIguales(invitacion.tokenHash(), tokenHash)
                && invitacion.consumidoEn() == null
                && ahora.isBefore(invitacion.venceEn());
    }

    private static boolean cuentaPendiente(CuentaActivacionOperador cuenta) {
        return cuenta != null && cuenta.rol() == RolCuenta.OPERADOR && "PENDIENTE".equals(cuenta.estado())
                && cuenta.hashContrasena() == null;
    }

    private String obtenerOrigenValidado() {
        if (origenConfigurado == null || origenConfigurado.isBlank()) {
            throw origenNoDisponible();
        }
        try {
            URI uri = new URI(origenConfigurado.strip());
            String esquema = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
            String host = uri.getHost();
            int puerto = uri.getPort();
            if (!uri.isAbsolute() || host == null || host.isBlank() || uri.getUserInfo() != null
                    || uri.getQuery() != null || uri.getFragment() != null
                    || (puerto != -1 && (puerto < 1 || puerto > 65_535))
                    || !(uri.getPath().isEmpty() || "/".equals(uri.getPath()))) {
                throw origenNoDisponible();
            }
            String hostNormalizado = host.replace("[", "").replace("]", "").toLowerCase(Locale.ROOT);
            if (!"https".equals(esquema)
                    && !("http".equals(esquema) && httpPermitido(hostNormalizado))) {
                throw origenNoDisponible();
            }
            return new URI(esquema, null, host, uri.getPort(), null, null, null).toASCIIString();
        } catch (URISyntaxException excepcion) {
            throw origenNoDisponible();
        }
    }

    private boolean httpPermitido(String host) {
        if (!permitirHttpLocal || perfilesActivos.isEmpty()
                || !PERFILES_HTTP_PERMITIDOS.containsAll(perfilesActivos)) {
            return false;
        }
        return host.equals("localhost") || host.equals("127.0.0.1") || host.equals("::1");
    }

    private static String enlace(String origen, String token) {
        return origen + "/activar-operador#" + token;
    }

    private static ErrorConfiguracion invitacionInvalida() {
        return error(HttpStatus.GONE, CODIGO_INVITACION_INVALIDA, MENSAJE_INVITACION_INVALIDA);
    }

    private static ErrorConfiguracion origenNoDisponible() {
        return error(HttpStatus.SERVICE_UNAVAILABLE, "ORIGEN_ACTIVACION_NO_CONFIGURADO",
                "No pudimos activar la cuenta en este momento. Inténtalo más tarde.");
    }

    private static ErrorConfiguracion servicioNoDisponible() {
        return error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                "No pudimos completar esto ahora. Inténtalo más tarde.");
    }

    private static ErrorConfiguracion error(HttpStatus estado, String codigo, String mensaje) {
        return new ErrorConfiguracion(estado, mensaje, codigo);
    }

}
