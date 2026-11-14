package mx.smartparking.ownerconsole.modelo;

/**
 * indica si falta configurar el estacionamiento, si ya está configurado
 * o si espera completar el cambio de propietario
 */
public enum EstadoConfiguracion {
    SIN_CONFIGURAR,
    CONFIGURADA,
    TRANSFERENCIA_PENDIENTE;

    /** busca el estado por el nombre recibido y produce un error cuando no existe. */
    public static EstadoConfiguracion desde(String valor) {
        return EstadoConfiguracion.valueOf(valor);
    }
}
