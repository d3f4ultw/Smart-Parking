package mx.smartparking.api.activacion;

import java.util.UUID;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.TransactionException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Permite activar una cuenta mediante su invitación y pedir otra invitación desde una cuenta autorizada. */
@RestController
@RequestMapping("/api/v1/operadores")
public class ControladorActivacionOperador {

    private final ServicioActivacionOperador servicio;
    private final ServicioAdministracionInvitacionesOperador administracionInvitaciones;

    public ControladorActivacionOperador(
            ServicioActivacionOperador servicio,
            ServicioAdministracionInvitacionesOperador administracionInvitaciones) {
        this.servicio = servicio;
        this.administracionInvitaciones = administracionInvitaciones;
    }

    /**
     * Comprueba si la invitación sigue vigente sin impedir que se use después ni mostrar datos de la
     * cuenta.
     */
    @PostMapping("/activacion/validar")
    public ResponseEntity<RespuestaValidacionActivacionOperador> validar(
            @RequestBody(required = false) SolicitudValidacionActivacionOperador solicitud) {
        RespuestaValidacionActivacionOperador respuesta = servicio.validar(
                solicitud == null ? null : solicitud.token());
        return ResponseEntity.ok().headers(encabezadosPrivados()).body(respuesta);
    }

    /** Guarda la contraseña y deja de aceptar la invitación en la misma operación. */
    @PostMapping("/activacion/completar")
    public ResponseEntity<Void> completar(
            @RequestBody(required = false) SolicitudCompletarActivacionOperador solicitud) {
        servicio.completar(solicitud);
        return ResponseEntity.noContent().headers(encabezadosPrivados()).build();
    }

    /** Sustituye la invitación anterior por un enlace nuevo y respeta el límite de solicitudes permitido. */
    @PostMapping("/{operadorId}/invitacion/reemitir")
    public ResponseEntity<RespuestaReemisionInvitacionOperador> reemitir(
            @PathVariable UUID operadorId,
            @RequestHeader(value = "If-Match", required = false) String ifMatch,
            @RequestHeader(value = "Idempotency-Key", required = false) String claveIdempotencia) {
        ResultadoReemisionInvitacionOperador resultado = administracionInvitaciones.reemitir(
                operadorId, ifMatch, claveIdempotencia);
        HttpHeaders encabezados = encabezadosPrivados();
        encabezados.setETag("\"" + resultado.revisionAcceso() + "\"");
        return ResponseEntity.ok().headers(encabezados).body(resultado.respuesta());
    }

    @ExceptionHandler(ErrorConfiguracion.class)
    public ResponseEntity<RespuestaErrorActivacionOperador> errorNegocio(ErrorConfiguracion excepcion) {
        HttpHeaders encabezados = encabezadosPrivados();
        if (excepcion.estadoHttp() == HttpStatus.TOO_MANY_REQUESTS) {
            encabezados.set("Retry-After", "900");
        }
        return ResponseEntity.status(excepcion.estadoHttp()).headers(encabezados)
                .body(new RespuestaErrorActivacionOperador(
                        excepcion.codigo() == null ? "OPERACION_NO_COMPLETADA" : excepcion.codigo(),
                        excepcion.getMessage()));
    }

    @ExceptionHandler({DataAccessException.class, TransactionException.class})
    public ResponseEntity<RespuestaErrorActivacionOperador> errorPersistencia(RuntimeException excepcion) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .headers(encabezadosPrivados())
                .body(new RespuestaErrorActivacionOperador(
                        "SERVICIO_NO_DISPONIBLE", "No pudimos completar esto ahora. Inténtalo más tarde."));
    }

    private static HttpHeaders encabezadosPrivados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.setCacheControl("no-store");
        encabezados.set("Referrer-Policy", "no-referrer");
        return encabezados;
    }
}
