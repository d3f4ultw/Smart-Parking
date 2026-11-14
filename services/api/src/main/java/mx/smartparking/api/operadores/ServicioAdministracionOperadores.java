package mx.smartparking.api.operadores;

import java.util.Locale;
import java.util.UUID;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;
import mx.smartparking.api.activacion.PreparacionInvitacionOperador;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import mx.smartparking.api.empleados.coordinacion.EmpleadoEnlaceOperador;
import mx.smartparking.api.empleados.coordinacion.PuertoEmpleadosOperador;
import org.springframework.beans.factory.annotation.Autowired;
import mx.smartparking.api.persistencia.RepositorioOperadores;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/** Consulta los datos actuales del operador y administra los cambios permitidos de su cuenta. */
@Service
public class ServicioAdministracionOperadores {

    private final RepositorioOperadores repositorio;
    private final PuertoInvitacionesAdministracion invitaciones;
    private final GestorSesionesPropietario sesiones;
    private final ServicioEventosAdministracion eventos;
    private final TransactionTemplate transaccion;
    private final TransactionTemplate transaccionLectura;
    private PuertoEmpleadosOperador empleados;

    @Autowired
    void establecerEmpleados(PuertoEmpleadosOperador empleados) { this.empleados = empleados; }

    public ServicioAdministracionOperadores(
            RepositorioOperadores repositorio,
            PuertoInvitacionesAdministracion invitaciones,
            GestorSesionesPropietario sesiones,
            ServicioEventosAdministracion eventos,
            PlatformTransactionManager administradorTransacciones) {
        this.repositorio = repositorio;
        this.invitaciones = invitaciones;
        this.sesiones = sesiones;
        this.eventos = eventos;
        this.transaccion = new TransactionTemplate(administradorTransacciones);
        this.transaccionLectura = new TransactionTemplate(administradorTransacciones);
        this.transaccionLectura.setReadOnly(true);
        this.transaccionLectura.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
    }

    /** Reúne los datos actuales de la cuenta y la invitación para mostrar el detalle del operador. */
    public DetalleOperadorVersionado consultar(UUID operadorId, PrincipalPropietario principal) {
        exigirDueno(principal);
        DetalleOperadorVersionado resultado = transaccionLectura.execute(estado ->
                crearDetalle(buscarCuenta(operadorId)));
        if (resultado == null) {
            throw servicioNoDisponible();
        }
        return resultado;
    }

