package mx.smartparking.api.configuracion;

import mx.smartparking.api.correo.EstadoAviso;

/** Indica el estado guardado del estacionamiento y el resultado del correo de bienvenida. */
public record ResultadoConfiguracion(
        EstadoConfiguracion estado,
        long revision,
        EstadoAviso avisoBienvenida) {
}
