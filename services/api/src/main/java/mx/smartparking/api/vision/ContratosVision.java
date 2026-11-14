package mx.smartparking.api.vision;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

/** Reúne los datos que se necesitan para configurar la cámara y comunicar lo que observa. */
public final class ContratosVision {
    private ContratosVision() {
    }

    public record SolicitudFuente(UUID fuenteId) { }
    public record RespuestaFuente(UUID fuenteId) { }
    public record ZonaConfiguracion(UUID visionZoneId, String etiqueta, UUID cajonId) { }
    public record SolicitudCalibracion(List<ZonaConfiguracion> zonas) { }
    public record RespuestaCalibracion(UUID fuenteId, List<ZonaConfiguracion> zonas) { }
    public record SolicitudSesion(UUID fuenteId, UUID solicitudId, Instant iniciadaEn) { }
    public record RespuestaSesion(UUID sesionId) { }
    public record ZonaObservacion(UUID visionZoneId, String estado) { }
    public record SolicitudObservacion(UUID fuenteId, UUID sesionId, Long secuencia, UUID solicitudId,
            Instant observadoEn, List<ZonaObservacion> zonas) { }
    public record RespuestaObservacion(boolean aceptada) { }
    public record EstadoCajon(UUID cajonId, String etiqueta, String estado,
            String ultimoEstadoConfirmado, Instant observadoEn, String displayName) { }
    public record SolicitudNombreCajon(String displayName) { }
}
