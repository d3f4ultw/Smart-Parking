package mx.smartparking.api.historial.controlador;

import mx.smartparking.api.historial.servicio.ServicioHistorialAccesos;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Permite al personal autorizado consultar las entradas y salidas registradas por los lectores. */
@RestController
@RequestMapping("/api/v1/accesos/historial")
public final class ControladorHistorialAccesos {

    private final ServicioHistorialAccesos servicio;

    public ControladorHistorialAccesos(ServicioHistorialAccesos servicio) {
        this.servicio = servicio;
    }

    /** Muestra hasta diez registros y permite reconocer si el historial cambia después de la consulta. */
    @GetMapping
    public ResponseEntity<RespuestaHistorialAccesos> consultar(
            @RequestParam(name = "pagina", defaultValue = "1") String pagina,
            @RequestParam(name = "lector", defaultValue = "TODOS") String lector,
            @RequestParam(name = "resultado", defaultValue = "TODOS") String resultado,
            @RequestParam(name = "periodo", defaultValue = "ULTIMOS_7_DIAS") String periodo,
            @RequestParam(name = "desde", required = false) String desde,
            @RequestParam(name = "hasta", required = false) String hasta) {
        return ResponseEntity.ok().headers(encabezadosPrivados())
                .body(servicio.consultar(pagina, lector, resultado, periodo, desde, hasta));
    }

    private static HttpHeaders encabezadosPrivados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.set(HttpHeaders.CACHE_CONTROL, "no-store, private");
        encabezados.set(HttpHeaders.VARY, HttpHeaders.COOKIE);
        return encabezados;
    }
}
