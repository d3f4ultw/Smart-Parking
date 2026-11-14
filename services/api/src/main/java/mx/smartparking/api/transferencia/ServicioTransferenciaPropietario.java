package mx.smartparking.api.transferencia;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.HexFormat;
import java.util.UUID;
import mx.smartparking.api.configuracion.DatosConfiguracion;
import mx.smartparking.api.configuracion.DatosPropietario;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.EstadoConfiguracion;
import mx.smartparking.api.configuracion.ResultadoConfiguracion;
import mx.smartparking.api.configuracion.ResultadoTransferencia;
import mx.smartparking.api.configuracion.SolicitudConfiguracion;
import mx.smartparking.api.correo.EstadoAviso;
import mx.smartparking.api.correo.NotificadorCorreo;
import mx.smartparking.api.persistencia.ConfiguracionPersistida;
import mx.smartparking.api.persistencia.RepositorioConfiguracion;
import mx.smartparking.api.persistencia.RepositorioConfiguracion.TipoAviso;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Administra el cambio de propietario, la recuperación del permiso y el retiro del acceso anterior. */
@Service
public class ServicioTransferenciaPropietario {

    private static final Duration DURACION_GRANT = Duration.ofMinutes(30);
    private static final String GRANT_INVALIDO = "Este enlace para cambiar de propietario venció o ya no funciona.";

    private final RepositorioConfiguracion repositorio;
    private final RepositorioCuentas cuentas;
    private final PasswordEncoder codificador;
    private final GestorSesionesPropietario sesiones;
    private final NotificadorCorreo correo;
    private final ProteccionIntentosTransferencia intentos;
    private final TransactionTemplate transaccion;
    private final Clock reloj;
    private final SecureRandom aleatorio;

    @Autowired
    public ServicioTransferenciaPropietario(
            RepositorioConfiguracion repositorio,
            RepositorioCuentas cuentas,
            PasswordEncoder codificador,
            GestorSesionesPropietario sesiones,
            NotificadorCorreo correo,
            ProteccionIntentosTransferencia intentos,
            PlatformTransactionManager administradorTransacciones) {
        this(repositorio, cuentas, codificador, sesiones, correo, intentos,
                administradorTransacciones, Clock.systemUTC(), new SecureRandom());
    }

    public ServicioTransferenciaPropietario(
            RepositorioConfiguracion repositorio,
            RepositorioCuentas cuentas,
            PasswordEncoder codificador,
            GestorSesionesPropietario sesiones,
            NotificadorCorreo correo,
            ProteccionIntentosTransferencia intentos,
            PlatformTransactionManager administradorTransacciones,
            Clock reloj,
            SecureRandom aleatorio) {
        this.repositorio = repositorio;
        this.cuentas = cuentas;
        this.codificador = codificador;
        this.sesiones = sesiones;
        this.correo = correo;
        this.intentos = intentos;
        this.transaccion = new TransactionTemplate(administradorTransacciones);
        this.reloj = reloj;
        this.aleatorio = aleatorio;
    }

