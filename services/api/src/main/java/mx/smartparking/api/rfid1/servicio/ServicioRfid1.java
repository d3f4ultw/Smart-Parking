package mx.smartparking.api.rfid1.servicio;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.TipoEstacionamiento;
import mx.smartparking.api.eventos.PublicadorCapturaRfid1;
import mx.smartparking.api.rfid1.PoliticaModalidadRfid1;
import mx.smartparking.api.rfid1.modelo.CapturaRfid1;
import mx.smartparking.api.rfid1.modelo.RespuestaLecturaRfid1;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.CapturaRfid1Persistida;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.DestinoRfid1Persistido;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.NuevaCapturaRfid1;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.ResultadoEstadoCaptura;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.ResultadoLecturaRfid1;
import mx.smartparking.api.persistencia.ConfiguracionPersistida;
import mx.smartparking.api.persistencia.RepositorioConfiguracion;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Administra la lectura de tarjetas y comprueba que cada una se asocie solo a la persona autorizada. */
@Service
public class ServicioRfid1 {

    private static final Duration DURACION_CAPTURA = Duration.ofSeconds(120);
    private static final Duration RETENCION_TERMINALES = Duration.ofHours(24);
    private final RepositorioRfid1 repositorio;
    private final RepositorioConfiguracion configuracion;
    private final TransactionTemplate transaccion;
    private final Clock reloj;
    private final PublicadorCapturaRfid1 publicadorCapturas;

    @Autowired
    public ServicioRfid1(
            RepositorioRfid1 repositorio,
            RepositorioConfiguracion configuracion,
            PlatformTransactionManager administradorTransacciones,
            PublicadorCapturaRfid1 publicadorCapturas) {
        this(repositorio, configuracion, administradorTransacciones, Clock.systemUTC(), publicadorCapturas);
    }

    ServicioRfid1(
            RepositorioRfid1 repositorio,
            RepositorioConfiguracion configuracion,
            PlatformTransactionManager administradorTransacciones,
            Clock reloj,
            PublicadorCapturaRfid1 publicadorCapturas) {
        this.repositorio = repositorio;
        this.configuracion = configuracion;
        this.transaccion = new TransactionTemplate(administradorTransacciones);
        this.reloj = reloj;
        this.publicadorCapturas = publicadorCapturas;
    }

