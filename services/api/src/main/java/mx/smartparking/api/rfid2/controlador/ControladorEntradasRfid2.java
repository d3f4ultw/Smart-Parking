package mx.smartparking.api.rfid2.controlador;

import mx.smartparking.api.rfid2.persistencia.ResultadoEntradaRfid2;
import mx.smartparking.api.rfid2.servicio.ServicioRfid2;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Recibe la lectura de entrada y devuelve si el vehículo tiene permiso para pasar. */
@RestController
@RequestMapping("/api/v1/dispositivos/rfid-2/entradas")
public final class ControladorEntradasRfid2 {

    private final ServicioRfid2 servicio;

    public ControladorEntradasRfid2(ServicioRfid2 servicio) {
        this.servicio = servicio;
    }

    /** Confirma que puede abrirse la entrada solo después de guardar el registro del vehículo. */
    @PostMapping
    public ResponseEntity<ResultadoEntradaRfid2> registrar(@RequestBody(required = false) SolicitudEntrada solicitud) {
        ResultadoEntradaRfid2 resultado = servicio.registrarEntrada(
                solicitud == null ? null : solicitud.uid(), solicitud == null ? null : solicitud.lecturaId());
        return ResponseEntity.ok().headers(encabezadosPrivados()).body(resultado);
    }

    private static HttpHeaders encabezadosPrivados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.set(HttpHeaders.CACHE_CONTROL, "no-store, private");
        encabezados.set(HttpHeaders.VARY, HttpHeaders.AUTHORIZATION);
        return encabezados;
    }

    public record SolicitudEntrada(String uid, String lecturaId) { }
}
