package mx.smartparking.api.clientes.membresia.controlador;

import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.util.UUID;
import mx.smartparking.api.clientes.membresia.modelo.RespuestaCheckoutMembresia;
import mx.smartparking.api.clientes.membresia.modelo.RespuestaEstadoCheckoutMembresia;
import mx.smartparking.api.clientes.membresia.modelo.ResultadoInicioCheckout;
import mx.smartparking.api.clientes.membresia.servicio.ServicioCheckoutMembresia;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.ErrorConfiguracionControlador.RespuestaError;
import mx.smartparking.api.seguridad.cliente.PrincipalCliente;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Permite al cliente que inició sesión comenzar y consultar el pago de su membresía. */
@RestController
@RequestMapping("/api/v1/clientes/membresia/checkout")
public final class ControladorCheckoutMembresia {

    private final ServicioCheckoutMembresia servicio;

    public ControladorCheckoutMembresia(ServicioCheckoutMembresia servicio) {
        this.servicio = servicio;
    }

    @PostMapping
    public ResponseEntity<RespuestaCheckoutMembresia> iniciar(
            @RequestHeader(name = "Idempotency-Key", required = false) String claveIdempotencia,
            HttpServletRequest solicitud) throws IOException {
        exigirSinCuerpo(solicitud);
        ResultadoInicioCheckout resultado = servicio.iniciar(clienteIdActual(), claveIdempotencia);
        HttpStatus estado = resultado.nuevo() ? HttpStatus.CREATED : HttpStatus.OK;
        return ResponseEntity.status(estado).headers(encabezadosPrivados()).body(resultado.respuesta());
    }

    @GetMapping("/{intentoId}")
    public ResponseEntity<RespuestaEstadoCheckoutMembresia> consultar(@PathVariable String intentoId) {
        UUID id = parsearIntento(intentoId);
        return ResponseEntity.ok().headers(encabezadosPrivados())
                .body(servicio.consultar(clienteIdActual(), id));
    }

    @ExceptionHandler(ErrorConfiguracion.class)
    public ResponseEntity<RespuestaError> errorDeNegocio(ErrorConfiguracion excepcion) {
        return ResponseEntity.status(excepcion.estadoHttp()).headers(encabezadosPrivados())
                .body(new RespuestaError(excepcion.codigo() == null ? "OPERACION_NO_COMPLETADA" : excepcion.codigo(),
                        excepcion.getMessage()));
    }

    private static UUID clienteIdActual() {
        Authentication autenticacion = SecurityContextHolder.getContext().getAuthentication();
        if (autenticacion != null && autenticacion.isAuthenticated()
                && autenticacion.getPrincipal() instanceof PrincipalCliente cliente) {
            return cliente.cuentaId();
        }
        throw new ErrorConfiguracion(HttpStatus.UNAUTHORIZED,
                "Inicia sesión para continuar.", "SESION_NO_VIGENTE");
    }

    private static UUID parsearIntento(String valor) {
        try {
            return UUID.fromString(valor);
        } catch (IllegalArgumentException excepcion) {
            throw new ErrorConfiguracion(HttpStatus.BAD_REQUEST,
                    "El identificador del pago no es válido.", "CHECKOUT_NO_VALIDO");
        }
    }

    private static void exigirSinCuerpo(HttpServletRequest solicitud) throws IOException {
        if (solicitud.getContentLengthLong() > 0 || solicitud.getInputStream().read() != -1) {
            throw new ErrorConfiguracion(HttpStatus.BAD_REQUEST,
                    "Envía la solicitud sin datos adicionales.", "SOLICITUD_NO_VALIDA");
        }
    }

    private static HttpHeaders encabezadosPrivados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.setCacheControl("no-store, private");
        encabezados.setVary(java.util.List.of(HttpHeaders.COOKIE));
        return encabezados;
    }
}
