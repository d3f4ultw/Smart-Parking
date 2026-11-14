package mx.smartparking.api.configuracion;

import mx.smartparking.api.seguridad.PrincipalPropietario;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Permite consultar la configuración inicial y administrar los datos permitidos desde el panel del
 * propietario.
 */
@RestController
@RequestMapping("/api/v1")
public class ConfiguracionControlador {

    private final ConfiguracionServicio servicio;

    public ConfiguracionControlador(ConfiguracionServicio servicio) {
        this.servicio = servicio;
    }

    /** Indica si el estacionamiento está configurado sin mostrar datos privados del propietario. */
    @GetMapping("/configuracion/estado")
    public EstadoPublico consultarEstado() {
        return new EstadoPublico(servicio.consultarEstado());
    }

    /** Guarda la configuración inicial del estacionamiento una sola vez. */
    @PostMapping("/configuracion/inicial")
    public ResponseEntity<ResultadoConfiguracion> configurarInicial(
            @RequestBody SolicitudConfiguracion solicitud,
            @RequestHeader("Idempotency-Key") String claveIdempotencia) {
        ResultadoConfiguracion resultado = servicio.configurarInicial(solicitud, claveIdempotencia);
        return ResponseEntity.status(201)
                .header(HttpHeaders.ETAG, etag(resultado.revision()))
                .body(resultado);
    }

    /**
     * Muestra al propietario los datos permitidos y la versión necesaria para evitar cambios con
     * información desactualizada.
     */
    @GetMapping("/panel")
    public ResponseEntity<PanelPropietario> obtenerPanel(
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        PanelPropietario panel = servicio.obtenerPanel(propietario.revisionPropietario());
        return ResponseEntity.ok().header(HttpHeaders.ETAG, etag(panel.revision())).body(panel);
    }

    /** Cambia únicamente el nombre del estacionamiento. */
    @PatchMapping("/estacionamiento")
    public ResponseEntity<PanelPropietario> renombrar(
            @RequestBody RenombrarEstacionamientoSolicitud solicitud,
            @RequestHeader("If-Match") String ifMatch,
            @RequestHeader("Idempotency-Key") String claveIdempotencia,
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        PanelPropietario panel = servicio.renombrar(
                solicitud == null ? null : solicitud.nombre(),
                parsearEtag(ifMatch),
                propietario.revisionPropietario(),
                claveIdempotencia);
        return ResponseEntity.ok().header(HttpHeaders.ETAG, etag(panel.revision())).body(panel);
    }

    /**
     * Cambia el tipo y horario si la información sigue vigente; repetir la misma solicitud no aplica
     * el cambio dos veces.
     */
    @PatchMapping("/estacionamiento/datos")
    public ResponseEntity<PanelPropietario> actualizarDatosEstacionamiento(
            @RequestBody ActualizarDatosEstacionamientoSolicitud solicitud,
            @RequestHeader("If-Match") String ifMatch,
            @RequestHeader("Idempotency-Key") String claveIdempotencia,
            @AuthenticationPrincipal PrincipalPropietario propietario) {
        if (solicitud == null) {
            throw new IllegalArgumentException("Completa el tipo y el horario del estacionamiento.");
        }
        ActualizarDatosEstacionamientoSolicitud.DatosEditables datos = solicitud.validar();
        PanelPropietario panel = servicio.actualizarDatosEstacionamiento(
                datos.tipo(),
                datos.horario(),
                parsearEtag(ifMatch),
                propietario.revisionPropietario(),
                claveIdempotencia);
        return ResponseEntity.ok().header(HttpHeaders.ETAG, etag(panel.revision())).body(panel);
    }

    private static long parsearEtag(String etag) {
        if (etag == null || etag.length() < 3 || etag.charAt(0) != '"' || etag.charAt(etag.length() - 1) != '"') {
            throw new ErrorConfiguracion(HttpStatus.BAD_REQUEST,
                    "La información cambió. Actualiza la pantalla e inténtalo de nuevo.");
        }
        try {
            return Long.parseLong(etag.substring(1, etag.length() - 1));
        } catch (NumberFormatException excepcion) {
            throw new ErrorConfiguracion(HttpStatus.BAD_REQUEST,
                    "La información cambió. Actualiza la pantalla e inténtalo de nuevo.");
        }
    }

    private static String etag(long revision) {
        return "\"" + revision + "\"";
    }

    public record EstadoPublico(EstadoConfiguracion estado) {
    }
}
