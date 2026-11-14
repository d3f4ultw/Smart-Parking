package mx.smartparking.api.rfid1.controlador;

import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.ErrorConfiguracionControlador.RespuestaError;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.TransactionException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** Evita que el navegador guarde los errores de las consultas privadas de tarjetas. */
@RestControllerAdvice(assignableTypes = {ControladorCapturasRfid1.class, ControladorTarjetasRfid1.class})
@Order(Ordered.HIGHEST_PRECEDENCE)
public class ManejadorErroresPrivadosRfid1 {

    /** Devuelve los avisos previstos para una operación sin permitir que se guarden como contenido público. */
    @ExceptionHandler(ErrorConfiguracion.class)
    public ResponseEntity<RespuestaError> errorConfiguracion(ErrorConfiguracion excepcion) {
        String codigo = excepcion.codigo() == null ? "OPERACION_NO_COMPLETADA" : excepcion.codigo();
        return respuesta(excepcion.estadoHttp(), codigo, excepcion.getMessage());
    }

    /** Avisa que no fue posible consultar o guardar la información sin mostrar detalles de la base de datos. */
    @ExceptionHandler({DataAccessException.class, TransactionException.class})
    public ResponseEntity<RespuestaError> errorPersistencia(RuntimeException excepcion) {
        return respuesta(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                "No pudimos completar esto ahora. Inténtalo más tarde.");
    }

    /** Avisa de forma segura cuando se recibe un identificador que no tiene el formato esperado. */
    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ResponseEntity<RespuestaError> argumentoNoValido(MethodArgumentTypeMismatchException excepcion) {
        return respuesta(HttpStatus.BAD_REQUEST, "ASOCIACION_ID_NO_VALIDO", "La tarjeta indicada no es válida.");
    }

    private static ResponseEntity<RespuestaError> respuesta(HttpStatus estado, String codigo, String mensaje) {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.set(HttpHeaders.CACHE_CONTROL, "no-store, private");
        encabezados.set(HttpHeaders.VARY, HttpHeaders.COOKIE);
        return ResponseEntity.status(estado).headers(encabezados).body(new RespuestaError(codigo, mensaje));
    }
}
