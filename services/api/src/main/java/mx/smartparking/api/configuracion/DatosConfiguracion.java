package mx.smartparking.api.configuracion;

/** Reúne los datos del propietario, del estacionamiento y de su horario para guardar la configuración. */
public record DatosConfiguracion(
        DatosPropietario propietario,
        String nombreEstacionamiento,
        TipoEstacionamiento tipoEstacionamiento,
        HorarioConfiguracion horario) {

    @Override
    public String toString() {
        return "DatosConfiguracion[propietario=[REDACTADO], estacionamiento="
                + nombreEstacionamiento + "]";
    }
}