    /**
     * Inicia una lectura RFID1 o devuelve la anterior si se repite. Rechaza clientes con estado
     * {@code SIN_MEMBRESIA}.
     */
    public CapturaRfid1 crearCaptura(
            String tipoEntidad,
            String codigoPersona,
            String claveIdempotencia,
            String huellaSesion,
            PrincipalPropietario propietario) {
        exigirAccesoAdministrativo(propietario);
        ValidacionesRfid1.huellaSesion(huellaSesion);
        String tipo = ValidacionesRfid1.tipoEntidad(tipoEntidad);
        String codigo = ValidacionesRfid1.codigoPersona(codigoPersona);
        ValidacionesRfid1.claveInicio(claveIdempotencia);
        String claveHash = ClavesRfid1.hashClave(claveIdempotencia);
        String huella = ClavesRfid1.huellaSolicitud(tipo, codigo);
        long revisionPropietarioCaptura = RevisionCapturaRfid1.persistida(propietario);

        ResultadoTransicion<CapturaRfid1Persistida> transicion = transaccion.execute(estado -> {
            Instant ahora = reloj.instant();
            boolean huboExpiraciones = repositorio.expirarCapturasVencidas(ahora) > 0;
            repositorio.purgarCapturasTerminalesAnterioresA(ahora.minus(RETENCION_TERMINALES));
            repositorio.buscarActivaParaDispositivo(ahora);
            TipoEstacionamiento modalidad = tipoEstacionamiento(configuracion.bloquear());
            if (!PoliticaModalidadRfid1.permite(modalidad, tipo)) {
                throw error(HttpStatus.CONFLICT, "TIPO_ENTIDAD_NO_DISPONIBLE",
                        "El tipo de persona no está permitido por la modalidad actual.");
            }
            Optional<CapturaRfid1Persistida> previa = repositorio.buscarPorIdempotencia(
                    propietario.cuentaId(), claveHash, huellaSesion);
            if (previa.isPresent()) {
                return new ResultadoTransicion<>(
                        reproducirInicio(previa.get(), huella, huellaSesion, propietario, revisionPropietarioCaptura),
                        huboExpiraciones);
            }

            if (repositorio.buscarActivaDePropietario(
                    propietario.cuentaId(), propietario.revisionAcceso(), revisionPropietarioCaptura,
                    huellaSesion, ahora)
                    .isPresent()) {
                throw error(HttpStatus.CONFLICT, "CAPTURA_EN_CURSO",
                        "Ya hay una captura en curso. Espera a que termine antes de iniciar otra.");
            }

            DestinoRfid1Persistido destino = repositorio.resolverDestino(tipo, codigo)
                    .orElseThrow(() -> error(HttpStatus.NOT_FOUND, "PERSONA_NO_ENCONTRADA",
                            "No encontramos a la persona indicada."));
            if (!destino.activo()) {
                throw error(HttpStatus.CONFLICT, "PERSONA_INACTIVA",
                        "La persona no está activa para recibir una tarjeta.");
            }
            if (destino.sinMembresia()) {
                throw error(HttpStatus.CONFLICT, "CLIENTE_SIN_MEMBRESIA",
                        "No se puede asociar una tarjeta a un cliente sin membresía.");
            }
            if (repositorio.destinoTieneTarjeta(destino)) {
                throw error(HttpStatus.CONFLICT, "PERSONA_CON_TARJETA",
                        "La persona ya tiene una tarjeta asociada.");
            }

            Instant venceEn = ahora.plus(DURACION_CAPTURA);
            String capturaId = nuevoIdCaptura();
            NuevaCapturaRfid1 nueva = new NuevaCapturaRfid1(
                    capturaId, tipo, codigo, destino.clienteId(), destino.empleadoId(), propietario.cuentaId(),
                    propietario.revisionAcceso(), revisionPropietarioCaptura, huellaSesion, claveHash, huella,
                    ahora, venceEn);
            if (repositorio.insertarCaptura(nueva)) {
                return new ResultadoTransicion<>(capturaNueva(nueva), true);
            }

            Optional<CapturaRfid1Persistida> concurrente = repositorio.buscarPorIdempotencia(
                    propietario.cuentaId(), claveHash, huellaSesion);
            if (concurrente.isPresent()) {
                return new ResultadoTransicion<>(
                        reproducirInicio(
                                concurrente.get(), huella, huellaSesion, propietario, revisionPropietarioCaptura),
                        huboExpiraciones);
            }
            throw error(HttpStatus.CONFLICT, "CAPTURA_EN_CURSO",
                    "Ya hay una captura en curso. Espera a que termine antes de iniciar otra.");
        });
        if (transicion == null) {
            throw servicioNoDisponible();
        }
        publicarSiActualizada(transicion.huboCambio());
        return CapturaRfid1.desde(transicion.valor());
    }

    /** Busca la lectura pendiente que pertenece a la cuenta y sesión autorizadas. */
    public Optional<CapturaRfid1> consultarCapturaActiva(String huellaSesion, PrincipalPropietario propietario) {
        exigirAccesoAdministrativo(propietario);
        ValidacionesRfid1.huellaSesion(huellaSesion);
        long revisionPropietarioCaptura = RevisionCapturaRfid1.persistida(propietario);
        ResultadoTransicion<Optional<CapturaRfid1Persistida>> transicion = transaccion.execute(estado -> {
            Instant ahora = reloj.instant();
            boolean huboExpiraciones = repositorio.expirarCapturasVencidas(ahora) > 0;
            Optional<CapturaRfid1Persistida> activa = repositorio.buscarActivaDePropietario(
                    propietario.cuentaId(), propietario.revisionAcceso(), revisionPropietarioCaptura,
                    huellaSesion, ahora);
            return new ResultadoTransicion<>(activa, huboExpiraciones);
        });
        if (transicion == null) {
            return Optional.empty();
        }
        publicarSiActualizada(transicion.huboCambio());
        return transicion.valor().map(CapturaRfid1::desde);
    }

