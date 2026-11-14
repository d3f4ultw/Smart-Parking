package mx.smartparking.api.configuracion;

/** Contiene el nombre nuevo del estacionamiento que el propietario desea guardar. */
public record RenombrarEstacionamientoSolicitud(String nombre) {

    public String validar() {
        if (nombre == null || nombre.isBlank()) {
            throw new IllegalArgumentException("Escribe un nombre para el estacionamiento.");
        }
        if (nombre.strip().length() > 120) {
            throw new IllegalArgumentException("Escribe un nombre más corto para el estacionamiento.");
        }
        return nombre.strip();
    }
}
