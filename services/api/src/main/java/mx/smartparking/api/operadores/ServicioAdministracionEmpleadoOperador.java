package mx.smartparking.api.operadores;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Locale;
import java.util.Optional;
import java.util.UUID;
import java.util.regex.Pattern;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;
import mx.smartparking.api.activacion.PreparacionInvitacionOperador;
import mx.smartparking.api.activacion.ServicioActivacionOperador;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.empleados.coordinacion.EmpleadoEnlaceOperador;
import mx.smartparking.api.empleados.coordinacion.PuertoAdministracionEmpleadoOperador;
import mx.smartparking.api.empleados.coordinacion.PuertoEmpleadosOperador;
import mx.smartparking.api.empleados.coordinacion.ResultadoAccionEmpleadoOperador;
import mx.smartparking.api.empleados.coordinacion.ResultadoCambioCorreoEmpleadoOperador;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import mx.smartparking.api.persistencia.RepositorioAccionesEmpleadoOperador;
import mx.smartparking.api.persistencia.RepositorioOperadores;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import mx.smartparking.api.activacion.SeguridadTokensOperador;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Mantiene de acuerdo los datos del empleado, su cuenta de operador y sus invitaciones cuando se
 * guardan cambios.
 */
@Service
public class ServicioAdministracionEmpleadoOperador implements PuertoAdministracionEmpleadoOperador {

    private static final Pattern FORMATO_CORREO = Pattern.compile("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$");
    private static final int MAXIMO_CORREO = 254;
    private static final String PROMOVER = "PROMOVER";
    private static final String CAMBIAR_CORREO = "CAMBIAR_CORREO";
    private static final String DESACTIVAR = "DESACTIVAR";
    private static final String VINCULAR = "VINCULAR";

    private final RepositorioOperadores operadores;
    private final RepositorioAccionesEmpleadoOperador acciones;
    private final PuertoInvitacionesAdministracion invitaciones;
    private final ServicioActivacionOperador activacion;
    private final PuertoEmpleadosOperador empleados;
    private final GestorSesionesPropietario sesiones;
    private final ServicioEventosAdministracion eventos;
    private final TransactionTemplate transaccion;

    public ServicioAdministracionEmpleadoOperador(
            RepositorioOperadores operadores,
            RepositorioAccionesEmpleadoOperador acciones,
            PuertoInvitacionesAdministracion invitaciones,
            ServicioActivacionOperador activacion,
            PuertoEmpleadosOperador empleados,
            GestorSesionesPropietario sesiones,
            ServicioEventosAdministracion eventos,
            PlatformTransactionManager administradorTransacciones) {
        this.operadores = operadores;
        this.acciones = acciones;
        this.invitaciones = invitaciones;
        this.activacion = activacion;
        this.empleados = empleados;
        this.sesiones = sesiones;
        this.eventos = eventos;
        this.transaccion = new TransactionTemplate(administradorTransacciones);
    }

    @Override
    public ResultadoAccionEmpleadoOperador promocionar(
            String idTexto, String ifMatch, String rawKey, PrincipalPropietario propietario) {
        return promocionar(idTexto, null, ifMatch, rawKey, propietario);
    }

