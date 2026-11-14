package mx.smartparking.api.rfid1.controlador;

import java.time.Instant;
import java.util.Optional;
import mx.smartparking.api.configuracion.ErrorConfiguracionControlador.RespuestaError;
import mx.smartparking.api.rfid1.modelo.CapturaRfid1;
import mx.smartparking.api.rfid1.servicio.ServicioRfid1;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Permite al equipo que comunica el lector con el servidor consultar y actualizar la lectura autorizada. */
@RestController
@RequestMapping("/api/v1/dispositivos/rfid-1/capturas")
public final class ControladorDispositivoRfid1 {

    private final ServicioRfid1 servicio;

    public ControladorDispositivoRfid1(ServicioRfid1 servicio) {
        this.servicio = servicio;
    }

    /** Indica al dispositivo si hay una lectura pendiente o si debe esperar sin buscar tarjetas. */
    @GetMapping("/activa")
    public ResponseEntity<RespuestaCaptura> consultarActiva() {
        Optional<CapturaRfid1> captura = servicio.consultarCapturaActivaDispositivo();
        if (captura.isEmpty()) {
            return ResponseEntity.noContent().headers(encabezadosPrivados()).build();
        }
        CapturaRfid1 estado = captura.get();
        return ResponseEntity.ok().headers(encabezadosPrivados())
                .body(new RespuestaCaptura(estado.capturaId(), estado.estado(), estado.expiraEn()));
    }

    /** Registra que el dispositivo comenzó a buscar la tarjeta solicitada. */
    @PostMapping("/{capturaId}/estado")
    public ResponseEntity<?> informarEstado(
            @PathVariable String capturaId,
            @RequestBody(required = false) SolicitudEstado solicitud) {
        if (solicitud == null || !"ESCANEANDO".equals(solicitud.estado())) {
            return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                    .headers(encabezadosPrivados())
                    .body(new RespuestaError("ESTADO_NO_VALIDO", "El estado enviado no es válido."));
        }
        servicio.informarEscaneando(capturaId);
        return ResponseEntity.noContent().headers(encabezadosPrivados()).build();
    }

    private static HttpHeaders encabezadosPrivados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.set(HttpHeaders.CACHE_CONTROL, "no-store, private");
        encabezados.set(HttpHeaders.VARY, HttpHeaders.AUTHORIZATION);
        return encabezados;
    }

    public record SolicitudEstado(String estado) {
    }

    public record RespuestaCaptura(String capturaId, String estado, Instant expiraEn) {
    }
}
