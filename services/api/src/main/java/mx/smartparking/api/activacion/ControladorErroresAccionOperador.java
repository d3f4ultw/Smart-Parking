package mx.smartparking.api.activacion;

import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** Informa cuánto falta esperar cuando se alcanza el límite de invitaciones o de recuperación de contraseña. */
@RestControllerAdvice
public class ControladorErroresAccionOperador {

    @ExceptionHandler(ErrorLimitacionAccionOperador.class)
    public ResponseEntity<RespuestaErrorActivacionOperador> limite(ErrorLimitacionAccionOperador error) {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.setCacheControl("no-store");
        encabezados.set("Referrer-Policy", "no-referrer");
        encabezados.set("Retry-After", Long.toString(error.retryAfterSeconds()));
        return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS).headers(encabezados)
                .body(new RespuestaErrorActivacionOperador(error.codigo(), error.getMessage()));
    }
}