    @Override
    public ResultadoAccionEmpleadoOperador promocionar(
            String idTexto, String correoSolicitado, String ifMatch, String rawKey,
            PrincipalPropietario propietario) {
        exigirDueno(propietario);
        long empleadoId = validarId(idTexto);
        String correoSolicitud = correoSolicitado == null ? null : validarCorreo(correoSolicitado, false);
        String claveHash = hashClave(rawKey);
        String huella = correoSolicitud == null
                ? huella(PROMOVER, Long.toString(empleadoId))
                : huella(PROMOVER, Long.toString(empleadoId), normalizarCorreo(correoSolicitud));
        TransicionPromocion transicion = transaccion.execute(estado -> {
            empleados.consultarPorId(empleadoId).orElseThrow(this::empleadoNoEncontrado);
            AccionEmpleadoOperadorPersistida repetida = reservarOReproducir(
                    propietario.cuentaId(), claveHash, huella, PROMOVER, empleadoId);
            if (repetida != null) {
                return TransicionPromocion.reproducida(repetida);
            }
            EmpleadoEnlaceOperador empleado = empleados.bloquearPorId(empleadoId)
                    .orElseThrow(this::empleadoNoEncontrado);
            exigirRevision(empleado.revision(), validarIfMatch(ifMatch));
            exigirEmpleadoActivo(empleado);
            if (empleado.revision() == Long.MAX_VALUE) {
                throw servicioNoDisponible();
            }
            String correo = validarCorreo(
                    correoSolicitud == null ? empleado.correo() : correoSolicitud, false);
            String normalizado = normalizarCorreo(correo);
            boolean cambioCorreo = !igualCorreo(normalizarCorreo(empleado.correo()), normalizado);
            Optional<CuentaOperadorAdministrable> cuentaExistente = operadores.bloquearCuentaVinculada(empleadoId);
            if (cuentaExistente.isPresent()) {
                CuentaOperadorAdministrable cuenta = cuentaExistente.get();
                if (cuenta.estado() != EstadoCuentaOperador.INACTIVA) {
                    throw error(HttpStatus.CONFLICT, "OPERADOR_YA_VINCULADO",
                            "El empleado ya tiene una cuenta de operador.");
                }
                if (operadores.correoReservado(normalizado, cuenta.id())) {
                    throw correoEnUso();
                }
                PreparacionInvitacionOperador preparacion = invitaciones.prepararReactivacion(
                        cuenta.id(), correo, rawKey);
                CuentaOperadorAdministrable actualizada = operadores.reactivarCuentaVinculada(
                        cuenta.id(), empleadoId, correo, normalizado, cuenta.revisionAcceso());
                if (cambioCorreo) {
                    actualizarCorreoEmpleado(empleado, correo, normalizado);
                } else {
                    incrementarRevisionEmpleado(empleado);
                }
                long revisionNueva = empleado.revision() + 1;
                ResultadoAccionEmpleadoOperador resultado = resultado(
                        empleadoId, actualizada.id(), EstadoCuentaOperador.PENDIENTE.name(),
                        revisionNueva, EstadoEnvioInvitacion.ENVIANDO.name());
                acciones.completar(propietario.cuentaId(), claveHash, actualizada.id(),
                        EstadoCuentaOperador.PENDIENTE.name(), revisionNueva, EstadoEnvioInvitacion.ENVIANDO.name());
                return new TransicionPromocion(resultado, preparacion, false, null);
            }
            if (operadores.correoReservado(normalizado, null)) {
                throw correoEnUso();
            }
            UUID operadorId = UUID.randomUUID();
            if (cambioCorreo) {
                actualizarCorreoEmpleado(empleado, correo, normalizado);
            }
            operadores.crearOperadorVinculado(operadorId, empleadoId);
            PreparacionInvitacionOperador preparacion = activacion.prepararInicial(operadorId, correo);
            if (!cambioCorreo) {
                incrementarRevisionEmpleado(empleado);
            }
            long revisionNueva = empleado.revision() + 1;
            ResultadoAccionEmpleadoOperador resultado = resultado(
                    empleadoId, operadorId, EstadoCuentaOperador.PENDIENTE.name(),
                    revisionNueva, EstadoEnvioInvitacion.ENVIANDO.name());
            acciones.completar(propietario.cuentaId(), claveHash, operadorId,
                    EstadoCuentaOperador.PENDIENTE.name(), revisionNueva, EstadoEnvioInvitacion.ENVIANDO.name());
            return new TransicionPromocion(resultado, preparacion, true, null);
        });
        if (transicion == null) {
            throw servicioNoDisponible();
        }
        if (transicion.repetida() != null) {
            return resultado(transicion.repetida());
        }
        publicarDirectorios(true, true);
        EstadoEnvioInvitacion envio = enviarPromocion(transicion);
        try {
            acciones.actualizarEstadoEnvio(propietario.cuentaId(), claveHash, envio.name());
        } catch (RuntimeException excepcion) {
            System.getLogger(getClass().getName()).log(
                    System.Logger.Level.WARNING,
                    "No se pudo persistir el resultado del envío de la invitación de operador.");
        }
        return conEnvio(transicion.resultado(), envio.name());
    }

