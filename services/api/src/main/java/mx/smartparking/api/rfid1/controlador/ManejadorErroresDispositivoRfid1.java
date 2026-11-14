package mx.smartparking.api.rfid1.controlador;

import jakarta.servlet.http.HttpServletRequest;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.ErrorConfiguracionControlador.RespuestaError;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.dao.DataAccessException;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.TransactionException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * Prepara avisos de error para el dispositivo y evita que se guarden o se compartan entre accesos
 * distintos.
 */
@Order(Ordered.HIGHEST_PRECEDENCE)
@RestControllerAdvice(assignableTypes = {ControladorDispositivoRfid1.class, ControladorLecturasRfid1.class})
public final class ManejadorErroresDispositivoRfid1 {

    @ExceptionHandler(ErrorConfiguracion.class)
    public ResponseEntity<RespuestaError> errorConfiguracion(ErrorConfiguracion excepcion) {
        String codigo = excepcion.codigo() == null ? "OPERACION_NO_COMPLETADA" : excepcion.codigo();
        return ResponseEntity.status(excepcion.estadoHttp())
                .headers(encabezadosPrivados())
                .body(new RespuestaError(codigo, excepcion.getMessage()));
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<RespuestaError> jsonNoValido(HttpServletRequest solicitud) {
        boolean rutaLectura = solicitud.getRequestURI().endsWith("/dispositivos/rfid-1/lecturas");
        String codigo = rutaLectura ? "LECTURA_NO_VALIDA" : "ESTADO_NO_VALIDO";
        String mensaje = rutaLectura ? "La lectura no es válida." : "El estado enviado no es válido.";
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .headers(encabezadosPrivados())
                .body(new RespuestaError(codigo, mensaje));
    }

    @ExceptionHandler({DataAccessException.class, TransactionException.class})
    public ResponseEntity<RespuestaError> errorPersistencia(RuntimeException excepcion) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .headers(encabezadosPrivados())
                .body(new RespuestaError(
                        "SERVICIO_NO_DISPONIBLE", "No pudimos confirmar la captura. Inténtalo más tarde."));
    }

    private static HttpHeaders encabezadosPrivados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.set(HttpHeaders.CACHE_CONTROL, "no-store, private");
        encabezados.set(HttpHeaders.VARY, HttpHeaders.AUTHORIZATION);
        return encabezados;
    }
}
