package mx.smartparking.api.rfid3.controlador;

import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.ErrorConfiguracionControlador.RespuestaError;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.transaction.TransactionException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** Responde sin datos de tarjeta cuando una salida falla o es inválida. */
@Order(Ordered.HIGHEST_PRECEDENCE)
@RestControllerAdvice(assignableTypes = ControladorSalidasRfid3.class)
public final class ManejadorErroresDispositivoRfid3 {

    @ExceptionHandler(ErrorConfiguracion.class)
    public ResponseEntity<RespuestaError> errorConfiguracion(ErrorConfiguracion excepcion) {
        String codigo = excepcion.codigo() == null ? "OPERACION_NO_COMPLETADA" : excepcion.codigo();
        return ResponseEntity.status(excepcion.estadoHttp()).headers(encabezadosPrivados())
                .body(new RespuestaError(codigo, excepcion.getMessage()));
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<RespuestaError> jsonNoValido() {
        return ResponseEntity.badRequest().headers(encabezadosPrivados())
                .body(new RespuestaError("LECTURA_NO_VALIDA", "La lectura enviada no es válida."));
    }

    @ExceptionHandler({DataAccessException.class, TransactionException.class})
    public ResponseEntity<RespuestaError> errorPersistencia(RuntimeException excepcion) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).headers(encabezadosPrivados())
                .body(new RespuestaError(
                        "SERVICIO_NO_DISPONIBLE", "No pudimos confirmar la salida. Inténtalo más tarde."));
    }

    private static HttpHeaders encabezadosPrivados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.set(HttpHeaders.CACHE_CONTROL, "no-store, private");
        encabezados.set(HttpHeaders.VARY, HttpHeaders.AUTHORIZATION);
        return encabezados;
    }
}