    /**
     * comprueba la contraseña administrativa, retira el acceso vigente
     * y abre un plazo para completar el cambio de propietario
     */
    public ResultadoTransferencia iniciarTransferencia(
            String contrasenaAdministrativa, long revisionEsperada, long revisionPropietario,
            String claveIdempotencia, String origenRemoto) {
        exigirPermitido(ProteccionIntentosTransferencia.Operacion.INICIO, origenRemoto,
                "No se pudo completar el cambio de propietario. Inténtalo de nuevo más tarde.");
        if (contrasenaAdministrativa == null || contrasenaAdministrativa.isEmpty()) {
            intentos.registrarFallo(ProteccionIntentosTransferencia.Operacion.INICIO, origenRemoto);
            throw new ErrorConfiguracion(HttpStatus.FORBIDDEN,
                    "No se pudo completar el cambio de propietario. Inténtalo de nuevo más tarde.");
        }
        String claveHash = hashClaveIdempotencia(claveIdempotencia);
        UUID operacionId = UUID.randomUUID();
        UUID transferId = UUID.randomUUID();
        String grant = crearGrant();
        String hashGrant = hashSecreto(grant);
        TransicionTransferencia cambio = transaccion.execute(status -> {
            ConfiguracionPersistida actual = repositorio.bloquear();
            exigirPropietarioActivo(actual, revisionPropietario);
            exigirRevision(actual, revisionEsperada);
            if (!codificador.matches(contrasenaAdministrativa, actual.hashContrasenaAdministrativa())) {
                intentos.registrarFallo(ProteccionIntentosTransferencia.Operacion.INICIO, origenRemoto);
                throw new ErrorConfiguracion(HttpStatus.FORBIDDEN,
                        "No se pudo completar el cambio de propietario. Inténtalo de nuevo más tarde.");
            }
            var dueno = cuentas.duenoActual().orElseThrow(() ->
                    new ErrorConfiguracion(HttpStatus.CONFLICT, "No encontramos al propietario actual."));
            Instant vence = reloj.instant().plus(DURACION_GRANT);
            cuentas.desactivar(dueno.id());
            repositorio.iniciarTransferencia(transferId, hashGrant, vence,
                    actual.hashContrasenaAdministrativa(), actual.revision() + 1,
                    actual.revisionPropietario() + 1, operacionId, claveHash);
            return new TransicionTransferencia(
                    new ResultadoTransferencia(EstadoConfiguracion.TRANSFERENCIA_PENDIENTE,
                            transferId, grant, vence, null), actual.revisionPropietario(),
                    dueno.correo(), dueno.nombreCompleto(),
                    actual.nombreEstacionamiento(), operacionId);
        });
        intentos.registrarExito(ProteccionIntentosTransferencia.Operacion.INICIO, origenRemoto);
        try {
            sesiones.revocarRevision(cambio.revisionPropietarioAnterior());
        } catch (RuntimeException excepcion) {
            // La revisión en base de datos sigue bloqueando las sesiones anteriores.
        }
        EstadoAviso aviso = notificarDesvinculacion(cambio);
        guardarEstadoAviso(cambio.operacionId(), TipoAviso.TRANSFERENCIA, aviso);
        ResultadoTransferencia resultado = cambio.resultado();
        return new ResultadoTransferencia(resultado.estado(), resultado.transferenciaId(),
                resultado.grant(), resultado.venceEn(), aviso);
    }

    /**
     * reemite una autorización limitada para concluir una transferencia pendiente
     * sin volver a activar al propietario anterior
     */
    public ResultadoTransferencia recuperarTransferencia(String contrasenaAdministrativa, String origenRemoto) {
        exigirPermitido(ProteccionIntentosTransferencia.Operacion.RECUPERACION, origenRemoto,
                "No se pudo completar el cambio de propietario. Inténtalo de nuevo más tarde.");
        if (contrasenaAdministrativa == null || contrasenaAdministrativa.isEmpty()) {
            intentos.registrarFallo(ProteccionIntentosTransferencia.Operacion.RECUPERACION, origenRemoto);
            throw new ErrorConfiguracion(HttpStatus.FORBIDDEN,
                    "No se pudo completar el cambio de propietario. Inténtalo de nuevo más tarde.");
        }
        String grant = crearGrant();
        String hashGrant = hashSecreto(grant);
        ResultadoTransferencia resultado = transaccion.execute(status -> {
            ConfiguracionPersistida actual = repositorio.bloquear();
            exigirEstado(actual, EstadoConfiguracion.TRANSFERENCIA_PENDIENTE);
            if (!codificador.matches(contrasenaAdministrativa, actual.hashRecuperacionTransferencia())) {
                intentos.registrarFallo(ProteccionIntentosTransferencia.Operacion.RECUPERACION, origenRemoto);
                throw new ErrorConfiguracion(HttpStatus.FORBIDDEN,
                        "No se pudo completar el cambio de propietario. Inténtalo de nuevo más tarde.");
            }
            Instant vence = reloj.instant().plus(DURACION_GRANT);
            repositorio.reemitirGrant(hashGrant, vence, actual.revision() + 1);
            return new ResultadoTransferencia(EstadoConfiguracion.TRANSFERENCIA_PENDIENTE,
                    actual.transferId(), grant, vence, null);
        });
        intentos.registrarExito(ProteccionIntentosTransferencia.Operacion.RECUPERACION, origenRemoto);
        return resultado;
    }

