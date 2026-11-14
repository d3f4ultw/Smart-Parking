package mx.smartparking.api.rfid1.controlador;

import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.CandidatoPersona;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.Cancelacion;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.Modalidad;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.Pagina;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.Tarjeta;
import mx.smartparking.api.rfid1.servicio.ServicioTarjetasRfid1;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Permite buscar personas, consultar tarjetas registradas y cancelar una tarjeta de forma permanente. */
@RestController
@RequestMapping("/api/v1/tarjetas-rfid")
public final class ControladorTarjetasRfid1 {

    private final ServicioTarjetasRfid1 servicio;

    public ControladorTarjetasRfid1(ServicioTarjetasRfid1 servicio) {
        this.servicio = servicio;
    }

    /** Indica el tipo de estacionamiento que necesita la pantalla para buscar personas autorizadas. */
    @GetMapping("/modalidad")
    public ResponseEntity<Modalidad> consultarModalidad(
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        return ResponseEntity.ok().headers(encabezadosPrivados()).body(servicio.consultarModalidad(propietario));
    }

    /** Busca personas cuando el texto escrito tiene la longitud necesaria y devuelve las coincidencias. */
    @GetMapping("/personas")
    public ResponseEntity<List<CandidatoPersona>> buscarPersonas(
            @RequestParam String tipoEntidad,
            @RequestParam(required = false) String busqueda,
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        return ResponseEntity.ok().headers(encabezadosPrivados())
                .body(servicio.buscarPersonas(tipoEntidad, busqueda, propietario));
    }

    /** Muestra al propietario una página del historial de tarjetas con sus números de identificación. */
    @GetMapping
    public ResponseEntity<Pagina> listar(
            @RequestParam String tipoEntidad,
            @RequestParam(required = false) String estado,
            @RequestParam(required = false) String pagina,
            @RequestParam(required = false) String busqueda,
            HttpServletRequest solicitud,
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        String[] terminos = solicitud.getParameterValues("busqueda");
        if (terminos != null && terminos.length > 1) {
            throw new ErrorConfiguracion(HttpStatus.BAD_REQUEST, "Revisa el texto de búsqueda.", "BUSQUEDA_NO_VALIDA");
        }
        return ResponseEntity.ok().headers(encabezadosPrivados())
                .body(servicio.listar(tipoEntidad, estado, pagina, busqueda, propietario));
    }

    /** Muestra al propietario los datos de una tarjeta, incluido su número de identificación. */
    @GetMapping("/{asociacionId}")
    public ResponseEntity<Tarjeta> consultar(
            @PathVariable long asociacionId,
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        return ResponseEntity.ok().headers(encabezadosPrivados())
                .body(servicio.consultar(asociacionId, propietario));
    }

    /** Cancela permanentemente una asociación activa. */
    @PostMapping("/{asociacionId}/cancelacion")
    public ResponseEntity<Cancelacion> cancelar(
            @PathVariable long asociacionId,
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        return ResponseEntity.ok().headers(encabezadosPrivados())
                .body(servicio.cancelar(asociacionId, propietario));
    }

    private static HttpHeaders encabezadosPrivados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.set(HttpHeaders.CACHE_CONTROL, "no-store, private");
        encabezados.set(HttpHeaders.VARY, HttpHeaders.COOKIE);
        return encabezados;
    }
}
