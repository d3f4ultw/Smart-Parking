package mx.smartparking.api.rfid1.servicio;

import java.time.Clock;
import java.time.Instant;
import java.util.Optional;
import java.util.regex.Pattern;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.PublicadorCapturaRfid1;
import mx.smartparking.api.eventos.PublicadorTarjetasRfid1;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.Confirmacion;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.VistaPrevia;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.ResultadoConfirmacionRfid1;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Muestra el número privado de una tarjeta a quien tiene permiso y confirma su asociación cuando lo
 * solicita.
 */
@Service
public class ServicioConfirmacionRfid1 {

    private static final Pattern FORMATO_CAPTURA = Pattern.compile("[0-9a-f]{32}");
    private static final Pattern FORMATO_HUELLA = Pattern.compile("[0-9a-f]{64}");
    private final RepositorioRfid1 repositorio;
    private final TransactionTemplate transaccion;
    private final Clock reloj;
    private final PublicadorCapturaRfid1 publicadorCapturas;
    private final PublicadorTarjetasRfid1 publicadorTarjetas;

    @Autowired
    public ServicioConfirmacionRfid1(
            RepositorioRfid1 repositorio,
            PlatformTransactionManager administradorTransacciones,
            PublicadorCapturaRfid1 publicadorCapturas,
            PublicadorTarjetasRfid1 publicadorTarjetas) {
        this(repositorio, administradorTransacciones, Clock.systemUTC(), publicadorCapturas, publicadorTarjetas);
    }

    ServicioConfirmacionRfid1(
            RepositorioRfid1 repositorio,
            PlatformTransactionManager administradorTransacciones,
            Clock reloj,
            PublicadorCapturaRfid1 publicadorCapturas,
            PublicadorTarjetasRfid1 publicadorTarjetas) {
        this.repositorio = repositorio;
        this.transaccion = new TransactionTemplate(administradorTransacciones);
        this.reloj = reloj;
        this.publicadorCapturas = publicadorCapturas;
        this.publicadorTarjetas = publicadorTarjetas;
    }

    /** Muestra el número de tarjeta únicamente a la cuenta y sesión que iniciaron esa lectura. */
    public VistaPrevia consultarVistaPrevia(
            String capturaId, String huellaSesion, PrincipalPropietario propietario) {
        exigirContexto(capturaId, huellaSesion, propietario);
        long revisionPropietarioCaptura = RevisionCapturaRfid1.persistida(propietario);
        TransicionVistaPrevia transicion;
        try {
            transicion = transaccion.execute(estado -> {
                Instant ahora = reloj.instant();
                boolean huboExpiraciones = repositorio.expirarCapturasVencidas(ahora) > 0;
                Optional<RepositorioRfid1.VistaPreviaRfid1Persistida> previa = repositorio.consultarVistaPrevia(
                        capturaId, propietario.cuentaId(), propietario.revisionAcceso(),
                        revisionPropietarioCaptura, huellaSesion, ahora);
                return new TransicionVistaPrevia(previa, huboExpiraciones);
            });
        } catch (DataAccessException excepcion) {
            throw servicioNoDisponible();
        }
        if (transicion == null) {
            throw servicioNoDisponible();
        }
        publicadorCapturas.publicarSiActualizada(transicion.huboExpiraciones());
        if (transicion.previa() == null) {
            throw servicioNoDisponible();
        }
        var previa = transicion.previa().orElseThrow(ServicioConfirmacionRfid1::capturaNoVigente);
        return new VistaPrevia(previa.uidCanonico(), previa.previsualizadaEn(), previa.confirmacionVenceEn());
    }

