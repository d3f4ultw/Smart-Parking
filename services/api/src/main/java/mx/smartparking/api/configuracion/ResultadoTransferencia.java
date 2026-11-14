package mx.smartparking.api.configuracion;

import java.time.Instant;
import java.util.UUID;
import mx.smartparking.api.correo.EstadoAviso;

/**
 * Reúne el permiso y la fecha límite para completar el cambio de propietario, junto con el resultado
 * del aviso por correo.
 */
public record ResultadoTransferencia(
        EstadoConfiguracion estado,
        UUID transferenciaId,
        String grant,
        Instant venceEn,
        EstadoAviso avisoTransferencia) {

    @Override
    public String toString() {
        return "ResultadoTransferencia[estado=" + estado + ", transferenciaId=" + transferenciaId
                + ", grant=[REDACTADO], venceEn=" + venceEn + ", avisoTransferencia=" + avisoTransferencia + "]";
    }
}