    /** Cambia el estado de la cuenta si los datos siguen vigentes y avisa después de guardar el cambio. */
    public DetalleOperadorVersionado cambiarEstado(
            UUID operadorId,
            String estadoSolicitado,
            String ifMatch,
            String rawIdempotencyKey,
            PrincipalPropietario principal) {
        exigirDueno(principal);
        EstadoCuentaOperador estadoDeseado = validarEstadoSolicitado(estadoSolicitado);
        long revisionEsperada = validarRevision(ifMatch);
        if (estadoDeseado == EstadoCuentaOperador.PENDIENTE) {
            validarClaveIdempotencia(rawIdempotencyKey);
        }

        TransicionEstado transicionEstado = transaccion.execute(estado -> {
            Long empleadoId = repositorio.empleadoId(operadorId).orElse(null);
            EmpleadoEnlaceOperador empleado = null;
            if (empleadoId != null) {
                if (empleados == null) {
                    throw servicioNoDisponible();
                }
                empleado = empleados.bloquearPorId(empleadoId).orElseThrow(this::operadorNoEncontrado);
            }
            CuentaOperadorAdministrable actual = repositorio.bloquearCuentaAdministrable(operadorId)
                    .orElseThrow(this::operadorNoEncontrado);
            if (!java.util.Objects.equals(empleadoId, actual.empleadoId())) {
                throw error(HttpStatus.CONFLICT, "VINCULO_CAMBIO",
                        "La cuenta cambió de vínculo. Actualiza la información e inténtalo de nuevo.");
            }
            if (estadoDeseado == EstadoCuentaOperador.PENDIENTE
                    && invitaciones.reactivacionRepetida(operadorId, rawIdempotencyKey)) {
                return new TransicionEstado(false, null, false);
            }
            if (actual.revisionAcceso() != revisionEsperada) {
                throw error(HttpStatus.PRECONDITION_FAILED, "REVISION_OBSOLETA",
                        "La información de la cuenta cambió. Actualízala antes de continuar.");
            }
            if (actual.estado() == estadoDeseado) {
                return new TransicionEstado(false, null, false);
            }
            validarTransicion(actual.estado(), estadoDeseado);
            if (estadoDeseado == EstadoCuentaOperador.PENDIENTE) {
                if (empleado == null) {
                    throw error(HttpStatus.CONFLICT, "EMPLEADO_REQUERIDO",
                            "Concilia esta cuenta con un empleado antes de reactivarla.");
                }
                if (!"ACTIVO".equals(empleado.estado())) {
                    throw error(HttpStatus.CONFLICT, "EMPLEADO_INACTIVO",
                            "Activa al empleado antes de reactivar su cuenta.");
                }
            }
            if (actual.revisionAcceso() == Long.MAX_VALUE) {
                throw servicioNoDisponible();
            }

            PreparacionInvitacionOperador preparacion = null;
            if (estadoDeseado == EstadoCuentaOperador.INACTIVA) {
                invitaciones.invalidarPendientes(operadorId);
            } else {
                preparacion = invitaciones.prepararReactivacion(
                        operadorId, actual.correo(), rawIdempotencyKey);
            }
            repositorio.actualizarEstado(
                    operadorId, estadoDeseado, actual.revisionAcceso(), actual.revisionAcceso() + 1);
            if (empleado != null) {
                if (empleado.revision() == Long.MAX_VALUE
                        || !empleados.incrementarRevision(empleado.id(), empleado.revision())) {
                    throw error(HttpStatus.PRECONDITION_FAILED, "REVISION_OBSOLETA",
                            "La información del empleado cambió. Actualízala antes de continuar.");
                }
            }
            return new TransicionEstado(true, preparacion, empleado != null);
        });
        if (transicionEstado == null) {
            throw servicioNoDisponible();
        }
        if (!transicionEstado.cambioVisible()) {
            return consultar(operadorId, principal);
        }

        if (estadoDeseado == EstadoCuentaOperador.INACTIVA) {
            sesiones.revocarCuenta(operadorId);
            publicarActualizacion(transicionEstado.empleadoActualizado());
        } else {
            publicarActualizacion(transicionEstado.empleadoActualizado());
            try {
                EstadoEnvioInvitacion resultado = invitaciones.enviarReactivacion(
                        transicionEstado.preparacion());
                if (resultado == null) {
                    throw servicioNoDisponible();
                }
            } catch (RuntimeException excepcion) {
                // La cuenta ya está pendiente; el resultado del correo se puede consultar en el detalle.
            }
        }
        return consultar(operadorId, principal);
    }

    private CuentaOperadorAdministrable buscarCuenta(UUID operadorId) {
        return repositorio.buscarCuentaAdministrable(operadorId).orElseThrow(this::operadorNoEncontrado);
    }

    private DetalleOperadorVersionado crearDetalle(CuentaOperadorAdministrable cuenta) {
        ProyeccionInvitacionOperador invitacion = invitaciones.consultar(cuenta.id());
        DetalleOperador detalle = new DetalleOperador(
                cuenta.id(),
                cuenta.nombres(),
                cuenta.primerApellido(),
                cuenta.segundoApellido(),
                cuenta.correo(),
                cuenta.estado(),
                invitacion.estadoInvitacion(),
                invitacion.invitacionGeneradaEn(),
                invitacion.invitacionVenceEn(),
                invitacion.invitacionConsumidaEn(),
                cuenta.creadaEn(),
                invitacion.reenvioDisponibleEn(),
                invitacion.reemisionesRestantes(),
                cuenta.estado() == EstadoCuentaOperador.PENDIENTE && invitacion.puedeReemitirInvitacion(),
                invitacion.recuperacionDisponibleEn(),
                invitacion.recuperacionesRestantes(),
                cuenta.estado() == EstadoCuentaOperador.ACTIVA && invitacion.puedeSolicitarRecuperacion(),
                cuenta.estado() != EstadoCuentaOperador.INACTIVA,
                cuenta.estado() == EstadoCuentaOperador.INACTIVA,
                cuenta.empleadoId() == null ? null : Long.toString(cuenta.empleadoId()),
                cuenta.empleadoId() == null ? "LEGADO_SIN_VINCULO" : "VINCULADO");
        return new DetalleOperadorVersionado(detalle, cuenta.revisionAcceso());
    }

    private static EstadoCuentaOperador validarEstadoSolicitado(String texto) {
        if (texto == null || texto.isBlank()) {
            throw error(HttpStatus.BAD_REQUEST, "ESTADO_NO_VALIDO", "Elige qué hacer con esta cuenta.");
        }
        EstadoCuentaOperador estado;
        try {
            estado = EstadoCuentaOperador.valueOf(texto.strip().toUpperCase(Locale.ROOT));
        } catch (IllegalArgumentException excepcion) {
            throw error(HttpStatus.BAD_REQUEST, "ESTADO_NO_VALIDO",
                    "Selecciona un estado válido para esta cuenta.");
        }
        if (estado == EstadoCuentaOperador.ACTIVA) {
            throw transicionNoPermitida();
        }
        return estado;
    }

