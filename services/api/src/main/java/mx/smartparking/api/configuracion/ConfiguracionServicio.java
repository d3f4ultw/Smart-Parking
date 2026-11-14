package mx.smartparking.api.configuracion;

import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.UUID;
import mx.smartparking.api.correo.EstadoAviso;
import mx.smartparking.api.correo.NotificadorCorreo;
import mx.smartparking.api.persistencia.ConfiguracionPersistida;
import mx.smartparking.api.persistencia.RepositorioConfiguracion;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.persistencia.RepositorioConfiguracion.TipoAviso;
import mx.smartparking.api.transferencia.ServicioTransferenciaPropietario;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Guarda los cambios de configuración de forma coordinada y envía los avisos cuando los cambios ya
 * quedaron confirmados.
 */
@Service
public class ConfiguracionServicio {

    private static final DateTimeFormatter FORMATO_HORA = DateTimeFormatter.ofPattern("HH:mm");
    private final RepositorioConfiguracion repositorio;
    private final RepositorioCuentas cuentas;
    private final PasswordEncoder codificadorContrasenas;
    private final NotificadorCorreo notificadorCorreo;
    private final TransactionTemplate transaccion;
    private final ServicioTransferenciaPropietario servicioTransferencia;

    @Autowired
    public ConfiguracionServicio(
            RepositorioConfiguracion repositorio,
            RepositorioCuentas cuentas,
            PasswordEncoder codificadorContrasenas,
            NotificadorCorreo notificadorCorreo,
            PlatformTransactionManager administradorTransacciones,
            ServicioTransferenciaPropietario servicioTransferencia) {
        this.repositorio = repositorio;
        this.cuentas = cuentas;
        this.codificadorContrasenas = codificadorContrasenas;
        this.notificadorCorreo = notificadorCorreo;
        this.transaccion = new TransactionTemplate(administradorTransacciones);
        this.servicioTransferencia = servicioTransferencia;
    }

    /** Indica el estado de configuración y avisa si no es posible consultar los datos guardados. */
    public EstadoConfiguracion consultarEstado() {
        return repositorio.obtener().estado();
    }

    /** Entrega la versión de la configuración para reconocer si cambió antes de una nueva modificación. */
    public long consultarRevision() {
        return repositorio.obtener().revision();
    }

    private static String hashClaveIdempotencia(String clave) {
        return ServicioTransferenciaPropietario.hashClaveIdempotencia(clave);
    }

    private static boolean coincideClave(ConfiguracionPersistida actual, String hashClave) {
        return ServicioTransferenciaPropietario.coincideClave(actual, hashClave);
    }

    /** Registra la configuración una sola vez y envía la bienvenida después de guardar los datos. */
    public ResultadoConfiguracion configurarInicial(SolicitudConfiguracion solicitud, String claveIdempotencia) {
        DatosConfiguracion datos = validarSolicitud(solicitud);
        String claveHash = hashClaveIdempotencia(claveIdempotencia);
        String hashAcceso = codificadorContrasenas.encode(datos.propietario().contrasenaAcceso());
        String hashAdministrativa = codificadorContrasenas.encode(datos.propietario().contrasenaAdministrativa());
        UUID operacionId = UUID.randomUUID();

        TransicionBienvenida transicion = transaccion.execute(status -> {
            ConfiguracionPersistida actual = repositorio.bloquear();
            if (actual.estado() == EstadoConfiguracion.CONFIGURADA
                    && coincideClave(actual, claveHash)) {
                return new TransicionBienvenida(
                        new ResultadoConfiguracion(actual.estado(), actual.revision(), avisoPersistido(actual.estadoAvisoBienvenida())),
                        null,
                        null);
            }
            exigirEstado(actual, EstadoConfiguracion.SIN_CONFIGURAR);
            UUID cuentaId = cuentas.crearDueno(datos, hashAcceso);
            repositorio.configurarInicial(
                    datos,
                    hashAdministrativa,
                    UUID.randomUUID(),
                    cuentaId,
                    actual.revision() + 1,
                    actual.revisionPropietario() + 1,
                    operacionId,
                    claveHash);
            return new TransicionBienvenida(
                    new ResultadoConfiguracion(EstadoConfiguracion.CONFIGURADA, actual.revision() + 1, null),
                    operacionId,
                    datos);
        });

        if (transicion.datos() == null) {
            return transicion.resultado();
        }
        EstadoAviso aviso = enviarBienvenida(transicion.datos());
        guardarEstadoAviso(transicion.operacionId(), TipoAviso.BIENVENIDA, aviso);
        return new ResultadoConfiguracion(EstadoConfiguracion.CONFIGURADA, transicion.resultado().revision(), aviso);
    }

