package mx.smartparking.ownerconsole.modelo;

/** Cambios editables del tipo y horario del estacionamiento. */
public record EdicionEstacionamiento(
        String tipo,
        String modoHorario,
        String zonaHoraria,
        String horaApertura,
        String horaCierre) {
}