    @Override
    public ResultadoCambioCorreoEmpleadoOperador cambiarCorreo(
            String idTexto, String correoSolicitado, String ifMatch, String rawKey,
            PrincipalPropietario propietario) {
        exigirDueno(propietario);
        long empleadoId = validarId(idTexto);
        String correo = validarCorreo(correoSolicitado, true);
        String normalizado = normalizarCorreo(correo);
        String claveHash = hashClave(rawKey);
        String huella = huella(CAMBIAR_CORREO, Long.toString(empleadoId), normalizado);
        TransicionCorreo transicion = transaccion.execute(estado -> {
            empleados.consultarPorId(empleadoId).orElseThrow(this::empleadoNoEncontrado);
            AccionEmpleadoOperadorPersistida repetida = reservarOReproducir(
                    propietario.cuentaId(), claveHash, huella, CAMBIAR_CORREO, empleadoId);
            if (repetida != null) {
                return TransicionCorreo.reproducida(repetida);
            }
            EmpleadoEnlaceOperador empleado = empleados.bloquearPorId(empleadoId)
                    .orElseThrow(this::empleadoNoEncontrado);
            exigirRevision(empleado.revision(), validarIfMatch(ifMatch));
            if (empleado.revision() == Long.MAX_VALUE) {
                throw servicioNoDisponible();
            }
            Optional<CuentaOperadorAdministrable> vinculada = operadores.bloquearCuentaVinculada(empleadoId);
            if (vinculada.isEmpty()) {
                if (igualCorreo(empleado.correo(), correo)) {
                    acciones.completar(propietario.cuentaId(), claveHash, null, null,
                            empleado.revision(), null);
                    return TransicionCorreo.sinCambio(empleadoId, correo, empleado.revision());
                }
                actualizarCorreoEmpleado(empleado, correo, normalizado);
                long revisionNueva = empleado.revision() + 1;
                acciones.completar(propietario.cuentaId(), claveHash, null, null, revisionNueva, null);
                return TransicionCorreo.sinEnvio(empleadoId, correo, revisionNueva, null, null, null, true);
            }
            CuentaOperadorAdministrable cuenta = vinculada.get();
            if (correo == null && cuenta.estado() != EstadoCuentaOperador.INACTIVA) {
                throw error(HttpStatus.CONFLICT, "CORREO_REQUERIDO",
                        "Agrega un correo antes de mantener el acceso de operador.");
            }
            if (igualCorreo(empleado.correo(), correo) && igualCorreo(cuenta.correo(), correo)) {
                acciones.completar(propietario.cuentaId(), claveHash, cuenta.id(), cuenta.estado().name(),
                        empleado.revision(), null);
                return TransicionCorreo.sinCambio(
                        empleadoId, correo, empleado.revision(), cuenta.id(), cuenta.estado());
            }
            if (cuenta.revisionAcceso() == Long.MAX_VALUE) {
                throw servicioNoDisponible();
            }
            if (normalizado != null && operadores.correoReservado(normalizado, cuenta.id())) {
                throw correoEnUso();
            }
            PreparacionInvitacionOperador preparacion = null;
            if (cuenta.estado() == EstadoCuentaOperador.PENDIENTE) {
                preparacion = invitaciones.prepararCambioCorreo(cuenta.id(), correo, rawKey);
            } else {
                invitaciones.invalidarPendientes(cuenta.id());
            }
            CuentaOperadorAdministrable actualizada = operadores.actualizarCorreo(
                    cuenta.id(), correo, normalizado, cuenta.revisionAcceso());
            actualizarCorreoEmpleado(empleado, correo, normalizado);
            long revisionNueva = empleado.revision() + 1;
            String estadoEnvio = preparacion == null ? null : EstadoEnvioInvitacion.ENVIANDO.name();
            acciones.completar(propietario.cuentaId(), claveHash, actualizada.id(),
                    actualizada.estado().name(), revisionNueva, estadoEnvio);
            ResultadoCambioCorreoEmpleadoOperador respuesta = resultadoCorreo(
                    empleadoId, correo, actualizada.id(), actualizada.estado(), revisionNueva, estadoEnvio);
            return new TransicionCorreo(respuesta, preparacion, actualizada.id(),
                    cuenta.estado() == EstadoCuentaOperador.ACTIVA, true, null, null);
        });
        if (transicion == null) {
            throw servicioNoDisponible();
        }
        if (transicion.repetida() != null) {
            AccionEmpleadoOperadorPersistida repetida = transicion.repetida();
            return resultadoCorreo(repetida, correo);
        }
        if (transicion.sinEnvio() != null) {
            if (transicion.publicar()) {
                publicarDirectorios(true, transicion.operadorId() != null);
            }
            return transicion.sinEnvio();
        }
        if (transicion.revocar()) {
            sesiones.revocarCuenta(transicion.operadorId());
        }
        if (transicion.publicar()) {
            publicarDirectorios(true, transicion.operadorId() != null);
        }
        String estadoEnvio = null;
        if (transicion.preparacion() != null) {
            estadoEnvio = invitaciones.enviarCambioCorreo(transicion.preparacion()).name();
            acciones.actualizarEstadoEnvio(propietario.cuentaId(), claveHash, estadoEnvio);
        }
        return resultadoCorreo(transicion, estadoEnvio);
    }

