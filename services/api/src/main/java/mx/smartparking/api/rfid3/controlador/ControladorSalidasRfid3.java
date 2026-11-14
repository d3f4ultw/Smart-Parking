package mx.smartparking.api.rfid3.controlador;

import java.util.Map;
import java.util.Set;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.rfid3.persistencia.ResultadoSalidaRfid3;
import mx.smartparking.api.rfid3.servicio.ServicioRfid3;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Recibe la lectura de salida y devuelve si el vehículo tiene permiso para salir. */
@RestController
@RequestMapping("/api/v1/dispositivos/rfid-3/salidas")
public final class ControladorSalidasRfid3 {

    private static final Set<String> MOTIVOS = Set.of(
            "TARJETA_DESCONOCIDA", "TARJETA_CANCELADA", "SIN_ENTRADA_ABIERTA", "SALIDA_MANUAL_EN_CURSO");
    private final ServicioRfid3 servicio;

    public ControladorSalidasRfid3(ServicioRfid3 servicio) {
        this.servicio = servicio;
    }

    /** Confirma que puede abrirse la salida después de guardar el cierre de la visita. */
    @PostMapping
    public ResponseEntity<Map<String, String>> registrar(@RequestBody(required = false) SolicitudSalida solicitud) {
        ResultadoSalidaRfid3 resultado = servicio.registrarSalida(
                solicitud == null ? null : texto(solicitud.uid()),
                solicitud == null ? null : texto(solicitud.lecturaId()));
        return ResponseEntity.ok().headers(encabezadosPrivados()).body(respuesta(resultado));
    }

    private static String texto(Object valor) {
        return valor instanceof String texto ? texto : null;
    }

    private static Map<String, String> respuesta(ResultadoSalidaRfid3 resultado) {
        if (resultado != null && "AUTORIZADA".equals(resultado.resultado()) && resultado.motivo() == null) {
            return Map.of("resultado", "AUTORIZADA");
        }
        if (resultado != null && "DENEGADA".equals(resultado.resultado())
                && resultado.motivo() != null && MOTIVOS.contains(resultado.motivo())) {
            return Map.of("resultado", "DENEGADA", "motivo", resultado.motivo());
        }
        throw new ErrorConfiguracion(HttpStatus.SERVICE_UNAVAILABLE,
                "No pudimos confirmar la salida. Inténtalo más tarde.", "SERVICIO_NO_DISPONIBLE");
    }

    private static HttpHeaders encabezadosPrivados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.set(HttpHeaders.CACHE_CONTROL, "no-store, private");
        encabezados.set(HttpHeaders.VARY, HttpHeaders.AUTHORIZATION);
        return encabezados;
    }

    public record SolicitudSalida(Object uid, Object lecturaId) { }
}
