package mx.smartparking.api.persistencia.membresia;

/** Indica si un cambio ya guardado modificó información de la membresía que se muestra al cliente. */
public record ResultadoActualizacionMembresia(boolean cambioVisible) {
}
