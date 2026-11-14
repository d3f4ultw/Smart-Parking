package mx.smartparking.api.accesos;

import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.ErrorConfiguracionControlador.RespuestaError;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.TransactionException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Permite consultar cuántos lugares hay disponibles y qué visitas siguen dentro del estacionamiento. */
@RestController
@RequestMapping("/api/v1/accesos")
public final class ControladorAccesos {
    private final ServicioAccesos servicio;

    public ControladorAccesos(ServicioAccesos servicio) {
        this.servicio = servicio;
    }

    @GetMapping("/capacidad")
    public ResponseEntity<ServicioAccesos.RespuestaCapacidad> capacidad() {
        return ResponseEntity.ok().headers(encabezados()).body(servicio.capacidad());
    }

    @GetMapping("/dentro")
    public ResponseEntity<ServicioAccesos.RespuestaDentro> dentro(
            @RequestParam(name = "pagina", defaultValue = "1") St ring pagina,
            @RequestParam(name = "busqueda", required = false) String busqueda) {
        return ResponseEntity.ok().headers(encabezados()).body(servicio.dentro(pagina, busqueda));
    }

    @ExceptionHandler(ErrorConfiguracion.class)
    public ResponseEntity<RespuestaError> errorConfiguracion(ErrorConfiguracion error) {
        return ResponseEntity.status(error.estadoHttp()).headers(encabezados())
                .body(new RespuestaError(error.codigo(), error.getMessage()));
    }

    @ExceptionHandler({DataAccessException.class, TransactionException.class})
    public ResponseEntity<RespuestaError> errorPersistencia(RuntimeException error) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).headers(encabezados())
                .body(new RespuestaError("SERVICIO_NO_DISPONIBLE", "No pudimos cargar los accesos."));
    }

    private static HttpHeaders encabezados() {
        HttpHeaders headers = new HttpHeaders();
        headers.set(HttpHeaders.CACHE_CONTROL, "no-store, private");
        headers.set(HttpHeaders.VARY, HttpHeaders.COOKIE);
        return headers;
    }
}

