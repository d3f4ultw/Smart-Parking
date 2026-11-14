package mx.smartparking.api.vision;

import java.util.List;
import java.util.UUID;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import mx.smartparking.api.vision.ContratosVision.*;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.TransactionException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

/** Recibe las solicitudes de la cámara y las consultas de ocupación del personal autorizado. */
@RestController
public final class ControladorVision {
    private final ServicioVision servicio;
    private final ServicioEventosAdministracion eventos;

    public ControladorVision(ServicioVision servicio, ServicioEventosAdministracion eventos) {
        this.servicio = servicio;
        this.eventos = eventos;
    }

    @PostMapping("/api/v1/vision/fuentes")
    public ResponseEntity<RespuestaFuente> registrar(@RequestBody JsonNode cuerpo) {
        return respuesta(servicio.registrarFuente(ParseadorVision.fuente(cuerpo)));
    }

    @PutMapping("/api/v1/vision/fuentes/{fuenteId}/calibracion")
    public ResponseEntity<Void> activar(@PathVariable UUID fuenteId, @RequestBody JsonNode cuerpo,
            @AuthenticationPrincipal UUID fuenteAutorizada) {
        comprobarFuente(fuenteAutorizada, fuenteId);
        servicio.activarCalibracion(fuenteId, ParseadorVision.calibracion(cuerpo));
        return ResponseEntity.noContent().headers(encabezados()).build();
    }

    @GetMapping("/api/v1/vision/fuentes/{fuenteId}/calibracion")
    public ResponseEntity<RespuestaCalibracion> calibracion(@PathVariable UUID fuenteId,
            @AuthenticationPrincipal UUID fuenteAutorizada) {
        comprobarFuente(fuenteAutorizada, fuenteId);
        return respuesta(servicio.consultarCalibracion(fuenteId));
    }

    @GetMapping("/api/v1/vision/cajones")
    public ResponseEntity<List<EstadoCajon>> cajones() {
        String cursor = eventos.cursorActual();
        ServicioVision.LecturaCajones lectura = servicio.consultarCajonesConVigencia();
        HttpHeaders headers = encabezados();
        headers.set("X-Eventos-Cursor", cursor);
        if (lectura.vigenciaRestanteMs() != null) {
            headers.set("X-Vision-Vigencia-Restante-Ms", lectura.vigenciaRestanteMs().toString());
        }
        return ResponseEntity.ok().headers(headers).body(lectura.cajones());
    }

    @PutMapping("/api/v1/vision/cajones/{cajonId}/display-name")
    public ResponseEntity<Void> actualizarNombreCajon(@PathVariable UUID cajonId,
            @RequestBody(required = false) SolicitudNombreCajon solicitud) {
        servicio.actualizarNombreCajon(cajonId, solicitud == null ? null : solicitud.displayName());
        return ResponseEntity.noContent().headers(encabezados()).build();
    }

    @PostMapping("/api/v1/dispositivos/vision/sesiones")
    public ResponseEntity<RespuestaSesion> sesion(@RequestBody JsonNode cuerpo,
            @AuthenticationPrincipal UUID fuenteAutorizada) {
        SolicitudSesion solicitud = ParseadorVision.sesion(cuerpo);
        comprobarFuente(fuenteAutorizada, solicitud.fuenteId());
        return respuesta(servicio.abrirSesion(solicitud));
    }

    @PostMapping("/api/v1/dispositivos/vision/observaciones")
    public ResponseEntity<RespuestaObservacion> observacion(@RequestBody JsonNode cuerpo,
            @AuthenticationPrincipal UUID fuenteAutorizada) {
        SolicitudObservacion solicitud = ParseadorVision.observacion(cuerpo);
        comprobarFuente(fuenteAutorizada, solicitud.fuenteId());
        return respuesta(servicio.observar(solicitud));
    }

    @ExceptionHandler(ErrorConfiguracion.class)
    public ResponseEntity<ErrorVision> errorConfiguracion(ErrorConfiguracion error) {
        return ResponseEntity.status(error.estadoHttp()).headers(encabezados())
                .body(new ErrorVision(error.codigo(), error.getMessage()));
    }

    @ExceptionHandler({DataAccessException.class, TransactionException.class})
    public ResponseEntity<ErrorVision> errorPersistencia(RuntimeException error) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).headers(encabezados())
                .body(new ErrorVision("VISION_NO_DISPONIBLE", "No se pudo completar la operación."));
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<ErrorVision> jsonInvalido() {
        return ResponseEntity.badRequest().headers(encabezados())
                .body(new ErrorVision("VISION_INVALIDA", "La solicitud de Vision no es válida."));
    }

    private static void comprobarFuente(UUID autorizada, UUID recibida) {
        if (autorizada == null || !autorizada.equals(recibida)) {
            throw new ErrorConfiguracion(HttpStatus.FORBIDDEN,
                    "La credencial no corresponde a esta fuente.", "VISION_NO_AUTORIZADA");
        }
    }

    private static <T> ResponseEntity<T> respuesta(T cuerpo) {
        return ResponseEntity.ok().headers(encabezados()).body(cuerpo);
    }

    private static HttpHeaders encabezados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.setCacheControl("no-store, private");
        return encabezados;
    }

    public record ErrorVision(String codigo, String mensaje) { }
}