    @Override
    public ResultadoAccionEmpleadoOperador desactivarAcceso(
            String idTexto, String ifMatch, String rawKey, PrincipalPropietario propietario) {
        exigirDueno(propietario);
        long empleadoId = validarId(idTexto);
        String claveHash = hashClave(rawKey);
        String huella = huella(DESACTIVAR, Long.toString(empleadoId));
        TransicionCuenta transicion = transaccion.execute(estado -> {
            empleados.consultarPorId(empleadoId).orElseThrow(this::empleadoNoEncontrado);
            AccionEmpleadoOperadorPersistida repetida = reservarOReproducir(
                    propietario.cuentaId(), claveHash, huella, DESACTIVAR, empleadoId);
            if (repetida != null) {
                return TransicionCuenta.reproducida(repetida);
            }
            EmpleadoEnlaceOperador empleado = empleados.bloquearPorId(empleadoId)
                    .orElseThrow(this::empleadoNoEncontrado);
            exigirRevision(empleado.revision(), validarIfMatch(ifMatch));
            if (empleado.revision() == Long.MAX_VALUE) {
                throw servicioNoDisponible();
            }
            CuentaOperadorAdministrable cuenta = operadores.bloquearCuentaVinculada(empleadoId)
                    .orElseThrow(() -> error(HttpStatus.CONFLICT, "OPERADOR_NO_VINCULADO",
                            "El empleado no tiene una cuenta de operador vinculada."));
            if (cuenta.estado() == EstadoCuentaOperador.INACTIVA) {
                acciones.completar(propietario.cuentaId(), claveHash, cuenta.id(),
                        cuenta.estado().name(), empleado.revision(), null);
                return TransicionCuenta.sinCambio(resultado(
                        empleadoId, cuenta.id(), cuenta.estado().name(), empleado.revision(), null));
            }
            if (cuenta.revisionAcceso() == Long.MAX_VALUE) {
                throw servicioNoDisponible();
            }
            invitaciones.invalidarPendientes(cuenta.id());
            operadores.actualizarEstado(cuenta.id(), EstadoCuentaOperador.INACTIVA,
                    cuenta.revisionAcceso(), cuenta.revisionAcceso() + 1);
            incrementarRevisionEmpleado(empleado);
            long revisionNueva = empleado.revision() + 1;
            ResultadoAccionEmpleadoOperador respuesta = resultado(
                    empleadoId, cuenta.id(), EstadoCuentaOperador.INACTIVA.name(), revisionNueva, null);
            acciones.completar(propietario.cuentaId(), claveHash, cuenta.id(),
                    EstadoCuentaOperador.INACTIVA.name(), revisionNueva, null);
            return new TransicionCuenta(respuesta, cuenta.id(), false, true, null);
        });
        if (transicion == null) {
            throw servicioNoDisponible();
        }
        if (transicion.repetida() != null) {
            return resultado(transicion.repetida());
        }
        if (transicion.cambio()) {
            sesiones.revocarCuenta(transicion.operadorId());
            publicarDirectorios(true, true);
        }
        return transicion.resultado();
    }

    @Override
    public ResultadoAccionEmpleadoOperador vincular(
            String idTexto, UUID operadorId, String revisionOperadorTexto, boolean copiarCorreoOperador,
            String ifMatch, String rawKey, PrincipalPropietario propietario) {
        exigirDueno(propietario);
        long empleadoId = validarId(idTexto);
        if (operadorId == null) {
            throw error(HttpStatus.BAD_REQUEST, "OPERADOR_NO_VALIDO", "Selecciona una cuenta de operador.");
        }
        long revisionOperador = validarRevisionDecimal(revisionOperadorTexto);
        String claveHash = hashClave(rawKey);
        String huella = huella(VINCULAR, Long.toString(empleadoId), operadorId.toString(), revisionOperadorTexto,
                Boolean.toString(copiarCorreoOperador));
        TransicionCuenta transicion = transaccion.execute(estado -> {
            empleados.consultarPorId(empleadoId).orElseThrow(this::empleadoNoEncontrado);
            AccionEmpleadoOperadorPersistida repetida = reservarOReproducir(
                    propietario.cuentaId(), claveHash, huella, VINCULAR, empleadoId);
            if (repetida != null) {
                return TransicionCuenta.reproducida(repetida);
            }
            EmpleadoEnlaceOperador empleado = empleados.bloquearPorId(empleadoId)
                    .orElseThrow(this::empleadoNoEncontrado);
            exigirRevision(empleado.revision(), validarIfMatch(ifMatch));
            if (empleado.revision() == Long.MAX_VALUE) {
                throw servicioNoDisponible();
            }
            if (operadores.buscarCuentaVinculada(empleadoId).isPresent()) {
                throw error(HttpStatus.CONFLICT, "VINCULO_OCUPADO", "El empleado ya tiene una cuenta vinculada.");
            }
            CuentaOperadorAdministrable cuenta = operadores.bloquearCuentaAdministrable(operadorId)
                    .orElseThrow(this::operadorNoEncontrado);
            if (cuenta.empleadoId() != null) {
                throw error(HttpStatus.CONFLICT, "VINCULO_OCUPADO", "La cuenta ya está vinculada a un empleado.");
            }
            if (cuenta.revisionAcceso() != revisionOperador) {
                throw error(HttpStatus.PRECONDITION_FAILED, "REVISION_OBSOLETA",
                        "La información de la cuenta cambió. Actualízala antes de continuar.");
            }
            if (cuenta.revisionAcceso() == Long.MAX_VALUE) {
                throw servicioNoDisponible();
            }
            if (cuenta.estado() != EstadoCuentaOperador.ACTIVA
                    && cuenta.estado() != EstadoCuentaOperador.PENDIENTE
                    && cuenta.estado() != EstadoCuentaOperador.INACTIVA) {
                throw error(HttpStatus.CONFLICT, "TRANSICION_NO_PERMITIDA", "No se puede vincular esta cuenta.");
            }
            if (cuenta.estado() != EstadoCuentaOperador.INACTIVA
                    && !"ACTIVO".equals(empleado.estado())) {
                throw error(HttpStatus.CONFLICT, "EMPLEADO_INACTIVO",
                        "Activa al empleado antes de vincular una cuenta con acceso.");
            }
            String correoEmpleado = empleado.correo();
            String correoOperador = cuenta.correo();
            boolean copiar = correoEmpleado == null && correoOperador != null;
            boolean ambosSinCorreo = correoEmpleado == null && correoOperador == null;
            if (copiar) {
                if (!copiarCorreoOperador) {
                    throw error(HttpStatus.CONFLICT, "CONFIRMACION_CORREO_REQUERIDA",
                            "Confirma que quieres copiar el correo de la cuenta al empleado.");
                }
                correoEmpleado = validarCorreo(correoOperador, false);
                actualizarCorreoEmpleado(empleado, correoEmpleado, normalizarCorreo(correoEmpleado));
            } else if (!ambosSinCorreo && !java.util.Objects.equals(correoEmpleado, correoOperador)) {
                throw error(HttpStatus.CONFLICT, "CORREOS_DISTINTOS",
                        "Corrige los correos de forma explícita antes de vincular las cuentas.");
            }
            CuentaOperadorAdministrable vinculada = operadores.vincularCuenta(
                    operadorId, empleadoId, cuenta.revisionAcceso());
            if (!copiar) {
                incrementarRevisionEmpleado(empleado);
            }
            long revisionNueva = empleado.revision() + 1;
            acciones.completar(propietario.cuentaId(), claveHash, operadorId,
                    cuenta.estado().name(), revisionNueva, null);
            ResultadoAccionEmpleadoOperador respuesta = resultado(
                    empleadoId, vinculada.id(), vinculada.estado().name(), revisionNueva, null);
            return new TransicionCuenta(respuesta, operadorId,
                    cuenta.estado() == EstadoCuentaOperador.ACTIVA, true, null);
        });
        if (transicion == null) {
            throw servicioNoDisponible();
        }
        if (transicion.repetida() != null) {
            return resultado(transicion.repetida());
        }
        if (transicion.revocar()) {
            sesiones.revocarCuenta(transicion.operadorId());
        }
        if (transicion.cambio()) {
            publicarDirectorios(true, true);
        }
        return transicion.resultado();
    }

