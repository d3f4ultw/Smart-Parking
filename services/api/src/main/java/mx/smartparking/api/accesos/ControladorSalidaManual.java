package mx.smartparking.api.accesos;

import jakarta.servlet.http.HttpServletRequest;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Permite al personal autorizado solicitar y consultar una salida manual cuando hace falta. */
@RestController
@RequestMapping("/api/v1/accesos")
public class ControladorSalidaManual {
    private final ServicioSalidaManual servicio;
    private final DetectorCapacidadSalidaManual detector;

    public ControladorSalidaManual(ServicioSalidaManual servicio, DetectorCapacidadSalidaManual detector) {
        this.servicio = servicio;
        this.detector = detector;
    }

    @GetMapping("/salidas-manuales/capacidad")
    public ResponseEntity<DetectorCapacidadSalidaManual.Disponibilidad> capacidad() {
        return ResponseEntity.ok().headers(encabezados()).body(detector.disponibilidad());
    }

    @PostMapping("/movimientos/{movimientoId}/salida-manual")
    public ResponseEntity<ServicioSalidaManual.Respuesta> solicitar(@PathVariable String movimientoId,
            @RequestHeader(value = "Idempotency-Key", required = false) String clave,
            @AuthenticationPrincipal PrincipalPropietario principal, HttpServletRequest solicitud) {
        return ResponseEntity.accepted().headers(encabezados()).body(
                servicio.solicitar(movimientoId, clave, principal, solicitud.getSession(false)));
    }

    @GetMapping("/salidas-manuales/{operacionId}")
    public ResponseEntity<ServicioSalidaManual.Respuesta> consultar(@PathVariable String operacionId) {
        return ResponseEntity.ok().headers(encabezados()).body(servicio.consultar(operacionId));
    }

    private static HttpHeaders encabezados() {
        HttpHeaders headers = new HttpHeaders();
        headers.set(HttpHeaders.CACHE_CONTROL, "no-store, private");
        headers.set(HttpHeaders.VARY, HttpHeaders.COOKIE);
        return headers;
    }
}
