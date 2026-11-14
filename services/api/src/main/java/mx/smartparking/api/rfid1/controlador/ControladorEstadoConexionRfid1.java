package mx.smartparking.api.rfid1.controlador;

import mx.smartparking.api.configuracion.ErrorConfiguracionControlador.RespuestaError;
import mx.smartparking.api.rfid1.servicio.ServicioEstadoConexionRfid1;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Permite al personal consultar si el lector de tarjetas respondió recientemente. */
@RestController
@RequestMapping("/api/v1/rfid-1/estado-conexion")
public final class ControladorEstadoConexionRfid1 {

    private final ServicioEstadoConexionRfid1 servicio;

    public ControladorEstadoConexionRfid1(ServicioEstadoConexionRfid1 servicio) {
        this.servicio = servicio;
    }

    @GetMapping
    public ResponseEntity<?> consultar(@AuthenticationPrincipal PrincipalPropietario propietario) {
        if (propietario == null) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                    .headers(encabezadosPrivados())
                    .body(new RespuestaError("SESION_NO_VIGENTE", "Inicia sesión para continuar."));
        }
        if (propietario.rol() != RolCuenta.DUENO && propietario.rol() != RolCuenta.OPERADOR) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN)
                    .headers(encabezadosPrivados())
                    .body(new RespuestaError("PERMISO_INSUFICIENTE", "No tienes permiso."));
        }
        return ResponseEntity.ok().headers(encabezadosPrivados()).body(servicio.consultar());
    }

    private static HttpHeaders encabezadosPrivados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.set(HttpHeaders.CACHE_CONTROL, "no-store, private");
        encabezados.set(HttpHeaders.VARY, HttpHeaders.COOKIE);
        return encabezados;
    }
}