    /** Comprueba que el acceso del propietario siga vigente antes de atender su solicitud. */
    public void validarRevisionPropietario(long revisionPropietario) {
        exigirPropietarioActivo(repositorio.obtener(), revisionPropietario);
    }

    /** Muestra los datos del panel sin revelar contraseñas ni otros datos usados para proteger el acceso. */
    public PanelPropietario obtenerPanel(long revisionPropietario) {
        ConfiguracionPersistida actual = repositorio.obtener();
        exigirPropietarioActivo(actual, revisionPropietario);
        return panel(actual);
    }

    /** Actualiza únicamente el nombre del estacionamiento y conserva las sesiones activas. */
    public PanelPropietario renombrar(
            String nombre,
            long revisionEsperada,
            long revisionPropietario,
            String claveIdempotencia) {
        String nombreValidado = validarNombre(nombre);
        String claveHash = hashClaveIdempotencia(claveIdempotencia);
        UUID operacionId = UUID.randomUUID();
        return transaccion.execute(status -> {
            ConfiguracionPersistida actual = repositorio.bloquear();
            exigirPropietarioActivo(actual, revisionPropietario);
            if (coincideClave(actual, claveHash)) {
                return panel(actual);
            }
            exigirRevision(actual, revisionEsperada);
            repositorio.renombrar(nombreValidado, actual.revision() + 1, operacionId, claveHash);
            return panel(conNombre(actual, nombreValidado, actual.revision() + 1, operacionId, claveHash));
        });
    }

    /** Actualiza el tipo y el horario del estacionamiento sin cerrar la sesión del propietario. */
    public PanelPropietario actualizarDatosEstacionamiento(
            TipoEstacionamiento tipo,
            HorarioConfiguracion horario,
            long revisionEsperada,
            long revisionPropietario,
            String claveIdempotencia) {
        if (tipo == null || horario == null) {
            throw new ErrorConfiguracion(HttpStatus.BAD_REQUEST, "Completa el tipo y el horario del estacionamiento.");
        }
        String claveHash = hashClaveIdempotencia(claveIdempotencia);
        UUID operacionId = UUID.randomUUID();
        return transaccion.execute(status -> {
            ConfiguracionPersistida actual = repositorio.bloquear();
            exigirPropietarioActivo(actual, revisionPropietario);
            if (coincideClave(actual, claveHash)) {
                return panel(actual);
            }
            exigirRevision(actual, revisionEsperada);
            long revision = actual.revision() + 1;
            repositorio.actualizarDatosEstacionamiento(tipo, horario, revision, operacionId, claveHash);
            return panel(conDatosEstacionamiento(actual, tipo, horario, revision, operacionId, claveHash));
        });
    }

    /** Entrega la solicitud de cambio de propietario al servicio que se encarga de realizarla. */
    public ResultadoTransferencia iniciarTransferencia(
            String contrasenaAdministrativa, long revisionEsperada, long revisionPropietario,
            String claveIdempotencia, String origenRemoto) {
        return servicioTransferencia.iniciarTransferencia(contrasenaAdministrativa, revisionEsperada,
                revisionPropietario, claveIdempotencia, origenRemoto);
    }

    public ResultadoTransferencia recuperarTransferencia(String contrasenaAdministrativa, String origenRemoto) {
        return servicioTransferencia.recuperarTransferencia(contrasenaAdministrativa, origenRemoto);
    }

    public ResultadoConfiguracion completarTransferencia(
            String grant, SolicitudConfiguracion solicitud, String claveIdempotencia, String origenRemoto) {
        return servicioTransferencia.completarTransferencia(grant, solicitud, claveIdempotencia, origenRemoto);
    }

    private EstadoAviso enviarBienvenida(DatosConfiguracion datos) {
        try {
            return normalizarEstadoAviso(notificadorCorreo.enviarBienvenida(
                    datos.propietario().correo(),
                    nombreCompleto(datos.propietario()),
                    datos.nombreEstacionamiento()));
        } catch (RuntimeException excepcion) {
            return EstadoAviso.DESCONOCIDO;
        }
    }

    private void guardarEstadoAviso(UUID operacionId, TipoAviso tipo, EstadoAviso aviso) {
        try {
            repositorio.actualizarEstadoAviso(operacionId, tipo, aviso.name());
        } catch (RuntimeException excepcion) {
            // La operación de negocio ya quedó confirmada; nunca se revierte ni se retransmite por un fallo de estado.
        }
    }

