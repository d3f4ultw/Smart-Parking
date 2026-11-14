package mx.smartparking.api.configuracion;

import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.TransactionException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** Prepara avisos comprensibles cuando falla una operación o no se pueden consultar los datos guardados. */
@RestControllerAdvice(basePackages = "mx.smartparking.api")
public class ErrorConfiguracionControlador {

    @ExceptionHandler(ErrorConfiguracion.class)
    public ResponseEntity<RespuestaError> errorConfiguracion(ErrorConfiguracion excepcion) {
        return ResponseEntity.status(excepcion.estadoHttp())
                .body(new RespuestaError(
                        excepcion.codigo() == null ? "OPERACION_NO_COMPLETADA" : excepcion.codigo(),
                        excepcion.getMessage()));
    }

    @ExceptionHandler(DataAccessException.class)
    public ResponseEntity<RespuestaError> errorPersistencia(DataAccessException excepcion) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .body(new RespuestaError("SERVICIO_NO_DISPONIBLE",
                        "No pudimos completar esto ahora. Inténtalo más tarde."));
    }

    @ExceptionHandler(TransactionException.class)
    public ResponseEntity<RespuestaError> errorTransaccion(TransactionException excepcion) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .body(new RespuestaError("SERVICIO_NO_DISPONIBLE",
                        "No pudimos completar esto ahora. Inténtalo más tarde."));
    }

    public record RespuestaError(String codigo, String mensaje) {
    }
}
