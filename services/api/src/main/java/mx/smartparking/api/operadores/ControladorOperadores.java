package mx.smartparking.api.operadores;

import java.util.UUID;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Recibe las solicitudes del propietario para registrar y administrar cuentas de operador. */
@RestController
@RequestMapping("/api/v1/operadores")
public class ControladorOperadores {

    private final ServicioOperadores servicio;
    private final ServicioAdministracionOperadores administracion;

    public ControladorOperadores(
            ServicioOperadores servicio, ServicioAdministracionOperadores administracion) {
        this.servicio = servicio;
        this.administracion = administracion;
    }

    /** Muestra al propietario una página de cuentas de operador y sus invitaciones. */
    @GetMapping
    public PaginaOperadores listar(
            @RequestParam(value = "pagina", required = false) String pagina,
            @RequestParam(value = "busqueda", required = false) String busqueda,
            @RequestParam(value = "estado", required = false) String estado,
            @AuthenticationPrincipal PrincipalPropietario principal) {
        return servicio.listar(pagina == null ? "1" : pagina, busqueda, estado, principal);
    }

    /**
     * Muestra la información actual del operador e indica su versión para evitar cambios con datos
     * antiguos.
     */
    @GetMapping("/{operadorId}")
    public ResponseEntity<DetalleOperador> consultarDetalle(
            @PathVariable UUID operadorId,
            @AuthenticationPrincipal PrincipalPropietario principal) {
        DetalleOperadorVersionado resultado = administracion.consultar(operadorId, principal);
        return ResponseEntity.ok()
                .header(HttpHeaders.ETAG, etag(resultado.revisionAcceso()))
                .body(resultado.detalle());
    }

    /** Activa o desactiva la cuenta únicamente si la información consultada todavía está actualizada. */
    @PatchMapping("/{operadorId}/estado")
    public ResponseEntity<DetalleOperador> cambiarEstado(
            @PathVariable UUID operadorId,
            @RequestBody(required = false) SolicitudEstadoOperador solicitud,
            @RequestHeader(value = HttpHeaders.IF_MATCH, required = false) String ifMatch,
            @RequestHeader(value = "Idempotency-Key", required = false) String claveIdempotencia,
            @AuthenticationPrincipal PrincipalPropietario principal) {
        DetalleOperadorVersionado resultado = administracion.cambiarEstado(
                operadorId, solicitud == null ? null : solicitud.estado(),
                ifMatch, claveIdempotencia, principal);
        return ResponseEntity.ok()
                .header(HttpHeaders.ETAG, etag(resultado.revisionAcceso()))
                .body(resultado.detalle());
    }

    /** Registra una cuenta pendiente o devuelve el resultado anterior si se repite la misma solicitud. */
    @PostMapping
    public ResponseEntity<RespuestaRegistroOperador> registrar(
            @RequestBody(required = false) SolicitudRegistroOperador solicitud,
            @RequestHeader(value = "Idempotency-Key", required = false) String claveIdempotencia,
            @AuthenticationPrincipal PrincipalPropietario principal) {
        RespuestaRegistroOperador respuesta = servicio.registrar(solicitud, claveIdempotencia, principal);
        return ResponseEntity.status(HttpStatus.CREATED).body(respuesta);
    }

    private static String etag(long revision) {
        return "\"" + revision + "\"";
    }
}