    private static long validarRevision(String ifMatch) {
        if (ifMatch == null) {
            throw error(HttpStatus.PRECONDITION_REQUIRED, "REVISION_REQUERIDA",
                    "Actualiza la información de la cuenta antes de continuar.");
        }
        if (ifMatch.length() < 3 || ifMatch.charAt(0) != '"' || ifMatch.charAt(ifMatch.length() - 1) != '"') {
            throw error(HttpStatus.BAD_REQUEST, "REVISION_NO_VALIDA", "La información cambió. Actualiza la cuenta e inténtalo de nuevo.");
        }
        String decimal = ifMatch.substring(1, ifMatch.length() - 1);
        if (!decimal.matches("[0-9]+")) {
            throw error(HttpStatus.BAD_REQUEST, "REVISION_NO_VALIDA", "La información cambió. Actualiza la cuenta e inténtalo de nuevo.");
        }
        try {
            long revision = Long.parseLong(decimal);
            if (revision < 0) {
                throw new NumberFormatException("La revisión no puede ser negativa.");
            }
            return revision;
        } catch (NumberFormatException excepcion) {
            throw error(HttpStatus.BAD_REQUEST, "REVISION_NO_VALIDA", "La información cambió. Actualiza la cuenta e inténtalo de nuevo.");
        }
    }

    private static void validarClaveIdempotencia(String clave) {
        if (clave == null || clave.strip().length() < 16 || clave.length() > 200
                || clave.codePoints().anyMatch(Character::isISOControl)) {
            throw error(HttpStatus.BAD_REQUEST, "CLAVE_IDEMPOTENCIA_NO_VALIDA",
                    "No pudimos completar el cambio. Actualiza la información de la cuenta e inténtalo de nuevo.");
        }
    }

    private static void validarTransicion(EstadoCuentaOperador actual, EstadoCuentaOperador deseado) {
        if (deseado == EstadoCuentaOperador.INACTIVA
                && (actual == EstadoCuentaOperador.ACTIVA || actual == EstadoCuentaOperador.PENDIENTE)) {
            return;
        }
        if (deseado == EstadoCuentaOperador.PENDIENTE && actual == EstadoCuentaOperador.INACTIVA) {
            return;
        }
        throw transicionNoPermitida();
    }

    private void publicarActualizacion(boolean empleadoActualizado) {
        if (empleadoActualizado) {
            try {
                eventos.publicarDirectorioActualizado();
            } catch (RuntimeException excepcion) {
                System.getLogger(ServicioAdministracionOperadores.class.getName()).log(
                        System.Logger.Level.WARNING, "No se pudo publicar la actualización del directorio de empleados.");
            }
        }
        try {
            eventos.publicarDirectorioOperadorActualizado();
        } catch (RuntimeException excepcion) {
            System.getLogger(ServicioAdministracionOperadores.class.getName()).log(
                    System.Logger.Level.WARNING, "No se pudo publicar la actualización del directorio de operadores.");
        }
    }

    private ErrorConfiguracion operadorNoEncontrado() {
        return error(HttpStatus.NOT_FOUND, "OPERADOR_NO_ENCONTRADO", "No encontramos esta cuenta.");
    }

    private static ErrorConfiguracion transicionNoPermitida() {
        return error(HttpStatus.CONFLICT, "TRANSICION_NO_PERMITIDA",
                "No se puede cambiar el acceso de esta cuenta ahora.");
    }

    private static ErrorConfiguracion servicioNoDisponible() {
        return error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                "No pudimos cargar la información de las cuentas. Inténtalo más tarde.");
    }

    private static void exigirDueno(PrincipalPropietario principal) {
        if (principal == null) {
            throw error(HttpStatus.UNAUTHORIZED, "SESION_NO_VIGENTE", "Tu acceso venció. Inicia sesión de nuevo.");
        }
        if (principal.rol() != RolCuenta.DUENO) {
            throw error(HttpStatus.FORBIDDEN, "PERMISO_INSUFICIENTE", "No tienes acceso para hacer este cambio.");
        }
    }

    private static ErrorConfiguracion error(HttpStatus estado, String codigo, String mensaje) {
        return new ErrorConfiguracion(estado, mensaje, codigo);
    }

    private record TransicionEstado(
            boolean cambioVisible,
            PreparacionInvitacionOperador preparacion,
            boolean empleadoActualizado) {
    }
}
