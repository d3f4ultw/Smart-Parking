package mx.smartparking.api.eventos;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpSession;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * Mantiene informadas a las personas autorizadas cuando hay cambios que deben volver a consultar en el
 * panel.
 */
@RestController
@RequestMapping("/api/v1/eventos")
public final class ControladorEventosAdministracion {

    private final ServicioEventosAdministracion servicioEventos;

    public ControladorEventosAdministracion(ServicioEventosAdministracion servicioEventos) {
        this.servicioEventos = servicioEventos;
    }

    @GetMapping(path = "/administracion", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public ResponseEntity<SseEmitter> abrirStream(
            @RequestHeader(value = "Last-Event-ID", required = false) String ultimoEvento,
            @RequestParam(value = "despues", required = false) String cursorInicial,
            @AuthenticationPrincipal PrincipalPropietario propietario,
            HttpServletRequest solicitud) {
        HttpSession sesion = solicitud.getSession(false);
        String idSesion = sesion == null ? null : sesion.getId();
        String cursor = ultimoEvento == null ? cursorInicial : ultimoEvento;
        SseEmitter emisor = servicioEventos.abrirStream(idSesion, propietario, cursor);
        return ResponseEntity.ok()
                .header(HttpHeaders.CACHE_CONTROL, "no-store, private")
                .header(HttpHeaders.VARY, HttpHeaders.COOKIE)
                .header("X-Accel-Buffering", "no")
                .contentType(MediaType.TEXT_EVENT_STREAM)
                .body(emisor);
    }

    /**
     * Confirma que una pantalla sigue recibiendo avisos sin cambiar el orden de las actualizaciones
     * del directorio.
     */
    @PostMapping(path = "/administracion/heartbeat", consumes = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Void> confirmarHeartbeat(
            @RequestBody SolicitudConfirmacionHeartbeat solicitud,
            @AuthenticationPrincipal PrincipalPropietario propietario,
            HttpServletRequest peticion) {
        HttpSession sesion = peticion.getSession(false);
        if (sesion != null) {
            servicioEventos.confirmarHeartbeat(
                    sesion.getId(), propietario, solicitud.suscripcionId(), solicitud.secuencia());
        }
        return ResponseEntity.noContent().build();
    }

    /** Devuelve el estado del error si no es posible comenzar los avisos, sin enviar datos adicionales. */
    @ExceptionHandler(ErrorConfiguracion.class)
    public ResponseEntity<Void> errorConfiguracionStream(ErrorConfiguracion excepcion) {
        return ResponseEntity.status(excepcion.estadoHttp()).build();
    }

    public record SolicitudConfirmacionHeartbeat(String suscripcionId, long secuencia) {
    }
}