    /** Consulta el estado de una lectura después de comprobar que la cuenta autorizada sigue vigente. */
    public CapturaRfid1 consultarCaptura(String capturaId, String huellaSesion, PrincipalPropietario propietario) {
        exigirAccesoAdministrativo(propietario);
        ValidacionesRfid1.huellaSesion(huellaSesion);
        ValidacionesRfid1.capturaId(capturaId);
        long revisionPropietarioCaptura = RevisionCapturaRfid1.persistida(propietario);
        ResultadoTransicion<CapturaRfid1Persistida> transicion = transaccion.execute(estado -> {
            boolean huboExpiraciones = repositorio.expirarCapturasVencidas(reloj.instant()) > 0;
            CapturaRfid1Persistida captura = repositorio.buscarPorPropietario(
                    capturaId, propietario.cuentaId(), propietario.revisionAcceso(),
                    revisionPropietarioCaptura, huellaSesion)
                    .orElseThrow(() -> capturaNoEncontrada());
            return new ResultadoTransicion<>(captura, huboExpiraciones);
        });
        if (transicion == null) {
            throw servicioNoDisponible();
        }
        publicarSiActualizada(transicion.huboCambio());
        return CapturaRfid1.desde(transicion.valor());
    }

    /** Cancela una lectura que aún está pendiente sin modificar las lecturas que ya terminaron. */
    public void cancelarCaptura(String capturaId, String huellaSesion, PrincipalPropietario propietario) {
        exigirAccesoAdministrativo(propietario);
        ValidacionesRfid1.huellaSesion(huellaSesion);
        ValidacionesRfid1.capturaId(capturaId);
        long revisionPropietarioCaptura = RevisionCapturaRfid1.persistida(propietario);
        ResultadoTransicion<ResultadoEstadoCaptura> transicion = transaccion.execute(estado -> {
            Instant ahora = reloj.instant();
            boolean huboExpiraciones = repositorio.expirarCapturasVencidas(ahora) > 0;
            Optional<CapturaRfid1Persistida> previa = repositorio.buscarPorPropietario(
                    capturaId, propietario.cuentaId(), propietario.revisionAcceso(),
                    revisionPropietarioCaptura, huellaSesion);
            boolean estabaActiva = previa.map(ServicioRfid1::estaActiva).orElse(false);
            ResultadoEstadoCaptura resultado = repositorio.cancelar(
                    capturaId, propietario.cuentaId(), propietario.revisionAcceso(),
                    revisionPropietarioCaptura, huellaSesion, ahora);
            return new ResultadoTransicion<>(resultado, huboExpiraciones || estabaActiva);
        });
        if (transicion == null) {
            throw servicioNoDisponible();
        }
        publicarSiActualizada(transicion.huboCambio());
        ResultadoEstadoCaptura resultado = transicion.valor();
        exigirResultadoEstado(resultado);
        if (!"CANCELADA".equals(resultado.estado())) {
            throw error(HttpStatus.CONFLICT, "CAPTURA_NO_VIGENTE", "La captura ya no está vigente.");
        }
    }

    /** Indica al dispositivo qué lectura atender solo si la cuenta que la inició sigue autorizada. */
    public Optional<CapturaRfid1> consultarCapturaActivaDispositivo() {
        ResultadoTransicion<Optional<CapturaRfid1Persistida>> transicion = transaccion.execute(estado -> {
            Instant ahora = reloj.instant();
            boolean huboExpiraciones = repositorio.expirarCapturasVencidas(ahora) > 0;
            Optional<CapturaRfid1Persistida> activa = repositorio.buscarActivaParaDispositivo(ahora);
            return new ResultadoTransicion<>(activa, huboExpiraciones);
        });
        if (transicion == null) {
            return Optional.empty();
        }
        publicarSiActualizada(transicion.huboCambio());
        return transicion.valor().map(CapturaRfid1::desde);
    }

