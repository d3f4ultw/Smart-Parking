package mx.smartparking.api.recuperacion;

/** Reúne la contraseña nueva y el código del enlace sin mostrarlos si los datos se registran como texto. */
public record SolicitudCompletarRecuperacionOperador(
        String token,
        String contrasena,
        String confirmarContrasena) {

    @Override
    public String toString() {
        return "SolicitudCompletarRecuperacionOperador[datos=[REDACTADOS]]";
    }
}