    /**
     * Confirma la asociación de la tarjeta o devuelve el resultado anterior si se repite la misma
     * solicitud. Antes de asociar, vuelve a validar la membresía del cliente.
     */
    public Confirmacion confirmar(
            String capturaId, String huellaSesion, String claveIdempotencia, PrincipalPropietario propietario) {
        exigirContexto(capturaId, huellaSesion, propietario);
        long revisionPropietarioCaptura = RevisionCapturaRfid1.persistida(propietario);
        if (claveIdempotencia == null || claveIdempotencia.strip().length() < 16
                || claveIdempotencia.length() > 200
                || claveIdempotencia.codePoints().anyMatch(Character::isISOControl)) {
            throw error(HttpStatus.BAD_REQUEST, "CLAVE_IDEMPOTENCIA_NO_VALIDA",
                    "No pudimos confirmar la tarjeta. Actualiza la captura e inténtalo de nuevo.");
        }

        TransicionConfirmacion transicion;
        try {
            transicion = transaccion.execute(estado -> {
                Instant ahora = reloj.instant();
                boolean huboExpiraciones = repositorio.expirarCapturasVencidas(ahora) > 0;
                ResultadoConfirmacionRfid1 resultado = repositorio.confirmarCaptura(
                        capturaId, propietario.cuentaId(), propietario.revisionAcceso(),
                        revisionPropietarioCaptura, huellaSesion,
                        ClavesRfid1.hashClave(claveIdempotencia), ahora);
                if (resultado == null) {
                    return new TransicionConfirmacion(null, huboExpiraciones);
                }
                boolean capturaInvalidada = "CANCELADA".equals(resultado.estado())
                        && ("CAPTURA_NO_VIGENTE".equals(resultado.codigoError())
                                || "CLIENTE_SIN_MEMBRESIA".equals(resultado.codigoError()))
                        && !resultado.repetida();
                boolean cambioCaptura = capturaInvalidada
                        || ("COMPLETADA".equals(resultado.estado()) && !resultado.repetida())
                        || "ESCANEANDO".equals(resultado.estado());
                return new TransicionConfirmacion(resultado, huboExpiraciones || cambioCaptura);
            });
        } catch (DataAccessException excepcion) {
            throw servicioNoDisponible();
        }
        if (transicion == null) {
            throw servicioNoDisponible();
        }
        publicadorCapturas.publicarSiActualizada(transicion.huboCambio());
        if (transicion.resultado() == null) {
            throw servicioNoDisponible();
        }

        ResultadoConfirmacionRfid1 resultado = transicion.resultado();
        boolean confirmada = "COMPLETADA".equals(resultado.estado()) && resultado.asociacionId() != null;
        publicadorTarjetas.publicarSiActualizadas(confirmada && !resultado.repetida());
        if (resultado.codigoError() != null) {
            throw errorConfirmacion(resultado.codigoError());
        }
        if (!confirmada) {
            throw servicioNoDisponible();
        }
        return new Confirmacion(capturaId, resultado.asociacionId(), resultado.estado(), "ASOCIADA");
    }

    private static void exigirContexto(String capturaId, String huellaSesion, PrincipalPropietario propietario) {
        if (propietario == null) {
            throw error(HttpStatus.UNAUTHORIZED, "SESION_NO_VIGENTE", "Inicia sesión para continuar.");
        }
        if (propietario.rol() != RolCuenta.DUENO && propietario.rol() != RolCuenta.OPERADOR) {
            throw error(HttpStatus.FORBIDDEN, "PERMISO_INSUFICIENTE", "No tienes acceso para hacer este cambio.");
        }
        if (capturaId == null || !FORMATO_CAPTURA.matcher(capturaId).matches()
                || huellaSesion == null || !FORMATO_HUELLA.matcher(huellaSesion).matches()) {
            throw capturaNoEncontrada();
        }
    }

    private static RuntimeException errorConfirmacion(String codigo) {
        return switch (codigo) {
            case "CAPTURA_NO_ENCONTRADA" -> capturaNoEncontrada();
            case "CAPTURA_NO_VIGENTE" -> capturaNoVigente();
            case "TARJETA_YA_REGISTRADA" -> error(HttpStatus.CONFLICT, codigo,
                    "La tarjeta ya está registrada. Inténtalo con otra tarjeta.");
            case "PERSONA_CON_TARJETA" -> error(HttpStatus.CONFLICT, codigo,
                    "La persona ya tiene una tarjeta activa.");
            case "CLIENTE_SIN_MEMBRESIA" -> error(HttpStatus.CONFLICT, codigo,
                    "No se puede asociar una tarjeta a un cliente sin membresía.");
            case "CLAVE_IDEMPOTENCIA_EN_CONFLICTO" -> error(HttpStatus.CONFLICT, codigo,
                    "La clave de confirmación ya se usó para otra solicitud.");
            default -> servicioNoDisponible();
        };
    }

    private static ErrorConfiguracion capturaNoEncontrada() {
        return error(HttpStatus.NOT_FOUND, "CAPTURA_NO_ENCONTRADA", "No encontramos la captura.");
    }

    private static ErrorConfiguracion capturaNoVigente() {
        return error(HttpStatus.CONFLICT, "CAPTURA_NO_VIGENTE", "La captura ya no está vigente.");
    }

    private static ErrorConfiguracion servicioNoDisponible() {
        return error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                "No pudimos confirmar la captura. Inténtalo más tarde.");
    }

    private static ErrorConfiguracion error(HttpStatus estado, String codigo, String mensaje) {
        return new ErrorConfiguracion(estado, mensaje, codigo);
    }

    private record TransicionVistaPrevia(
            Optional<RepositorioRfid1.VistaPreviaRfid1Persistida> previa, boolean huboExpiraciones) {
    }

    private record TransicionConfirmacion(ResultadoConfirmacionRfid1 resultado, boolean huboCambio) {
    }
}
