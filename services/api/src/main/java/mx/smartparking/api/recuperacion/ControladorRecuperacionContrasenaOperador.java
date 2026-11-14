package mx.smartparking.api.recuperacion;

import java.util.UUID;
import mx.smartparking.api.activacion.RespuestaErrorActivacionOperador;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Permite al propietario pedir un enlace de recuperación y al operador elegir una contraseña nueva. */
@RestController
@RequestMapping("/api/v1/operadores")
public class ControladorRecuperacionContrasenaOperador {

    private final ServicioRecuperacionContrasenaOperador servicio;

    public ControladorRecuperacionContrasenaOperador(ServicioRecuperacionContrasenaOperador servicio) {
        this.servicio = servicio;
    }

    /** Pide el envío de un correo de recuperación sin mostrar el código del enlace en el panel. */
    @PostMapping("/{operadorId}/recuperacion")
    public ResponseEntity<RespuestaSolicitudRecuperacionOperador> solicitar(
            @PathVariable UUID operadorId,
            @RequestHeader(value = "If-Match", required = false) String ifMatch,
            @RequestHeader(value = "Idempotency-Key", required = false) String claveIdempotencia) {
        ResultadoSolicitudRecuperacionOperador resultado = servicio.solicitar(
                operadorId, ifMatch, claveIdempotencia);
        HttpHeaders encabezados = encabezadosPrivados();
        encabezados.setETag("\"" + resultado.revisionAcceso() + "\"");
        return ResponseEntity.ok().headers(encabezados).body(resultado.respuesta());
    }

    /**
     * Comprueba si el enlace de recuperación sigue vigente sin impedir que se use después ni mostrar
     * datos de la cuenta.
     */
    @PostMapping("/recuperacion/validar")
    public ResponseEntity<RespuestaValidacionRecuperacionOperador> validar(
            @RequestBody(required = false) SolicitudValidacionRecuperacionOperador solicitud) {
        RespuestaValidacionRecuperacionOperador respuesta = servicio.validar(
                solicitud == null ? null : solicitud.token());
        return ResponseEntity.ok().headers(encabezadosPrivados()).body(respuesta);
    }

    /** Guarda la contraseña nueva y deja de aceptar el enlace como una sola operación. */
    @PostMapping("/recuperacion/completar")
    public ResponseEntity<Void> completar(
            @RequestBody(required = false) SolicitudCompletarRecuperacionOperador solicitud) {
        servicio.completar(solicitud);
        return ResponseEntity.noContent().headers(encabezadosPrivados()).build();
    }

    @ExceptionHandler(ErrorConfiguracion.class)
    public ResponseEntity<RespuestaErrorActivacionOperador> errorNegocio(ErrorConfiguracion error) {
        HttpHeaders encabezados = encabezadosPrivados();
        if (error.estadoHttp() == HttpStatus.TOO_MANY_REQUESTS) {
            encabezados.set("Retry-After", "900");
        }
        return ResponseEntity.status(error.estadoHttp()).headers(encabezados)
                .body(new RespuestaErrorActivacionOperador(
                        error.codigo() == null ? "OPERACION_NO_COMPLETADA" : error.codigo(), error.getMessage()));
    }

    private static HttpHeaders encabezadosPrivados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.setCacheControl("no-store");
        encabezados.set("Referrer-Policy", "no-referrer");
        return encabezados;
    }
}