    /** Registra que el lector busca la tarjeta solo si la lectura y la cuenta autorizada siguen vigentes. */
    public void informarEscaneando(String capturaId) {
        ValidacionesRfid1.capturaId(capturaId);
        ResultadoTransicion<ResultadoEstadoCaptura> transicion = transaccion.execute(estado -> {
            Instant ahora = reloj.instant();
            boolean huboExpiraciones = repositorio.expirarCapturasVencidas(ahora) > 0;
            Optional<CapturaRfid1Persistida> activa = repositorio.buscarActivaParaDispositivo(ahora);
            boolean iniciaEscaneo = activa.filter(captura -> captura.capturaId().equals(capturaId))
                    .map(captura -> "PENDIENTE".equals(captura.estado())).orElse(false);
            ResultadoEstadoCaptura resultado = repositorio.marcarEscaneando(capturaId, ahora);
            return new ResultadoTransicion<>(resultado, huboExpiraciones || iniciaEscaneo);
        });
        if (transicion == null) {
            throw servicioNoDisponible();
        }
        publicarSiActualizada(transicion.huboCambio());
        ResultadoEstadoCaptura resultado = transicion.valor();
        exigirResultadoEstado(resultado);
        if (!"ESCANEANDO".equals(resultado.estado())) {
            throw error(HttpStatus.CONFLICT, "CAPTURA_NO_VIGENTE", "La captura ya no está vigente.");
        }
    }

    /** Guarda el resultado de una lectura de tarjeta y devuelve ese mismo resultado si se repite. */
    public RespuestaLecturaRfid1 procesarLectura(
            String capturaId,
            String requestId,
            String uid,
            String claveIdempotencia) {
        ValidacionesRfid1.capturaId(capturaId);
        String requestNormalizado = ValidacionesRfid1.requestId(requestId);
        String uidCanonico = ValidacionesRfid1.uid(uid);
        ValidacionesRfid1.claveLectura(capturaId, requestNormalizado, claveIdempotencia);

        ResultadoTransicion<ResultadoLecturaRfid1> transicion = transaccion.execute(estado -> {
            Instant ahora = reloj.instant();
            boolean huboExpiraciones = repositorio.expirarCapturasVencidas(ahora) > 0;
            ResultadoLecturaRfid1 resultado = repositorio.completarLectura(
                    capturaId, requestNormalizado, uidCanonico, ClavesRfid1.huellaUid(uidCanonico), ahora);
            boolean actualizada = resultado != null && !resultado.repetida()
                    && ("COMPLETADA".equals(resultado.estado()) || "RECHAZADA".equals(resultado.estado())
                            || "VISTA_PREVIA".equals(resultado.estado())
                            || "TARJETA_YA_REGISTRADA".equals(resultado.codigoError()));
            return new ResultadoTransicion<>(resultado, huboExpiraciones || actualizada);
        });
        if (transicion == null) {
            throw servicioNoDisponible();
        }
        publicarSiActualizada(transicion.huboCambio());
        ResultadoLecturaRfid1 resultado = transicion.valor();
        if (resultado == null) {
            throw servicioNoDisponible();
        }
        if (resultado.codigoError() != null) {
            throw errorLectura(resultado.codigoError());
        }
        return new RespuestaLecturaRfid1(capturaId, resultado.estado(), resultado.resultado());
    }

    private CapturaRfid1Persistida reproducirInicio(
            CapturaRfid1Persistida previa,
            String huella,
            String huellaSesion,
            PrincipalPropietario propietario,
            long revisionPropietarioCaptura) {
        if (!previa.huellaSolicitud().equals(huella)) {
            throw error(HttpStatus.CONFLICT, "CLAVE_IDEMPOTENCIA_EN_CONFLICTO",
                    "La clave ya se usó con otra solicitud.");
        }
        if (previa.revisionAcceso() != propietario.revisionAcceso()
                || previa.revisionPropietario() != revisionPropietarioCaptura
                || !huellaSesion.equals(previa.huellaSesion())) {
            throw error(HttpStatus.CONFLICT, "CAPTURA_NO_VIGENTE", "La captura ya no está vigente.");
        }
        return previa;
    }

