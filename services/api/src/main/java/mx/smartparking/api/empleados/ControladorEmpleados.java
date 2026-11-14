package mx.smartparking.api.empleados;

import java.util.Map;
import java.util.UUID;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.empleados.coordinacion.ResultadoAccionEmpleadoOperador;
import mx.smartparking.api.empleados.coordinacion.ResultadoCambioCorreoEmpleadoOperador;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import org.springframework.http.CacheControl;
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

/** Recibe las solicitudes del propietario para consultar y administrar a los empleados. */
@RestController
@RequestMapping("/api/v1/empleados")
public class ControladorEmpleados {

    private final ServicioEmpleados servicio;

    public ControladorEmpleados(ServicioEmpleados servicio) {
        this.servicio = servicio;
    }

    /** Devuelve una página de empleados y los datos necesarios para avisar si después hay cambios. */
    @GetMapping
    public ResponseEntity<PaginaEmpleados> listar(
            @RequestParam(value = "pagina", required = false) String pagina,
            @RequestParam(value = "busqueda", required = false) String busqueda,
            @RequestParam(value = "soloElegiblesOperador", defaultValue = "false") boolean soloElegiblesOperador) {
        String paginaEfectiva = pagina == null ? "1" : pagina;
        PaginaEmpleados resultado = !soloElegiblesOperador && busqueda == null
                ? servicio.listar(paginaEfectiva)
                : servicio.listar(paginaEfectiva, busqueda, soloElegiblesOperador);
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(resultado);
    }

    /** Muestra los datos actuales del empleado para que el propietario pueda administrarlo. */
    @GetMapping("/{id}")
    public ResponseEntity<Empleado> consultar(@PathVariable String id) {
        Empleado empleado = servicio.consultar(id);
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .header(HttpHeaders.ETAG, etag(empleado.revisionTexto()))
                .body(empleado);
    }

    /** Registra al empleado o devuelve el resultado anterior si se repite la misma solicitud. */
    @PostMapping
    public ResponseEntity<RespuestaRegistroEmpleado> registrar(
            @RequestBody(required = false) SolicitudRegistroEmpleado solicitud,
            @RequestHeader(value = "Idempotency-Key", required = false) String claveIdempotencia,
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        RespuestaRegistroEmpleado respuesta = servicio.registrar(solicitud, claveIdempotencia, propietario);
        return ResponseEntity.status(HttpStatus.CREATED)
                .cacheControl(CacheControl.noStore())
                .body(respuesta);
    }

    /** Actualiza el estado del empleado junto con el acceso vinculado, si existe. */
    @PatchMapping("/{id}/estado")
    public ResponseEntity<Empleado> cambiarEstado(
            @PathVariable String id,
            @RequestBody(required = false) SolicitudEstadoEmpleado solicitud,
            @RequestHeader(value = "If-Match", required = false) String ifMatch,
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        Empleado empleado = servicio.cambiarEstado(
                id, solicitud == null ? null : solicitud.estado(), ifMatch, propietario);
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .header(HttpHeaders.ETAG, etag(empleado.revisionTexto()))
                .body(empleado);
    }

    /** Cambia o quita el correo del empleado y actualiza también la cuenta de operador asociada, si existe. */
    @PatchMapping("/{id}/correo")
    public ResponseEntity<ResultadoCambioCorreoEmpleadoOperador> cambiarCorreo(
            @PathVariable String id,
            @RequestBody(required = false) Map<String, Object> solicitud,
            @RequestHeader(value = "If-Match", required = false) String ifMatch,
            @RequestHeader(value = "Idempotency-Key", required = false) String claveIdempotencia,
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        String correo = correoSolicitado(solicitud);
        ResultadoCambioCorreoEmpleadoOperador resultado = servicio.cambiarCorreo(
                id, correo, ifMatch, claveIdempotencia, propietario);
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .header(HttpHeaders.ETAG, etag(resultado.revisionEmpleado()))
                .body(resultado);
    }

