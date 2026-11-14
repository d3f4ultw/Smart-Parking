package mx.smartparking.api.accesos;

import java.util.Map;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Recibe mensajes del equipo autorizado que comunica el servidor con el dispositivo de salida manual,
 * sin ofrecer una orden para abrir la barrera directamente.
 */
@RestController
@RequestMapping("/api/v1/dispositivos/rfid-3/salidas-manuales")
public class ControladorDispositivoSalidaManual {
    private final ServicioSalidaManual servicio;
    private final DetectorCapacidadSalidaManual detector;

    public ControladorDispositivoSalidaManual(ServicioSalidaManual servicio, DetectorCapacidadSalidaManual detector) {
        this.servicio = servicio;
        this.detector = detector;
    }

    @GetMapping("/capacidad/desafio")
    public ResponseEntity<Map<String, String>> desafioCapacidad() {
        String desafio = detector.crearDesafio();
        return desafio == null ? ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).headers(encabezados()).build()
                : ResponseEntity.ok().headers(encabezados()).body(Map.of("desafioId", desafio));
    }

    @PostMapping("/capacidad")
    public ResponseEntity<Void> confirmarCapacidad(@RequestBody(required = false) PruebaCapacidad prueba) {
        if (prueba != null && Boolean.FALSE.equals(prueba.conectado())) {
            detector.invalidar();
            return ResponseEntity.noContent().headers(encabezados()).build();
        }
        boolean valida = prueba != null && prueba.conectado() == null
                && detector.confirmar(prueba.desafioId(), prueba.bootId(), prueba.firma());
        if (!valida) {
            detector.invalidar();
        }
        return ResponseEntity.status(valida ? HttpStatus.NO_CONTENT : HttpStatus.CONFLICT).headers(encabezados())
                .build();
    }

    @GetMapping("/pendiente")
    public ResponseEntity<ServicioSalidaManual.TrabajoDispositivo> pendiente(
            @RequestParam(value = "despues", required = false) String despues) {
        var trabajo = servicio.pendiente(despues);
        return trabajo == null ? ResponseEntity.noContent().headers(encabezados()).build()
                : ResponseEntity.ok().headers(encabezados()).body(trabajo);
    }

    @PostMapping("/{operacionId}/emitir")
    public ResponseEntity<Map<String, Object>> emitir(@PathVariable String operacionId,
            @RequestBody(required = false) SolicitudEmision solicitud) {
        String firma = servicio.emitir(operacionId, solicitud == null ? null : solicitud.bootId(),
                solicitud == null ? null : solicitud.ticketId());
        return firma != null ? ResponseEntity.ok().headers(encabezados()).body(Map.of("autorizada", true, "firma", firma))
                : ResponseEntity.status(HttpStatus.CONFLICT).headers(encabezados()).body(Map.of("autorizada", false));
    }

    @PostMapping("/{operacionId}/resultado")
    public ResponseEntity<ServicioSalidaManual.Respuesta> resultado(@PathVariable String operacionId,
            @RequestBody(required = false) SolicitudResultado solicitud) {
        return ResponseEntity.ok().headers(encabezados()).body(servicio.resultado(operacionId,
                solicitud == null ? null : solicitud.bootId(), solicitud == null ? null : solicitud.ticketId(),
                solicitud == null ? null : solicitud.resultado(), solicitud == null ? null : solicitud.firma()));
    }

    private static HttpHeaders encabezados() {
        HttpHeaders headers = new HttpHeaders();
        headers.set(HttpHeaders.CACHE_CONTROL, "no-store, private");
        headers.set(HttpHeaders.VARY, HttpHeaders.AUTHORIZATION);
        return headers;
    }

    public record SolicitudEmision(String bootId, String ticketId) { }
    public record SolicitudResultado(String bootId, String ticketId, String resultado, String firma) { }
    public record PruebaCapacidad(Boolean conectado, String desafioId, String bootId, String firma) { }
}
