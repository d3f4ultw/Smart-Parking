package mx.smartparking.api.rfid1.controlador;

import mx.smartparking.api.configuracion.ErrorConfiguracionControlador.RespuestaError;
import mx.smartparking.api.rfid1.servicio.ServicioEstadoConexionRfid1;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Recibe del equipo de comunicación si el dispositivo ESP32 respondió y sigue conectado. */
@RestController
@RequestMapping("/api/v1/dispositivos/rfid-1/estado")
public final class ControladorEstadoConexionDispositivoRfid1 {

    private final ServicioEstadoConexionRfid1 servicio;

    public ControladorEstadoConexionDispositivoRfid1(ServicioEstadoConexionRfid1 servicio) {
        this.servicio = servicio;
    }

    @PostMapping
    public ResponseEntity<?> registrar(@RequestBody(required = false) SolicitudEstado solicitud) {
        if (solicitud == null || solicitud.conectado() == null) {
            return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                    .headers(encabezadosPrivados())
                    .body(new RespuestaError("ESTADO_NO_VALIDO", "El estado no es válido."));
        }
        servicio.registrar(solicitud.conectado());
        return ResponseEntity.noContent().headers(encabezadosPrivados()).build();
    }

    private static HttpHeaders encabezadosPrivados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.set(HttpHeaders.CACHE_CONTROL, "no-store, private");
        encabezados.set(HttpHeaders.VARY, HttpHeaders.AUTHORIZATION);
        return encabezados;
    }

    public record SolicitudEstado(Boolean conectado) {
    }
}