    /**
     * valida la autorización vigente y guarda los datos del nuevo propietario
     * envía el aviso de bienvenida después de confirmar los cambios
     */
    public ResultadoConfiguracion completarTransferencia(
            String grant, SolicitudConfiguracion solicitud, String claveIdempotencia, String origenRemoto) {
        exigirPermitido(ProteccionIntentosTransferencia.Operacion.GRANT, origenRemoto, GRANT_INVALIDO);
        DatosConfiguracion datos = validarSolicitud(solicitud);
        if (grant == null || grant.isBlank()) {
            intentos.registrarFallo(ProteccionIntentosTransferencia.Operacion.GRANT, origenRemoto);
            throw new ErrorConfiguracion(HttpStatus.FORBIDDEN, GRANT_INVALIDO);
        }
        String claveHash = hashClaveIdempotencia(claveIdempotencia);
        String hashAcceso = codificador.encode(datos.propietario().contrasenaAcceso());
        String hashAdministrativa = codificador.encode(datos.propietario().contrasenaAdministrativa());
        UUID operacionId = UUID.randomUUID();
        TransicionBienvenida cambio = transaccion.execute(status -> {
            ConfiguracionPersistida actual = repositorio.bloquear();
            if (actual.estado() == EstadoConfiguracion.CONFIGURADA
                    && coincideClave(actual, claveHash)) {
                return new TransicionBienvenida(new ResultadoConfiguracion(actual.estado(),
                        actual.revision(), avisoPersistido(actual.estadoAvisoBienvenida())), null, null);
            }
            exigirEstado(actual, EstadoConfiguracion.TRANSFERENCIA_PENDIENTE);
            if (!hashesIguales(actual.hashGrantTransferencia(), hashSecreto(grant))
                    || actual.grantVenceEn() == null || !reloj.instant().isBefore(actual.grantVenceEn())) {
                intentos.registrarFallo(ProteccionIntentosTransferencia.Operacion.GRANT, origenRemoto);
                throw new ErrorConfiguracion(HttpStatus.FORBIDDEN, GRANT_INVALIDO);
            }
            UUID cuentaId = cuentas.crearDueno(datos, hashAcceso);
            repositorio.completarTransferencia(datos, hashAdministrativa, cuentaId,
                    actual.revision() + 1, actual.revisionPropietario() + 1, operacionId, claveHash);
            return new TransicionBienvenida(new ResultadoConfiguracion(EstadoConfiguracion.CONFIGURADA,
                    actual.revision() + 1, null), operacionId, datos);
        });
        intentos.registrarExito(ProteccionIntentosTransferencia.Operacion.GRANT, origenRemoto);
        if (cambio.datos() == null) {
            return cambio.resultado();
        }
        EstadoAviso aviso = enviarBienvenida(cambio.datos());
        guardarEstadoAviso(cambio.operacionId(), TipoAviso.BIENVENIDA, aviso);
        return new ResultadoConfiguracion(EstadoConfiguracion.CONFIGURADA,
                cambio.resultado().revision(), aviso);
    }

    private void exigirPermitido(ProteccionIntentosTransferencia.Operacion operacion, String origen, String mensaje) {
        if (!intentos.permitido(operacion, origen)) {
            throw new ErrorConfiguracion(HttpStatus.FORBIDDEN, mensaje);
        }
    }

    private void exigirPropietarioActivo(ConfiguracionPersistida actual, long revision) {
        if (actual.estado() != EstadoConfiguracion.CONFIGURADA || actual.revisionPropietario() != revision) {
            throw new ErrorConfiguracion(HttpStatus.UNAUTHORIZED, "Tu acceso venció. Inicia sesión de nuevo.");
        }
    }

    private static void exigirEstado(ConfiguracionPersistida actual, EstadoConfiguracion estado) {
        if (actual.estado() != estado) {
            throw new ErrorConfiguracion(HttpStatus.CONFLICT,
                    "No se puede hacer este cambio ahora. Actualiza la pantalla e inténtalo de nuevo.");
        }
    }