    /** Crea o reactiva la cuenta de operador del empleado y prepara una invitación para que pueda entrar. */
    @PostMapping("/{id}/operador/promocion")
    public ResponseEntity<ResultadoAccionEmpleadoOperador> promocionar(
            @PathVariable String id,
            @RequestBody Map<String, Object> solicitud,
            @RequestHeader(value = "If-Match", required = false) String ifMatch,
            @RequestHeader(value = "Idempotency-Key", required = false) String claveIdempotencia,
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        String correo = correoPromocionSolicitado(solicitud);
        ResultadoAccionEmpleadoOperador resultado = correo == null
                ? servicio.promocionar(id, ifMatch, claveIdempotencia, propietario)
                : servicio.promocionar(id, correo, ifMatch, claveIdempotencia, propietario);
        return respuestaAccion(resultado);
    }

    /** Retira el acceso de operador y conserva la identidad de empleado vinculada. */
    @PostMapping("/{id}/operador/desactivacion")
    public ResponseEntity<ResultadoAccionEmpleadoOperador> desactivarAcceso(
            @PathVariable String id,
            @RequestBody Map<String, Object> solicitud,
            @RequestHeader(value = "If-Match", required = false) String ifMatch,
            @RequestHeader(value = "Idempotency-Key", required = false) String claveIdempotencia,
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        exigirCuerpoVacio(solicitud);
        ResultadoAccionEmpleadoOperador resultado = servicio.desactivarAcceso(
                id, ifMatch, claveIdempotencia, propietario);
        return respuestaAccion(resultado);
    }

    /** Une la cuenta de operador con el empleado elegido después de que el propietario confirme la acción. */
    @PostMapping("/{id}/operador/vinculacion")
    public ResponseEntity<ResultadoAccionEmpleadoOperador> vincular(
            @PathVariable String id,
            @RequestBody(required = false) SolicitudVinculacionOperador solicitud,
            @RequestHeader(value = "If-Match", required = false) String ifMatch,
            @RequestHeader(value = "Idempotency-Key", required = false) String claveIdempotencia,
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        if (solicitud == null || solicitud.operadorId() == null || solicitud.revisionOperador() == null
                || solicitud.copiarCorreoOperador() == null) {
            throw solicitudNoValida();
        }
        ResultadoAccionEmpleadoOperador resultado = servicio.vincular(
                id,
                solicitud.operadorId(),
                solicitud.revisionOperador(),
                Boolean.TRUE.equals(solicitud.copiarCorreoOperador()),
                ifMatch, claveIdempotencia, propietario);
        return respuestaAccion(resultado);
    }

    private static ResponseEntity<ResultadoAccionEmpleadoOperador> respuestaAccion(
            ResultadoAccionEmpleadoOperador resultado) {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .header(HttpHeaders.ETAG, etag(resultado.revisionEmpleado()))
                .body(resultado);
    }

    private static String correoSolicitado(Map<String, Object> solicitud) {
        if (solicitud == null || !solicitud.containsKey("correo")) {
            throw solicitudNoValida();
        }
        Object valor = solicitud.get("correo");
        if (valor != null && !(valor instanceof String)) {
            throw solicitudNoValida();
        }
        return (String) valor;
    }

    private static void exigirCuerpoVacio(Map<String, Object> solicitud) {
        if (solicitud == null || !solicitud.isEmpty()) {
            throw solicitudNoValida();
        }
    }

    private static String correoPromocionSolicitado(Map<String, Object> solicitud) {
        if (solicitud == null || solicitud.isEmpty()) {
            return null;
        }
        if (solicitud.size() != 1 || !solicitud.containsKey("correo")
                || !(solicitud.get("correo") instanceof String correo)) {
            throw solicitudNoValida();
        }
        return correo;
    }

    private static ErrorConfiguracion solicitudNoValida() {
        return new ErrorConfiguracion(HttpStatus.BAD_REQUEST, "Revisa los datos e inténtalo de nuevo.",
                "SOLICITUD_NO_VALIDA");
    }

    private static String etag(String revision) {
        return "\"" + revision + "\"";
    }

    /** Indica si el propietario desea activar o desactivar a un empleado. */
    public record SolicitudEstadoEmpleado(String estado) {
    }

    /** Contiene la versión de la cuenta existente que el propietario eligió vincular con un empleado. */
    public record SolicitudVinculacionOperador(
            UUID operadorId, String revisionOperador, Boolean copiarCorreoOperador) {
    }
}