    @Override
    public ResultadoAccionEmpleadoOperador cambiarEstadoEmpleado(
            String idTexto, String estadoSolicitado, String ifMatch, PrincipalPropietario propietario) {
        exigirDueno(propietario);
        long empleadoId = validarId(idTexto);
        String estadoNuevo = validarEstadoEmpleado(estadoSolicitado);
        TransicionCuenta transicion = transaccion.execute(estado -> {
            EmpleadoEnlaceOperador empleado = empleados.bloquearPorId(empleadoId)
                    .orElseThrow(this::empleadoNoEncontrado);
            exigirRevision(empleado.revision(), validarIfMatch(ifMatch));
            if (empleado.revision() == Long.MAX_VALUE) {
                throw servicioNoDisponible();
            }
            if (empleado.estado().equals(estadoNuevo)) {
                return TransicionCuenta.sinCambio(resultado(
                        empleadoId, null, null, empleado.revision(), null));
            }
            Optional<CuentaOperadorAdministrable> vinculada = operadores.bloquearCuentaVinculada(empleadoId);
            UUID operadorId = null;
            boolean revocar = false;
            boolean cuentaCambio = false;
            if ("INACTIVO".equals(estadoNuevo) && vinculada.isPresent()) {
                CuentaOperadorAdministrable cuenta = vinculada.get();
                operadorId = cuenta.id();
                if (cuenta.estado() != EstadoCuentaOperador.INACTIVA) {
                    if (cuenta.revisionAcceso() == Long.MAX_VALUE) {
                        throw servicioNoDisponible();
                    }
                    invitaciones.invalidarPendientes(cuenta.id());
                    operadores.actualizarEstado(cuenta.id(), EstadoCuentaOperador.INACTIVA,
                            cuenta.revisionAcceso(), cuenta.revisionAcceso() + 1);
                    revocar = true;
                    cuentaCambio = true;
                }
            }
            if (!empleados.actualizarEstadoYRevision(empleadoId, estadoNuevo, empleado.revision())) {
                throw error(HttpStatus.PRECONDITION_FAILED, "REVISION_OBSOLETA",
                        "La información cambió. Actualiza la lista antes de continuar.");
            }
            return new TransicionCuenta(resultado(
                    empleadoId, operadorId,
                    cuentaCambio ? EstadoCuentaOperador.INACTIVA.name()
                            : vinculada.map(cuenta -> cuenta.estado().name()).orElse(null),
                    empleado.revision() + 1, null), operadorId, revocar, true, null);
        });
        if (transicion == null) {
            throw servicioNoDisponible();
        }
        if (transicion.revocar() && transicion.operadorId() != null) {
            sesiones.revocarCuenta(transicion.operadorId());
        }
        if (transicion.cambio()) {
            publicarDirectorios(true, transicion.operadorId() != null);
        }
        return transicion.resultado();
    }

