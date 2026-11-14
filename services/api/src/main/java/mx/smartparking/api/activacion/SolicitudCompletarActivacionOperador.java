package mx.smartparking.api.activacion;

/** Reúne los datos para completar la activación y oculta el código y la contraseña si se convierte en texto. */
public record SolicitudCompletarActivacionOperador(
        String token,
        String contrasena,
        String confirmarContrasena) {

    @Override
    public String toString() {
        return "SolicitudCompletarActivacionOperador[datos=[REDACTADOS]]";
    }
}
