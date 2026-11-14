package mx.smartparking.api.correo;

/** Define los avisos por correo que se envían después de confirmar un cambio de propietario. */
public interface NotificadorCorreo {

    /**
     * Intenta enviar una sola bienvenida al propietario recién configurado.
     *
     * @param correo destinatario
     * @param nombreCompleto nombre del propietario
     * @param nombreEstacionamiento nombre visible del estacionamiento
     * @return resultado del único intento
     */
    EstadoAviso enviarBienvenida(String correo, String nombreCompleto, String nombreEstacionamiento);

    /**
     * Intenta enviar una sola vez un correo al propietario anterior para informarle que dejó de tener acceso.
     *
     * @param correoAnterior destinatario anterior
     * @param nombreCompletoAnterior nombre del propietario anterior
     * @param nombreEstacionamiento nombre del estacionamiento
     * @return resultado del único intento
     */
    EstadoAviso notificarDesvinculacion(String correoAnterior, String nombreCompletoAnterior,
                                        String nombreEstacionamiento);
}