    private EstadoEnvioInvitacion enviarPromocion(TransicionPromocion transicion) {
        try {
            if (transicion.inicial()) {
                return activacion.enviarInicial(transicion.preparacion());
            }
            return invitaciones.enviarReactivacion(transicion.preparacion());
        } catch (RuntimeException excepcion) {
            return EstadoEnvioInvitacion.DESCONOCIDO;
        }
    }

    private AccionEmpleadoOperadorPersistida reservarOReproducir(
            UUID duenoId, String claveHash, String huella, String operacion, long empleadoId) {
        if (acciones.reservar(duenoId, claveHash, huella, operacion, empleadoId)) {
            return null;
        }
        AccionEmpleadoOperadorPersistida accion = acciones.bloquear(duenoId, claveHash)
                .orElseThrow(ServicioAdministracionEmpleadoOperador::servicioNoDisponible);
        if (!hashesIguales(accion.huellaSolicitud(), huella)) {
            throw error(HttpStatus.CONFLICT, "CLAVE_IDEMPOTENCIA_REUTILIZADA",
                    "La clave ya se usó para otra solicitud.");
        }
        if (!"COMPLETADA".equals(accion.estado()) || accion.revisionEmpleado() == null) {
            throw servicioNoDisponible();
        }
        return accion;
    }

    private void actualizarCorreoEmpleado(EmpleadoEnlaceOperador empleado, String correo, String normalizado) {
        if (!empleados.actualizarCorreoYRevision(empleado.id(), correo, normalizado, empleado.revision())) {
            throw error(HttpStatus.PRECONDITION_FAILED, "REVISION_OBSOLETA",
                    "La información cambió. Actualiza la lista antes de continuar.");
        }
    }

    private void incrementarRevisionEmpleado(EmpleadoEnlaceOperador empleado) {
        if (!empleados.incrementarRevision(empleado.id(), empleado.revision())) {
            throw error(HttpStatus.PRECONDITION_FAILED, "REVISION_OBSOLETA",
                    "La información cambió. Actualiza la lista antes de continuar.");
        }
    }

    private static ResultadoAccionEmpleadoOperador resultado(
            long empleadoId, UUID operadorId, String estadoOperador, long revisionEmpleado, String estadoEnvio) {
        return new ResultadoAccionEmpleadoOperador(
                Long.toString(empleadoId), operadorId, estadoOperador,
                Long.toString(revisionEmpleado), estadoEnvio);
    }

    private static ResultadoAccionEmpleadoOperador resultado(AccionEmpleadoOperadorPersistida accion) {
        return resultado(accion.empleadoId(), accion.operadorId(), accion.estadoOperador(),
                accion.revisionEmpleado(), accion.estadoEnvio());
    }

    private static ResultadoCambioCorreoEmpleadoOperador resultadoCorreo(
            long empleadoId, String correo, UUID operadorId, EstadoCuentaOperador estado,
            long revision, String envio) {
        return new ResultadoCambioCorreoEmpleadoOperador(
                Long.toString(empleadoId), correo, operadorId,
                estado == null ? null : estado.name(), Long.toString(revision), envio);
    }

    private static ResultadoCambioCorreoEmpleadoOperador resultadoCorreo(TransicionCorreo transicion, String envio) {
        ResultadoCambioCorreoEmpleadoOperador anterior = transicion.respuesta();
        return new ResultadoCambioCorreoEmpleadoOperador(
                anterior.empleadoId(), anterior.correo(), anterior.operadorId(), anterior.estadoOperador(),
                anterior.revisionEmpleado(), envio == null ? anterior.estadoInvitacion() : envio);
    }

    private static ResultadoCambioCorreoEmpleadoOperador resultadoCorreo(
            AccionEmpleadoOperadorPersistida accion, String correo) {
        return new ResultadoCambioCorreoEmpleadoOperador(
                Long.toString(accion.empleadoId()), correo, accion.operadorId(), accion.estadoOperador(),
                accion.revisionEmpleado() == null ? null : Long.toString(accion.revisionEmpleado()),
                accion.estadoEnvio());
    }

    private static ResultadoCambioCorreoEmpleadoOperador conEnvio(
            ResultadoCambioCorreoEmpleadoOperador resultado, String envio) {
        return new ResultadoCambioCorreoEmpleadoOperador(
                resultado.empleadoId(), resultado.correo(), resultado.operadorId(), resultado.estadoOperador(),
                resultado.revisionEmpleado(), envio == null ? resultado.estadoInvitacion() : envio);
    }

    private static ResultadoAccionEmpleadoOperador conEnvio(
            ResultadoAccionEmpleadoOperador resultado, String envio) {
        return new ResultadoAccionEmpleadoOperador(
                resultado.empleadoId(), resultado.operadorId(), resultado.estadoOperador(),
                resultado.revisionEmpleado(), envio == null ? resultado.estadoInvitacion() : envio);
    }