    private static void exigirRevision(ConfiguracionPersistida actual, long revision) {
        if (actual.revision() != revision) {
            throw new ErrorConfiguracion(HttpStatus.PRECONDITION_FAILED,
                    "La información cambió. Actualiza la pantalla antes de continuar.");
        }
    }

    public static boolean coincideClave(ConfiguracionPersistida actual, String hashClave) {
        return hashesIguales(actual.ultimaClaveIdempotenciaHash(), hashClave);
    }

    public static String hashClaveIdempotencia(String clave) {
        if (clave == null || clave.strip().length() < 16 || clave.length() > 200
                || clave.contains("\n") || clave.contains("\r")) {
            throw new ErrorConfiguracion(HttpStatus.BAD_REQUEST,
                    "No pudimos completar el cambio. Actualiza la pantalla e inténtalo de nuevo.");
        }
        return hashSecreto(clave);
    }

    private static String hashSecreto(String secreto) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(secreto.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException("No pudimos completar la acción en este momento.", excepcion);
        }
    }

    private static boolean hashesIguales(String esperado, String presentado) {
        return esperado != null && presentado != null && MessageDigest.isEqual(
                esperado.getBytes(StandardCharsets.US_ASCII), presentado.getBytes(StandardCharsets.US_ASCII));
    }

    private String crearGrant() {
        byte[] bytes = new byte[32];
        aleatorio.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private static DatosConfiguracion validarSolicitud(SolicitudConfiguracion solicitud) {
        try {
            if (solicitud == null) {
                throw new IllegalArgumentException("Completa los datos del estacionamiento.");
            }
            return solicitud.validar();
        } catch (IllegalArgumentException excepcion) {
            throw new ErrorConfiguracion(HttpStatus.BAD_REQUEST, excepcion.getMessage());
        }
    }

    private EstadoAviso notificarDesvinculacion(TransicionTransferencia cambio) {
        try {
            return normalizar(correo.notificarDesvinculacion(cambio.correoAnterior(),
                    cambio.nombreCompletoAnterior(), cambio.nombreEstacionamiento()));
        } catch (RuntimeException excepcion) {
            return EstadoAviso.DESCONOCIDO;
        }
    }

    private EstadoAviso enviarBienvenida(DatosConfiguracion datos) {
        try {
            DatosPropietario propietario = datos.propietario();
            return normalizar(correo.enviarBienvenida(propietario.correo(),
                    nombreCompleto(propietario.nombres(), propietario.primerApellido(), propietario.segundoApellido()),
                    datos.nombreEstacionamiento()));
        } catch (RuntimeException excepcion) {
            return EstadoAviso.DESCONOCIDO;
        }
    }

    private void guardarEstadoAviso(UUID operacionId, TipoAviso tipo, EstadoAviso aviso) {
        try {
            repositorio.actualizarEstadoAviso(operacionId, tipo, aviso.name());
        } catch (RuntimeException excepcion) {
            // La transición de negocio ya confirmó; el correo no se reintenta.
        }
    }

    private static EstadoAviso avisoPersistido(String estado) {
        if (estado == null || estado.equals("RESERVADO") || estado.equals("NO_APLICA")) {
            return EstadoAviso.DESCONOCIDO;
        }
        try {
            return EstadoAviso.valueOf(estado);
        } catch (IllegalArgumentException excepcion) {
            return EstadoAviso.DESCONOCIDO;
        }
    }

    private static EstadoAviso normalizar(EstadoAviso aviso) {
        return aviso == null ? EstadoAviso.DESCONOCIDO : aviso;
    }

    private static String nombreCompleto(String nombres, String primerApellido, String segundoApellido) {
        return java.util.stream.Stream.of(nombres, primerApellido, segundoApellido)
                .filter(valor -> valor != null && !valor.isBlank())
                .collect(java.util.stream.Collectors.joining(" "));
    }

    private record TransicionBienvenida(ResultadoConfiguracion resultado, UUID operacionId, DatosConfiguracion datos) { }

    private record TransicionTransferencia(
            ResultadoTransferencia resultado, long revisionPropietarioAnterior,
            String correoAnterior, String nombreCompletoAnterior,
            String nombreEstacionamiento, UUID operacionId) { }
}
