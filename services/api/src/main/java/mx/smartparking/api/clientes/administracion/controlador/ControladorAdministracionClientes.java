package mx.smartparking.api.clientes.administracion.controlador;

import java.util.List;
import mx.smartparking.api.clientes.administracion.modelo.DetalleClienteAdministracion;
import mx.smartparking.api.clientes.administracion.modelo.PaginaClientesAdministracion;
import mx.smartparking.api.clientes.administracion.servicio.ServicioAdministracionClientes;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.ErrorConfiguracionControlador.RespuestaError;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.TransactionException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Permite al personal autorizado consultar la lista de clientes y sus membresías. */
@RestController
@RequestMapping("/api/v1/clientes/administracion")
public final class ControladorAdministracionClientes {

    private final ServicioAdministracionClientes servicio;

    public ControladorAdministracionClientes(ServicioAdministracionClientes servicio) {
        this.servicio = servicio;
    }

    /** Muestra al personal autorizado una página de clientes que cumplen los filtros elegidos. */
    @GetMapping
    public ResponseEntity<PaginaClientesAdministracion> listar(
            @RequestParam(value = "pagina", required = false) String pagina,
            @RequestParam(value = "estado", required = false) String estado,
            @RequestParam(value = "busqueda", required = false) String busqueda,
            @AuthenticationPrincipal PrincipalPropietario principal) {
        PaginaClientesAdministracion resultado = servicio.listar(
                pagina == null ? "1" : pagina, estado, busqueda, principal);
        return ResponseEntity.ok().headers(encabezadosPrivados()).body(resultado);
    }

    /** Busca la información guardada de la membresía de un cliente a partir de su código público. */
    @GetMapping("/{codigoPublico}")
    public ResponseEntity<DetalleClienteAdministracion> consultarDetalle(
            @PathVariable String codigoPublico,
            @AuthenticationPrincipal PrincipalPropietario principal) {
        DetalleClienteAdministracion resultado = servicio.consultarDetalle(codigoPublico, principal);
        return ResponseEntity.ok().headers(encabezadosPrivados()).body(resultado);
    }

    @ExceptionHandler(ErrorConfiguracion.class)
    public ResponseEntity<RespuestaError> errorConfiguracion(ErrorConfiguracion excepcion) {
        return ResponseEntity.status(excepcion.estadoHttp()).headers(encabezadosPrivados())
                .body(new RespuestaError(
                        excepcion.codigo() == null ? "OPERACION_NO_COMPLETADA" : excepcion.codigo(),
                        excepcion.getMessage()));
    }

    @ExceptionHandler({DataAccessException.class, TransactionException.class})
    public ResponseEntity<RespuestaError> errorPersistencia(RuntimeException excepcion) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).headers(encabezadosPrivados())
                .body(new RespuestaError(
                        "SERVICIO_NO_DISPONIBLE",
                        "No pudimos cargar esta información. Inténtalo más tarde."));
    }

    private static HttpHeaders encabezadosPrivados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.setCacheControl("no-store, private");
        encabezados.setVary(List.of(HttpHeaders.COOKIE));
        return encabezados;
    }
}