    private static String validarCorreo(String correo, boolean opcional) {
        String normalizado = correo == null ? null : correo.trim().toLowerCase(Locale.ROOT);
        if (normalizado == null || normalizado.isEmpty()) {
            if (opcional) {
                return null;
            }
            throw error(HttpStatus.CONFLICT, "CORREO_REQUERIDO", "Agrega un correo antes de dar acceso al operador.");
        }
        if (normalizado.length() > MAXIMO_CORREO || normalizado.indexOf('\0') >= 0
                || !FORMATO_CORREO.matcher(normalizado).matches()) {
            throw error(HttpStatus.BAD_REQUEST, "CORREO_NO_VALIDO", "Ingresa un correo válido.");
        }
        return normalizado;
    }

    private static String normalizarCorreo(String correo) {
        return correo == null ? null : correo.trim().toLowerCase(Locale.ROOT);
    }

    private static boolean igualCorreo(String primero, String segundo) {
        return java.util.Objects.equals(primero, segundo);
    }

    private static long validarId(String texto) {
        if (texto == null || !texto.matches("[1-9][0-9]{0,18}")) {
            throw error(HttpStatus.BAD_REQUEST, "IDENTIFICADOR_NO_VALIDO", "El identificador del empleado no es válido.");
        }
        try {
            long id = Long.parseLong(texto);
            if (id < 1) {
                throw new NumberFormatException("El identificador debe ser positivo.");
            }
            return id;
        } catch (NumberFormatException excepcion) {
            throw error(HttpStatus.BAD_REQUEST, "IDENTIFICADOR_NO_VALIDO", "El identificador del empleado no es válido.");
        }
    }

    private static long validarIfMatch(String ifMatch) {
        if (ifMatch == null) {
            throw error(HttpStatus.PRECONDITION_REQUIRED, "REVISION_REQUERIDA",
                    "Actualiza la información antes de continuar.");
        }
        if (ifMatch.length() < 3 || ifMatch.charAt(0) != '"' || ifMatch.charAt(ifMatch.length() - 1) != '"') {
            throw error(HttpStatus.BAD_REQUEST, "REVISION_NO_VALIDA", "La revisión enviada no es válida.");
        }
        return validarRevisionDecimal(ifMatch.substring(1, ifMatch.length() - 1));
    }

    private static long validarRevisionDecimal(String texto) {
        if (texto == null || !texto.matches("[0-9]{1,19}")) {
            throw error(HttpStatus.BAD_REQUEST, "REVISION_NO_VALIDA", "La revisión enviada no es válida.");
        }
        try {
            return Long.parseLong(texto);
        } catch (NumberFormatException excepcion) {
            throw error(HttpStatus.BAD_REQUEST, "REVISION_NO_VALIDA", "La revisión enviada no es válida.");
        }
    }

    private static String validarEstadoEmpleado(String texto) {
        if ("ACTIVO".equals(texto) || "INACTIVO".equals(texto)) {
            return texto;
        }
        throw error(HttpStatus.BAD_REQUEST, "ESTADO_NO_VALIDO", "Selecciona un estado válido para el empleado.");
    }

    private static void exigirRevision(long actual, long esperada) {
        if (actual != esperada) {
            throw error(HttpStatus.PRECONDITION_FAILED, "REVISION_OBSOLETA",
                    "La información cambió. Actualiza la lista antes de continuar.");
        }
    }

    private static void exigirEmpleadoActivo(EmpleadoEnlaceOperador empleado) {
        if (!"ACTIVO".equals(empleado.estado())) {
            throw error(HttpStatus.CONFLICT, "EMPLEADO_INACTIVO",
                    "Activa al empleado antes de dar acceso de operador.");
        }
    }

    private static String hashClave(String clave) {
        try {
            return SeguridadTokensOperador.hashClaveIdempotencia(clave);
        } catch (ErrorConfiguracion excepcion) {
            throw excepcion;
        } catch (RuntimeException excepcion) {
            throw error(HttpStatus.BAD_REQUEST, "CLAVE_IDEMPOTENCIA_NO_VALIDA",
                    "No pudimos completar el cambio. Inténtalo de nuevo.");
        }
    }

