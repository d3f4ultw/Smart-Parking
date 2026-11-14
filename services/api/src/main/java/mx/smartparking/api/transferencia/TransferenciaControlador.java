package mx.smartparking.api.transferencia;

import jakarta.servlet.http.HttpServletRequest;
import mx.smartparking.api.configuracion.ConfiguracionServicio;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.ResultadoConfiguracion;
import mx.smartparking.api.configuracion.ResultadoTransferencia;
import mx.smartparking.api.configuracion.SolicitudConfiguracion;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Recibe las solicitudes para iniciar el cambio de propietario, recuperar el permiso o completar el
 * registro del nuevo.
 */
@RestController
@RequestMapping("/api/v1/transferencia")
public class TransferenciaControlador {

    private final ConfiguracionServicio servicio;

    public TransferenciaControlador(ConfiguracionServicio servicio) {
        this.servicio = servicio;
    }

    @PostMapping("/iniciar")
    public ResponseEntity<ResultadoTransferencia> iniciar(
            @RequestBody SolicitudTransferencia solicitud,
            @RequestHeader("If-Match") String ifMatch,
            @RequestHeader("Idempotency-Key") String claveIdempotencia,
            @AuthenticationPrincipal PrincipalPropietario propietario,
            HttpServletRequest solicitudHttp) {
        ResultadoTransferencia resultado = servicio.iniciarTransferencia(
                solicitud == null ? null : solicitud.contrasenaAdministrativa(),
                parsearEtag(ifMatch),
                propietario.revisionPropietario(),
                claveIdempotencia,
                solicitudHttp.getRemoteAddr());
        return ResponseEntity.ok()
                .header(HttpHeaders.ETAG, etag(servicio.consultarRevision()))
                .body(resultado);
    }

    @PostMapping("/recuperar")
    public ResponseEntity<ResultadoTransferencia> recuperar(
            @RequestBody SolicitudRecuperacion solicitud,
            HttpServletRequest solicitudHttp) {
        ResultadoTransferencia resultado = servicio.recuperarTransferencia(
                solicitud == null ? null : solicitud.contrasenaAdministrativa(),
                solicitudHttp.getRemoteAddr());
        return ResponseEntity.ok()
                .header(HttpHeaders.ETAG, etag(servicio.consultarRevision()))
                .body(resultado);
    }

    @PostMapping("/completar")
    public ResponseEntity<ResultadoConfiguracion> completar(
            @RequestHeader(value = "X-Transfer-Grant", required = false) String grant,
            @RequestHeader("Idempotency-Key") String claveIdempotencia,
            @RequestBody SolicitudConfiguracion solicitud,
            HttpServletRequest solicitudHttp) {
        ResultadoConfiguracion resultado = servicio.completarTransferencia(
                grant,
                solicitud,
                claveIdempotencia,
                solicitudHttp.getRemoteAddr());
        return ResponseEntity.ok()
                .header(HttpHeaders.ETAG, etag(resultado.revision()))
                .body(resultado);
    }

    private static long parsearEtag(String etag) {
        if (etag == null || etag.length() < 3 || etag.charAt(0) != '"' || etag.charAt(etag.length() - 1) != '"') {
            throw new ErrorConfiguracion(HttpStatus.BAD_REQUEST,
                    "La información cambió. Actualiza la pantalla e inténtalo de nuevo.");
        }
        try {
            return Long.parseLong(etag.substring(1, etag.length() - 1));
        } catch (NumberFormatException excepcion) {
            throw new ErrorConfiguracion(HttpStatus.BAD_REQUEST,
                    "La información cambió. Actualiza la pantalla e inténtalo de nuevo.");
        }
    }

    private static String etag(long revision) {
        return "\"" + revision + "\"";
    }
}
