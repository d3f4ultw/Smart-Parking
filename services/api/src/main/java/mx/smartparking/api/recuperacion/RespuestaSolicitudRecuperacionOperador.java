package mx.smartparking.api.recuperacion;

import java.time.Instant;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;

/** Indica qué ocurrió al enviar el correo sin mostrar el código del enlace de recuperación. */
public record RespuestaSolicitudRecuperacionOperador(
        EstadoEnvioInvitacion estadoEnvio,
        Instant venceEn,
        Instant recuperacionDisponibleEn) {
}