    private static String huella(String... campos) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            for (String campo : campos) {
                if (campo == null) {
                    digest.update(ByteBuffer.allocate(Integer.BYTES).putInt(-1).array());
                } else {
                    byte[] bytes = campo.getBytes(StandardCharsets.UTF_8);
                    digest.update(ByteBuffer.allocate(Integer.BYTES).putInt(bytes.length).array());
                    digest.update(bytes);
                }
            }
            return java.util.HexFormat.of().formatHex(digest.digest());
        } catch (NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException("No pudimos completar el cambio.", excepcion);
        }
    }

    private static boolean hashesIguales(String primero, String segundo) {
        return primero != null && segundo != null && MessageDigest.isEqual(
                primero.getBytes(StandardCharsets.US_ASCII), segundo.getBytes(StandardCharsets.US_ASCII));
    }

    private static void exigirDueno(PrincipalPropietario principal) {
        if (principal == null) {
            throw error(HttpStatus.UNAUTHORIZED, "SESION_NO_VIGENTE", "Tu acceso venció. Inicia sesión de nuevo.");
        }
        if (principal.rol() != RolCuenta.DUENO) {
            throw error(HttpStatus.FORBIDDEN, "PERMISO_INSUFICIENTE", "No tienes acceso para hacer este cambio.");
        }
    }

    private void publicarDirectorios(boolean empleadosActualizados, boolean operadoresActualizados) {
        if (empleadosActualizados) {
            try {
                eventos.publicarDirectorioActualizado();
            } catch (RuntimeException excepcion) {
                System.getLogger(getClass().getName()).log(
                        System.Logger.Level.WARNING, "No se pudo publicar el directorio de empleados.");
            }
        }
        if (operadoresActualizados) {
            try {
                eventos.publicarDirectorioOperadorActualizado();
            } catch (RuntimeException excepcion) {
                System.getLogger(getClass().getName()).log(
                        System.Logger.Level.WARNING, "No se pudo publicar el directorio de operadores.");
            }
        }
    }

    private ErrorConfiguracion empleadoNoEncontrado() {
        return error(HttpStatus.NOT_FOUND, "EMPLEADO_NO_ENCONTRADO", "No encontramos a este empleado.");
    }

    private ErrorConfiguracion operadorNoEncontrado() {
        return error(HttpStatus.NOT_FOUND, "OPERADOR_NO_ENCONTRADO", "No encontramos esta cuenta.");
    }

    private static ErrorConfiguracion correoEnUso() {
        return error(HttpStatus.CONFLICT, "CORREO_EN_USO", "El correo ya está reservado para otra cuenta.");
    }

    private static ErrorConfiguracion servicioNoDisponible() {
        return error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                "No pudimos completar esto ahora. Inténtalo más tarde.");
    }

    private static ErrorConfiguracion error(HttpStatus status, String codigo, String mensaje) {
        return new ErrorConfiguracion(status, mensaje, codigo);
    }

    private record TransicionPromocion(
            ResultadoAccionEmpleadoOperador resultado,
            PreparacionInvitacionOperador preparacion,
            boolean inicial,
            AccionEmpleadoOperadorPersistida repetida) {
        private static TransicionPromocion reproducida(AccionEmpleadoOperadorPersistida accion) {
            return new TransicionPromocion(null, null, false, accion);
        }
    }

    private record TransicionCorreo(
            ResultadoCambioCorreoEmpleadoOperador respuesta,
            PreparacionInvitacionOperador preparacion,
            UUID operadorId,
            boolean revocar,
            boolean publicar,
            AccionEmpleadoOperadorPersistida repetida,
            ResultadoCambioCorreoEmpleadoOperador sinEnvio) {
        private static TransicionCorreo reproducida(AccionEmpleadoOperadorPersistida accion) {
            return new TransicionCorreo(null, null, null, false, false, accion, null);
        }

        private static TransicionCorreo sinCambio(long empleadoId, String correo, long revision) {
            return new TransicionCorreo(resultadoCorreo(empleadoId, correo, null, null, revision, null),
                    null, null, false, false, null, resultadoCorreo(empleadoId, correo, null, null, revision, null));
        }

        private static TransicionCorreo sinCambio(
                long empleadoId, String correo, long revision, UUID operadorId, EstadoCuentaOperador estado) {
            return sinEnvio(empleadoId, correo, revision, operadorId, estado, null, false);
        }

        private static TransicionCorreo sinEnvio(
                long empleadoId, String correo, long revision, UUID operadorId,
                EstadoCuentaOperador estado, String envio, boolean publicar) {
            ResultadoCambioCorreoEmpleadoOperador respuesta = resultadoCorreo(
                    empleadoId, correo, operadorId, estado, revision, envio);
            return new TransicionCorreo(respuesta, null, operadorId, false, publicar, null, respuesta);
        }
    }

    private record TransicionCuenta(
            ResultadoAccionEmpleadoOperador resultado,
            UUID operadorId,
            boolean revocar,
            boolean cambio,
            AccionEmpleadoOperadorPersistida repetida) {
        private static TransicionCuenta reproducida(AccionEmpleadoOperadorPersistida accion) {
            return new TransicionCuenta(ServicioAdministracionEmpleadoOperador.resultado(accion),
                    accion.operadorId(), false, false, accion);
        }

        private static TransicionCuenta sinCambio(ResultadoAccionEmpleadoOperador resultado) {
            return new TransicionCuenta(resultado, resultado.operadorId(), false, false, null);
        }
    }
}