    private static EstadoAviso normalizarEstadoAviso(EstadoAviso aviso) {
        return aviso == null ? EstadoAviso.DESCONOCIDO : aviso;
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

    private static String validarNombre(String nombre) {
        try {
            return new RenombrarEstacionamientoSolicitud(nombre).validar();
        } catch (IllegalArgumentException excepcion) {
            throw new ErrorConfiguracion(HttpStatus.BAD_REQUEST, excepcion.getMessage());
        }
    }

    private static void exigirEstado(ConfiguracionPersistida actual, EstadoConfiguracion estadoEsperado) {
        if (actual.estado() != estadoEsperado) {
            throw new ErrorConfiguracion(HttpStatus.CONFLICT,
                    "No se puede hacer este cambio ahora. Actualiza la pantalla e inténtalo de nuevo.");
        }
    }

    private static void exigirRevision(ConfiguracionPersistida actual, long revisionEsperada) {
        if (actual.revision() != revisionEsperada) {
            throw new ErrorConfiguracion(HttpStatus.PRECONDITION_FAILED,
                    "La información cambió. Actualiza la pantalla antes de continuar.");
        }
    }

    private static void exigirPropietarioActivo(ConfiguracionPersistida actual, long revisionPropietario) {
        if (actual.estado() != EstadoConfiguracion.CONFIGURADA
                || actual.revisionPropietario() != revisionPropietario) {
            throw new ErrorConfiguracion(HttpStatus.UNAUTHORIZED, "Tu acceso venció. Inicia sesión de nuevo.");
        }
    }

    private static PanelPropietario panel(ConfiguracionPersistida actual) {
        return new PanelPropietario(
                actual.revision(),
                actual.revisionPropietario(),
                new PanelPropietario.PropietarioPanel(
                        actual.propietarioNombres(),
                        actual.propietarioPrimerApellido(),
                        actual.propietarioSegundoApellido(),
                        actual.correoPropietario()),
                new PanelPropietario.EstacionamientoPanel(
                        actual.estacionamientoId(),
                        actual.nombreEstacionamiento(),
                        actual.tipoEstacionamiento(),
                        new PanelPropietario.HorarioPanel(
                                actual.modoHorario(),
                                actual.zonaHoraria(),
                                formatearHora(actual.horaApertura()),
                                formatearHora(actual.horaCierre()))));
    }

    private static ConfiguracionPersistida conNombre(
            ConfiguracionPersistida actual,
            String nombre,
            long revision,
            UUID operacionId,
            String hashClave) {
        return new ConfiguracionPersistida(
                actual.estado(), revision, actual.revisionPropietario(), actual.estacionamientoId(),
                actual.propietarioNombres(), actual.propietarioPrimerApellido(), actual.propietarioSegundoApellido(),
                actual.correoPropietario(), null, actual.hashContrasenaAdministrativa(),
                nombre, actual.tipoEstacionamiento(), actual.modoHorario(), actual.zonaHoraria(),
                actual.horaApertura(), actual.horaCierre(), actual.transferId(), actual.hashGrantTransferencia(),
                actual.grantVenceEn(), actual.hashRecuperacionTransferencia(), actual.estadoAvisoTransferencia(),
                actual.estadoAvisoBienvenida(), operacionId, hashClave);
    }

    private static ConfiguracionPersistida conDatosEstacionamiento(
            ConfiguracionPersistida actual,
            TipoEstacionamiento tipo,
            HorarioConfiguracion horario,
            long revision,
            UUID operacionId,
            String hashClave) {
        return new ConfiguracionPersistida(
                actual.estado(), revision, actual.revisionPropietario(), actual.estacionamientoId(),
                actual.propietarioNombres(), actual.propietarioPrimerApellido(), actual.propietarioSegundoApellido(),
                actual.correoPropietario(), null, actual.hashContrasenaAdministrativa(),
                actual.nombreEstacionamiento(), tipo, horario.modo(), horario.zonaHoraria(),
                horario.horaApertura(), horario.horaCierre(), actual.transferId(), actual.hashGrantTransferencia(),
                actual.grantVenceEn(), actual.hashRecuperacionTransferencia(), actual.estadoAvisoTransferencia(),
                actual.estadoAvisoBienvenida(), operacionId, hashClave);
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

    private static String formatearHora(LocalTime hora) {
        return hora == null ? null : hora.format(FORMATO_HORA);
    }

    private static String nombreCompleto(DatosPropietario propietario) {
        return nombreCompleto(propietario.nombres(), propietario.primerApellido(), propietario.segundoApellido());
    }

    private static String nombreCompleto(String nombres, String primerApellido, String segundoApellido) {
        return java.util.stream.Stream.of(nombres, primerApellido, segundoApellido)
                .filter(valor -> valor != null && !valor.isBlank())
                .collect(java.util.stream.Collectors.joining(" "));
    }

    private record TransicionBienvenida(
            ResultadoConfiguracion resultado,
            UUID operacionId,
            DatosConfiguracion datos) {
    }


}
