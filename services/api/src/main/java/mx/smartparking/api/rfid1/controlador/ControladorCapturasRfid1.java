package mx.smartparking.api.rfid1.controlador;

import java.time.Instant;
import java.util.Optional;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpSession;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.Confirmacion;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.VistaPrevia;
import mx.smartparking.api.rfid1.modelo.CapturaRfid1;
import mx.smartparking.api.rfid1.servicio.ServicioConfirmacionRfid1;
import mx.smartparking.api.rfid1.servicio.ServicioRfid1;
import mx.smartparking.api.seguridad.HuellaSesionPropietario;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Permite a las cuentas autorizadas iniciar, consultar o cancelar la lectura de una tarjeta para
 * asociarla a una persona.
 */
@RestController
@RequestMapping("/api/v1/rfid-1/capturas")
public final class ControladorCapturasRfid1 {

    private final ServicioRfid1 servicio;
    private final ServicioConfirmacionRfid1 servicioConfirmacion;

    public ControladorCapturasRfid1(ServicioRfid1 servicio, ServicioConfirmacionRfid1 servicioConfirmacion) {
        this.servicio = servicio;
        this.servicioConfirmacion = servicioConfirmacion;
    }

    /**
     * Inicia la lectura de una tarjeta para la persona elegida y evita duplicarla si se repite la
     * solicitud.
     */
    @PostMapping
    public ResponseEntity<RespuestaCreacion> crear(
            @RequestBody(required = false) SolicitudCreacion solicitud,
            @RequestHeader(value = "Idempotency-Key", required = false) String claveIdempotencia,
            HttpServletRequest solicitudHttp,
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        CapturaRfid1 captura = servicio.crearCaptura(
                solicitud == null ? null : solicitud.tipoEntidad(),
                solicitud == null ? null : solicitud.codigoPersona(),
                claveIdempotencia,
                huellaSesion(solicitudHttp),
                propietario);
        return ResponseEntity.status(HttpStatus.CREATED)
                .headers(encabezadosPrivados())
                .body(new RespuestaCreacion(captura.capturaId(), captura.estado(), captura.expiraEn()));
    }

    /** Recupera la lectura que sigue pendiente para que la persona pueda continuar donde se quedó. */
    @GetMapping("/activa")
    public ResponseEntity<?> consultarActiva(
            HttpServletRequest solicitudHttp, @AuthenticationPrincipal PrincipalPropietario propietario) {
        Optional<CapturaRfid1> captura = servicio.consultarCapturaActiva(huellaSesion(solicitudHttp), propietario);
        if (captura.isEmpty()) {
            return ResponseEntity.noContent().headers(encabezadosPrivados()).build();
        }
        return ResponseEntity.ok().headers(encabezadosPrivados()).body(captura.get());
    }

    /**
     * Muestra el avance y resultado de la lectura sin revelar el número de tarjeta ni el identificador
     * interno de la persona.
     */
    @GetMapping("/{capturaId}")
    public ResponseEntity<CapturaRfid1> consultar(
            @PathVariable String capturaId,
            HttpServletRequest solicitudHttp,
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        return ResponseEntity.ok().headers(encabezadosPrivados())
                .body(servicio.consultarCaptura(capturaId, huellaSesion(solicitudHttp), propietario));
    }

    /** Muestra el número de la tarjeta solo a la cuenta que inició la lectura y mantiene la misma sesión. */
    @GetMapping("/{capturaId}/vista-previa")
    public ResponseEntity<VistaPrevia> consultarVistaPrevia(
            @PathVariable String capturaId,
            HttpServletRequest solicitudHttp,
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        VistaPrevia vista = servicioConfirmacion.consultarVistaPrevia(
                capturaId, huellaSesion(solicitudHttp), propietario);
        return ResponseEntity.ok().headers(encabezadosPrivados()).body(vista);
    }

    /**
     * Confirma que la tarjeta mostrada debe asociarse a la persona elegida y reconoce las solicitudes
     * repetidas.
     */
    @PostMapping("/{capturaId}/confirmacion")
    public ResponseEntity<Confirmacion> confirmar(
            @PathVariable String capturaId,
            @RequestHeader(value = "Idempotency-Key", required = false) String claveIdempotencia,
            HttpServletRequest solicitudHttp,
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        Confirmacion confirmacion = servicioConfirmacion.confirmar(
                capturaId, huellaSesion(solicitudHttp), claveIdempotencia, propietario);
        return ResponseEntity.ok().headers(encabezadosPrivados()).body(confirmacion);
    }

    /** Cancela una lectura pendiente y conserva el mismo resultado si se repite la solicitud. */
    @DeleteMapping("/{capturaId}")
    public ResponseEntity<Void> cancelar(
            @PathVariable String capturaId,
            HttpServletRequest solicitudHttp,
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        servicio.cancelarCaptura(capturaId, huellaSesion(solicitudHttp), propietario);
        return ResponseEntity.noContent().headers(encabezadosPrivados()).build();
    }

    private static String huellaSesion(HttpServletRequest solicitud) {
        HttpSession sesion = solicitud.getSession(false);
        if (sesion == null) {
            throw new ErrorConfiguracion(HttpStatus.UNAUTHORIZED, "Inicia sesión para continuar.",
                    "SESION_NO_VIGENTE");
        }
        return HuellaSesionPropietario.calcular(sesion.getId());
    }

    private static HttpHeaders encabezadosPrivados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.set(HttpHeaders.CACHE_CONTROL, "no-store, private");
        encabezados.set(HttpHeaders.VARY, HttpHeaders.COOKIE);
        return encabezados;
    }

    public record SolicitudCreacion(String tipoEntidad, String codigoPersona) {
    }

    public record RespuestaCreacion(String capturaId, String estado, Instant expiraEn) {
    }
}
