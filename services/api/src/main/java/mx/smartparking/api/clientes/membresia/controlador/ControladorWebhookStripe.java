package mx.smartparking.api.clientes.membresia.controlador;

import com.stripe.exception.SignatureVerificationException;
import mx.smartparking.api.clientes.membresia.servicio.ServicioWebhookStripe;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.ErrorConfiguracionControlador.RespuestaError;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Recibe los avisos de Stripe conservando su contenido original para poder comprobar que proceden de
 * Stripe.
 */
@RestController
@RequestMapping("/api/v1/webhooks/stripe")
public final class ControladorWebhookStripe {

    private final ServicioWebhookStripe servicio;

    public ControladorWebhookStripe(ServicioWebhookStripe servicio) {
        this.servicio = servicio;
    }

    @PostMapping(consumes = "application/json")
    public ResponseEntity<Void> recibir(
            @RequestBody byte[] cuerpoOriginal,
            @RequestHeader(name = "Stripe-Signature", required = false) String firma) throws SignatureVerificationException {
        servicio.procesar(cuerpoOriginal, firma);
        return ResponseEntity.noContent().headers(encabezadosPrivados()).build();
    }

    @ExceptionHandler(SignatureVerificationException.class)
    public ResponseEntity<RespuestaError> firmaInvalida(SignatureVerificationException excepcion) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).headers(encabezadosPrivados())
                .body(new RespuestaError("WEBHOOK_NO_VALIDO", "No pudimos validar el aviso de pago."));
    }

    @ExceptionHandler(ErrorConfiguracion.class)
    public ResponseEntity<RespuestaError> errorDeNegocio(ErrorConfiguracion excepcion) {
        return ResponseEntity.status(excepcion.estadoHttp()).headers(encabezadosPrivados())
                .body(new RespuestaError(excepcion.codigo() == null ? "OPERACION_NO_COMPLETADA" : excepcion.codigo(),
                        excepcion.getMessage()));
    }

    private static HttpHeaders encabezadosPrivados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.setCacheControl("no-store, private");
        encabezados.setVary(java.util.List.of(HttpHeaders.COOKIE));
        return encabezados;
    }
}