    private CapturaRfid1Persistida capturaNueva(NuevaCapturaRfid1 nueva) {
        return new CapturaRfid1Persistida(
                nueva.capturaId(), nueva.tipoEntidad(), nueva.codigoPersona(), nueva.clienteId(), nueva.empleadoId(),
                nueva.propietarioId(), nueva.revisionAcceso(), nueva.revisionPropietario(), nueva.huellaSesion(),
                nueva.claveIdempotenciaHash(), nueva.huellaSolicitud(), null, null, "PENDIENTE", null, null,
                nueva.creadaEn(), nueva.venceEn(), null, null, null, null, null, null);
    }

    private void exigirResultadoEstado(ResultadoEstadoCaptura resultado) {
        if (resultado == null) {
            throw servicioNoDisponible();
        }
        if (resultado.codigoError() != null) {
            throw errorCaptura(resultado.codigoError());
        }
    }

    private static boolean estaActiva(CapturaRfid1Persistida captura) {
        return "PENDIENTE".equals(captura.estado()) || "ESCANEANDO".equals(captura.estado())
                || "VISTA_PREVIA".equals(captura.estado());
    }

    private void publicarSiActualizada(boolean huboCambio) {
        publicadorCapturas.publicarSiActualizada(huboCambio);
    }

    private String nuevoIdCaptura() {
        return UUID.randomUUID().toString().replace("-", "");
    }

    private static void exigirAccesoAdministrativo(PrincipalPropietario propietario) {
        if (propietario == null) {
            throw error(HttpStatus.UNAUTHORIZED, "SESION_NO_VIGENTE", "Inicia sesión para continuar.");
        }
        if (propietario.rol() != RolCuenta.DUENO && propietario.rol() != RolCuenta.OPERADOR) {
            throw error(HttpStatus.FORBIDDEN, "PERMISO_INSUFICIENTE", "No tienes acceso para hacer este cambio.");
        }
    }

    private static TipoEstacionamiento tipoEstacionamiento(ConfiguracionPersistida actual) {
        return actual == null || actual.estado() == null
                || !"CONFIGURADA".equals(actual.estado().name()) ? null : actual.tipoEstacionamiento();
    }

    private static RuntimeException errorCaptura(String codigo) {
        return switch (codigo) {
            case "CAPTURA_NO_ENCONTRADA" -> capturaNoEncontrada();
            case "PERSONA_NO_ENCONTRADA" -> error(HttpStatus.NOT_FOUND, codigo, "No encontramos a la persona indicada.");
            case "CAPTURA_NO_VIGENTE" -> error(HttpStatus.CONFLICT, codigo, "La captura ya no está vigente.");
            case "PERSONA_CON_TARJETA" -> error(HttpStatus.CONFLICT, codigo, "La persona ya tiene una tarjeta asociada.");
            case "TARJETA_YA_REGISTRADA", "TARJETA_ASOCIADA" -> error(HttpStatus.CONFLICT, "TARJETA_YA_REGISTRADA",
                    "La tarjeta ya está registrada. Inténtalo con otra tarjeta.");
            case "LECTURA_NO_VALIDA" -> error(HttpStatus.BAD_REQUEST, codigo, "La lectura no es válida.");
            default -> error(HttpStatus.CONFLICT, codigo, "La captura no está disponible.");
        };
    }

    private static RuntimeException errorLectura(String codigo) {
        return errorCaptura(codigo);
    }

    private static RuntimeException capturaNoEncontrada() {
        return error(HttpStatus.NOT_FOUND, "CAPTURA_NO_ENCONTRADA", "No encontramos la captura.");
    }

    private static ErrorConfiguracion error(HttpStatus estado, String codigo, String mensaje) {
        return new ErrorConfiguracion(estado, mensaje, codigo);
    }

    private static ErrorConfiguracion servicioNoDisponible() {
        return error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                "No pudimos confirmar la captura. Inténtalo más tarde.");
    }

    private record ResultadoTransicion<T>(T valor, boolean huboCambio) { }
}
