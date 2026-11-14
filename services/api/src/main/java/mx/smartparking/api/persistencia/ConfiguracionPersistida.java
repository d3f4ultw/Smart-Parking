package mx.smartparking.api.persistencia;

import java.time.Instant;
import java.time.LocalTime;
import java.util.UUID;
import mx.smartparking.api.configuracion.EstadoConfiguracion;
import mx.smartparking.api.configuracion.ModoHorario;
import mx.smartparking.api.configuracion.TipoEstacionamiento;

/** Reúne los datos internos de la configuración guardada y no debe enviarse directamente como respuesta. */
public record ConfiguracionPersistida(
        EstadoConfiguracion estado,
        long revision,
        long revisionPropietario,
        UUID estacionamientoId,
        String propietarioNombres,
        String propietarioPrimerApellido,
        String propietarioSegundoApellido,
        String correoPropietario,
        String hashContrasenaAcceso,
        String hashContrasenaAdministrativa,
        String nombreEstacionamiento,
        TipoEstacionamiento tipoEstacionamiento,
        ModoHorario modoHorario,
        String zonaHoraria,
        LocalTime horaApertura,
        LocalTime horaCierre,
        UUID transferId,
        String hashGrantTransferencia,
        Instant grantVenceEn,
        String hashRecuperacionTransferencia,
        String estadoAvisoTransferencia,
        String estadoAvisoBienvenida,
        UUID ultimaOperacionId,
        String ultimaClaveIdempotenciaHash) {

    @Override
    public String toString() {
        return "ConfiguracionPersistida[estado=" + estado + ", revision=" + revision
                + ", revisionPropietario=" + revisionPropietario + ", secretos=[REDACTADOS]]";
    }
}
